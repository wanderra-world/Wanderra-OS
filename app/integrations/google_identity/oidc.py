"""Google Identity OIDC adapter for ADR-035 operator authentication."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

import requests
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from app.identity.operator_auth import VerifiedExternalIdentity

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
IDENTITY_SCOPES = ("openid", "email", "profile")


class GoogleOIDCError(RuntimeError):
    """Fail-closed identity-provider error containing no secret material."""


@dataclass(frozen=True, slots=True, repr=False)
class GoogleOIDCConfiguration:
    client_id: str
    client_secret: str
    redirect_uri: str

    def __post_init__(self) -> None:
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("Google Identity client configuration is required")
        if not self.redirect_uri.startswith(("https://", "http://localhost")):
            raise ValueError("Google Identity redirect URI must be secure")

    def __repr__(self) -> str:
        return (
            "GoogleOIDCConfiguration("
            f"client_id={self.client_id!r}, client_secret=<redacted>, "
            f"redirect_uri={self.redirect_uri!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class OIDCTransaction:
    workspace_id: uuid.UUID
    state: str
    nonce: str
    code_verifier: str
    issued_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            "OIDCTransaction("
            f"workspace_id={self.workspace_id!r}, state=<redacted>, "
            "nonce=<redacted>, code_verifier=<redacted>, "
            f"issued_at={self.issued_at!r}, expires_at={self.expires_at!r})"
        )


@dataclass(frozen=True, slots=True)
class OIDCStartResult:
    authorization_url: str
    transaction_cookie: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class GoogleIdentityClaims:
    issuer: str
    subject: str
    audience: str
    nonce: str
    expires_at: datetime
    issued_at: datetime
    email: str
    email_verified: bool

    def validated(self, *, client_id: str, now: datetime) -> GoogleIdentityClaims:
        if self.issuer not in GOOGLE_ISSUERS:
            raise GoogleOIDCError("Google identity issuer is invalid")
        if self.audience != client_id:
            raise GoogleOIDCError("Google identity audience is invalid")
        if not self.subject.strip() or not self.nonce.strip():
            raise GoogleOIDCError("Google identity claims are incomplete")
        if self.expires_at <= now or self.issued_at > now + timedelta(minutes=5):
            raise GoogleOIDCError("Google identity token is outside its valid lifetime")
        if not self.email_verified or not self.email.strip():
            raise GoogleOIDCError("Google identity email is not verified")
        return replace(self, issuer="https://accounts.google.com")

    def external_identity(self) -> VerifiedExternalIdentity:
        return VerifiedExternalIdentity(
            issuer=self.issuer,
            subject=self.subject,
            email=self.email,
            email_verified=self.email_verified,
        )


@dataclass(frozen=True, slots=True)
class OIDCCompleteResult:
    workspace_id: uuid.UUID
    claims: VerifiedExternalIdentity


class OIDCTransport(Protocol):
    async def exchange_and_verify(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> GoogleIdentityClaims: ...


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class OIDCTransactionCodec:
    """Authenticate short-lived pre-session state stored in a secure browser cookie."""

    def __init__(self, secret: str, *, lifetime: timedelta = timedelta(minutes=10)) -> None:
        if len(secret) < 16:
            raise ValueError("OIDC transaction signing secret is too short")
        if lifetime <= timedelta(0) or lifetime > timedelta(minutes=15):
            raise ValueError("OIDC transaction lifetime is invalid")
        self._key = hashlib.sha256(
            b"atlas-operator-oidc-state-v1\0" + secret.encode()
        ).digest()
        self._lifetime = lifetime

    def issue(self, *, workspace_id: uuid.UUID, now: datetime) -> tuple[OIDCTransaction, str]:
        transaction = OIDCTransaction(
            workspace_id=workspace_id,
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            code_verifier=secrets.token_urlsafe(64),
            issued_at=now,
            expires_at=now + self._lifetime,
        )
        payload = _b64encode(
            json.dumps(
                {
                    "v": 1,
                    "workspace_id": str(transaction.workspace_id),
                    "state": transaction.state,
                    "nonce": transaction.nonce,
                    "code_verifier": transaction.code_verifier,
                    "issued_at": int(transaction.issued_at.timestamp()),
                    "expires_at": int(transaction.expires_at.timestamp()),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        signature = _b64encode(hmac.digest(self._key, payload.encode(), "sha256"))
        return transaction, f"v1.{payload}.{signature}"

    def decode(self, value: str, *, now: datetime) -> OIDCTransaction:
        try:
            version, payload, signature = value.split(".")
            expected = _b64encode(hmac.digest(self._key, payload.encode(), "sha256"))
            if version != "v1" or not hmac.compare_digest(signature, expected):
                raise GoogleOIDCError("OIDC transaction is invalid")
            document = json.loads(_b64decode(payload))
            if document["v"] != 1:
                raise GoogleOIDCError("OIDC transaction version is invalid")
            transaction = OIDCTransaction(
                workspace_id=uuid.UUID(document["workspace_id"]),
                state=str(document["state"]),
                nonce=str(document["nonce"]),
                code_verifier=str(document["code_verifier"]),
                issued_at=datetime.fromtimestamp(int(document["issued_at"]), tz=UTC),
                expires_at=datetime.fromtimestamp(int(document["expires_at"]), tz=UTC),
            )
        except GoogleOIDCError:
            raise
        except Exception as error:
            raise GoogleOIDCError("OIDC transaction is invalid") from error
        if transaction.expires_at <= now or transaction.issued_at > now:
            raise GoogleOIDCError("OIDC transaction is expired or invalid")
        if not all((transaction.state, transaction.nonce, transaction.code_verifier)):
            raise GoogleOIDCError("OIDC transaction is incomplete")
        return transaction


class GoogleOIDCTransport:
    """Exchange an authorization code and verify Google's signed ID token."""

    def __init__(self, configuration: GoogleOIDCConfiguration) -> None:
        self._configuration = configuration

    async def exchange_and_verify(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> GoogleIdentityClaims:
        def exchange() -> GoogleIdentityClaims:
            response = requests.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": self._configuration.client_id,
                    "client_secret": self._configuration.client_secret,
                    "code": code,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": self._configuration.redirect_uri,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            raw_token = payload.get("id_token") if isinstance(payload, dict) else None
            if not isinstance(raw_token, str) or not raw_token:
                raise GoogleOIDCError("Google identity response is invalid")
            verified = id_token.verify_oauth2_token(
                raw_token,
                Request(),
                self._configuration.client_id,
            )
            audience = verified.get("aud")
            if not isinstance(audience, str):
                raise GoogleOIDCError("Google identity audience is invalid")
            claims = GoogleIdentityClaims(
                issuer=str(verified.get("iss", "")),
                subject=str(verified.get("sub", "")),
                audience=audience,
                nonce=str(verified.get("nonce", "")),
                expires_at=datetime.fromtimestamp(int(verified.get("exp", 0)), tz=UTC),
                issued_at=datetime.fromtimestamp(int(verified.get("iat", 0)), tz=UTC),
                email=str(verified.get("email", "")),
                email_verified=verified.get("email_verified") is True,
            )
            if not hmac.compare_digest(claims.nonce, expected_nonce):
                raise GoogleOIDCError("Google identity nonce is invalid")
            return claims.validated(
                client_id=self._configuration.client_id,
                now=datetime.now(UTC),
            )

        try:
            return await asyncio.to_thread(exchange)
        except GoogleOIDCError:
            raise
        except Exception as error:
            raise GoogleOIDCError("Google identity verification failed") from error


class GoogleOIDCProtocol:
    """Create and complete the bounded Google operator authentication flow."""

    def __init__(
        self,
        configuration: GoogleOIDCConfiguration,
        *,
        codec: OIDCTransactionCodec | None = None,
        transport: OIDCTransport | None = None,
    ) -> None:
        self._configuration = configuration
        self._codec = codec or OIDCTransactionCodec(configuration.client_secret)
        self._transport = transport or GoogleOIDCTransport(configuration)

    def start(self, *, workspace_id: uuid.UUID, now: datetime | None = None) -> OIDCStartResult:
        issued_at = now or datetime.now(UTC)
        transaction, cookie = self._codec.issue(workspace_id=workspace_id, now=issued_at)
        challenge = _b64encode(hashlib.sha256(transaction.code_verifier.encode()).digest())
        url = f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode({
            'client_id': self._configuration.client_id,
            'redirect_uri': self._configuration.redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(IDENTITY_SCOPES),
            'state': transaction.state,
            'nonce': transaction.nonce,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
            'prompt': 'select_account',
        })}"
        return OIDCStartResult(url, cookie, transaction.expires_at)

    def validate_callback(
        self,
        *,
        state: str,
        transaction_cookie: str,
        now: datetime,
    ) -> OIDCTransaction:
        transaction = self._codec.decode(transaction_cookie, now=now)
        if not hmac.compare_digest(transaction.state, state):
            raise GoogleOIDCError("Google identity state is invalid")
        return transaction

    async def complete(
        self,
        *,
        code: str,
        state: str,
        transaction_cookie: str,
        now: datetime | None = None,
    ) -> OIDCCompleteResult:
        checked_at = now or datetime.now(UTC)
        transaction = self.validate_callback(
            state=state,
            transaction_cookie=transaction_cookie,
            now=checked_at,
        )
        if not code:
            raise GoogleOIDCError("Google identity authorization code is missing")
        claims = await self._transport.exchange_and_verify(
            code=code,
            code_verifier=transaction.code_verifier,
            expected_nonce=transaction.nonce,
        )
        return OIDCCompleteResult(
            workspace_id=transaction.workspace_id,
            claims=claims.validated(
                client_id=self._configuration.client_id,
                now=checked_at,
            ).external_identity(),
        )
