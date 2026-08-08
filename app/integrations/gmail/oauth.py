"""Workspace-safe Google OAuth adapter for the canonical H2 transaction boundary."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlencode

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.oauth_transactions.contracts import OAuthCredentialGrant

GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_ALLOWED_SCOPES = frozenset(
    {GMAIL_READ_SCOPE, GMAIL_COMPOSE_SCOPE, GMAIL_SEND_SCOPE}
)
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

_OPERATION_SCOPES = {
    "profile": GMAIL_READ_SCOPE,
    "list": GMAIL_READ_SCOPE,
    "unread": GMAIL_READ_SCOPE,
    "search": GMAIL_READ_SCOPE,
    "draft": GMAIL_COMPOSE_SCOPE,
    "send": GMAIL_SEND_SCOPE,
}


class GmailOAuthError(RuntimeError):
    """Fail-closed provider error that never contains OAuth secret material."""


@dataclass(frozen=True, slots=True, repr=False)
class GmailOAuthConfiguration:
    client_id: str
    client_secret: str
    redirect_uri: str

    def __post_init__(self) -> None:
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("Google OAuth client configuration is required")
        if not self.redirect_uri.startswith("https://") and not self.redirect_uri.startswith(
            "http://localhost"
        ):
            raise ValueError("Google OAuth redirect URI must be secure")

    def __repr__(self) -> str:
        return (
            "GmailOAuthConfiguration("
            f"client_id={self.client_id!r}, client_secret=<redacted>, "
            f"redirect_uri={self.redirect_uri!r})"
        )


@dataclass(frozen=True, slots=True)
class GmailOAuthScopeProfile:
    scopes: tuple[str, ...]

    @classmethod
    def for_operations(cls, operations: tuple[str, ...]) -> GmailOAuthScopeProfile:
        if not operations:
            raise ValueError("at least one Gmail operation is required")
        try:
            scopes = tuple(sorted({_OPERATION_SCOPES[value] for value in operations}))
        except KeyError as error:
            raise ValueError("unsupported Gmail operation") from error
        return cls(scopes)


@dataclass(frozen=True, slots=True, repr=False)
class GmailOAuthGrant:
    payload: bytes
    scopes: tuple[str, ...]
    provider_account_id: str
    credential_kind: str = "oauth_refresh_token"
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        scopes = tuple(sorted(set(self.scopes)))
        if not scopes or not set(scopes).issubset(GMAIL_ALLOWED_SCOPES):
            raise ValueError("Gmail OAuth scope is invalid")
        account = self.provider_account_id.strip().lower()
        if not account:
            raise ValueError("Google account identifier is required")
        if not self.payload:
            raise ValueError("OAuth credential payload is required")
        object.__setattr__(self, "scopes", scopes)
        object.__setattr__(self, "provider_account_id", account)

    def __repr__(self) -> str:
        return (
            "GmailOAuthGrant(payload=<redacted>, "
            f"scopes={len(self.scopes)}, provider_account_id="
            f"{self.provider_account_id!r}, credential_kind={self.credential_kind!r})"
        )


class GmailOAuthTransport(Protocol):
    async def exchange(self, **values: object) -> dict[str, object]: ...

    async def account(self, credential: dict[str, object]) -> str: ...


class GoogleOAuthTransport:
    """Confine supported Google client libraries and network calls to the adapter."""

    def __init__(self, configuration: GmailOAuthConfiguration) -> None:
        self._configuration = configuration

    async def exchange(self, **values: object) -> dict[str, object]:
        def fetch() -> dict[str, object]:
            response = requests.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": self._configuration.client_id,
                    "client_secret": self._configuration.client_secret,
                    "code": str(values["authorization_code"]),
                    "code_verifier": str(values["pkce_verifier"]),
                    "grant_type": "authorization_code",
                    "redirect_uri": self._configuration.redirect_uri,
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise GmailOAuthError("Google OAuth token response is invalid")
            scope = result.pop("scope", "")
            result["scopes"] = str(scope).split()
            result["client_id"] = self._configuration.client_id
            result["client_secret"] = self._configuration.client_secret
            result["token_uri"] = GOOGLE_TOKEN_ENDPOINT
            if "expires_in" in result:
                result["expiry"] = datetime.fromtimestamp(
                    datetime.now(UTC).timestamp() + int(result.pop("expires_in")),
                    tz=UTC,
                ).isoformat()
            return result

        return await asyncio.to_thread(fetch)

    async def account(self, credential: dict[str, object]) -> str:
        credentials = Credentials.from_authorized_user_info(credential)
        resource = await asyncio.to_thread(
            build,
            "gmail",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )
        profile = await asyncio.to_thread(
            lambda: resource.users().getProfile(userId="me").execute()
        )
        return str(profile["emailAddress"])


class GmailOAuthProtocol:
    """Google adapter implementing the canonical OAuth protocol dispatcher port."""

    def __init__(
        self,
        configuration: GmailOAuthConfiguration,
        *,
        transport: GmailOAuthTransport | None = None,
    ) -> None:
        self._configuration = configuration
        self._transport = transport or GoogleOAuthTransport(configuration)

    def authorization_url(
        self,
        *,
        state: str,
        pkce_verifier: bytes,
        scopes: tuple[str, ...],
    ) -> str:
        if not state or not pkce_verifier:
            raise GmailOAuthError("OAuth state and PKCE verifier are required")
        requested = tuple(sorted(set(scopes)))
        if not requested or not set(requested).issubset(GMAIL_ALLOWED_SCOPES):
            raise GmailOAuthError("Gmail OAuth scope policy denied the request")
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(pkce_verifier).digest()
        ).decode().rstrip("=")
        return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode({
            'client_id': self._configuration.client_id,
            'redirect_uri': self._configuration.redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(requested),
            'state': state,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
            'access_type': 'offline',
            'include_granted_scopes': 'true',
            'prompt': 'consent',
        })}"

    async def exchange(
        self,
        *,
        provider_key: str,
        authorization_code: str,
        pkce_verifier: bytes,
        redirect_uri: str,
    ) -> OAuthCredentialGrant:
        if provider_key != "google_workspace":
            raise GmailOAuthError("OAuth provider is unsupported")
        if redirect_uri != self._configuration.redirect_uri:
            raise GmailOAuthError("OAuth redirect binding is invalid")
        if not authorization_code or not pkce_verifier:
            raise GmailOAuthError("OAuth exchange coordinates are invalid")
        try:
            raw = await self._transport.exchange(
                authorization_code=authorization_code,
                pkce_verifier=pkce_verifier.decode(),
                redirect_uri=redirect_uri,
            )
            if not raw.get("refresh_token"):
                raise GmailOAuthError("Google did not return refresh authorization")
            account = await self._transport.account(raw)
            raw["account_id"] = account.strip().lower()
            scopes_value = raw.get("scopes", ())
            scopes = (
                tuple(scope for scope in scopes_value if scope in GMAIL_ALLOWED_SCOPES)
                if isinstance(scopes_value, list)
                else ()
            )
            expiry = raw.get("expiry")
            expires_at = (
                datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                if expiry
                else None
            )
            grant = GmailOAuthGrant(
                payload=json.dumps(raw, sort_keys=True, separators=(",", ":")).encode(),
                scopes=scopes,
                provider_account_id=account,
                expires_at=expires_at,
            )
        except GmailOAuthError:
            raise
        except Exception as error:
            raise GmailOAuthError("Google OAuth exchange failed") from error
        return OAuthCredentialGrant(
            payload=grant.payload,
            scopes=grant.scopes,
            provider_account_id=grant.provider_account_id,
            credential_kind=grant.credential_kind,
            expires_at=grant.expires_at,
        )


async def refresh_google_credential(payload: bytes) -> GmailOAuthGrant:
    """Refresh one decrypted Google grant; callers persist a new encrypted generation."""
    try:
        values = json.loads(payload)
        credentials = Credentials.from_authorized_user_info(values)
        if not credentials.refresh_token:
            raise GmailOAuthError("Google refresh authorization is unavailable")
        await asyncio.to_thread(credentials.refresh, Request())
        refreshed = json.loads(credentials.to_json())
        refreshed["account_id"] = str(values.get("account_id", ""))
        return GmailOAuthGrant(
            payload=json.dumps(refreshed, sort_keys=True, separators=(",", ":")).encode(),
            scopes=tuple(credentials.scopes or ()),
            provider_account_id=str(values.get("account_id", "")),
            expires_at=credentials.expiry.astimezone(UTC) if credentials.expiry else None,
        )
    except GmailOAuthError:
        raise
    except Exception as error:
        raise GmailOAuthError("Google credential refresh failed") from error
