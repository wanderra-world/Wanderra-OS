"""ADR-035 Google Identity operator-authentication contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from app.integrations.google_identity.oidc import (
    GoogleIdentityClaims,
    GoogleOIDCConfiguration,
    GoogleOIDCError,
    GoogleOIDCProtocol,
    OIDCTransactionCodec,
)


class FakeTransport:
    def __init__(self, claims: GoogleIdentityClaims) -> None:
        self.claims = claims
        self.exchanges = 0

    async def exchange_and_verify(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> GoogleIdentityClaims:
        assert code == "one-time-code"
        assert len(code_verifier) >= 43
        self.exchanges += 1
        if self.claims.nonce != expected_nonce:
            raise GoogleOIDCError("Google identity nonce is invalid")
        return self.claims


def _configuration() -> GoogleOIDCConfiguration:
    return GoogleOIDCConfiguration(
        client_id="operator.apps.googleusercontent.com",
        client_secret="never-render-this-secret",
        redirect_uri="https://atlas.example/api/v1/operator/auth/google/callback",
    )


def test_oidc_start_uses_identity_only_scopes_pkce_state_and_nonce() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    codec = OIDCTransactionCodec(_configuration().client_secret)
    protocol = GoogleOIDCProtocol(_configuration(), codec=codec)
    workspace_id = uuid.uuid4()

    started = protocol.start(workspace_id=workspace_id, now=now)
    query = parse_qs(urlparse(started.authorization_url).query)
    transaction = codec.decode(started.transaction_cookie, now=now)

    assert query["scope"] == ["openid email profile"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [transaction.state]
    assert query["nonce"] == [transaction.nonce]
    assert query["code_challenge"][0]
    assert transaction.workspace_id == workspace_id
    assert "never-render-this-secret" not in repr(_configuration())


def test_oidc_transaction_rejects_tampering_expiry_and_state_mismatch() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    codec = OIDCTransactionCodec(_configuration().client_secret)
    protocol = GoogleOIDCProtocol(_configuration(), codec=codec)
    started = protocol.start(workspace_id=uuid.uuid4(), now=now)

    with pytest.raises(GoogleOIDCError):
        codec.decode(started.transaction_cookie + "tampered", now=now)
    with pytest.raises(GoogleOIDCError):
        codec.decode(started.transaction_cookie, now=now + timedelta(minutes=11))
    with pytest.raises(GoogleOIDCError):
        protocol.validate_callback(
            state="wrong-state",
            transaction_cookie=started.transaction_cookie,
            now=now,
        )


@pytest.mark.asyncio
async def test_oidc_completion_requires_verified_google_claims_and_nonce() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    claims = GoogleIdentityClaims(
        issuer="https://accounts.google.com",
        subject="google-subject-123",
        audience="operator.apps.googleusercontent.com",
        nonce="placeholder",
        expires_at=now + timedelta(minutes=5),
        issued_at=now,
        email="operator@example.com",
        email_verified=True,
    )
    codec = OIDCTransactionCodec(_configuration().client_secret)
    protocol = GoogleOIDCProtocol(_configuration(), codec=codec)
    started = protocol.start(workspace_id=uuid.uuid4(), now=now)
    transaction = codec.decode(started.transaction_cookie, now=now)
    transport = FakeTransport(
        GoogleIdentityClaims(
            issuer=claims.issuer,
            subject=claims.subject,
            audience=claims.audience,
            nonce=transaction.nonce,
            expires_at=claims.expires_at,
            issued_at=claims.issued_at,
            email=claims.email,
            email_verified=claims.email_verified,
        )
    )
    protocol = GoogleOIDCProtocol(_configuration(), codec=codec, transport=transport)

    completed = await protocol.complete(
        code="one-time-code",
        state=transaction.state,
        transaction_cookie=started.transaction_cookie,
        now=now,
    )

    assert completed.claims.subject == "google-subject-123"
    assert completed.workspace_id == transaction.workspace_id
    assert transport.exchanges == 1


def test_google_claims_reject_wrong_issuer_audience_expiry_and_unverified_email() -> None:
    now = datetime(2026, 8, 9, tzinfo=UTC)
    valid = {
        "issuer": "https://accounts.google.com",
        "subject": "subject",
        "audience": "operator.apps.googleusercontent.com",
        "nonce": "nonce",
        "expires_at": now + timedelta(minutes=1),
        "issued_at": now,
        "email": "operator@example.com",
        "email_verified": True,
    }
    for override in (
        {"issuer": "https://attacker.example"},
        {"audience": "wrong-client"},
        {"expires_at": now - timedelta(seconds=1)},
        {"email_verified": False},
    ):
        with pytest.raises(GoogleOIDCError):
            GoogleIdentityClaims(**(valid | override)).validated(
                client_id="operator.apps.googleusercontent.com",
                now=now,
            )
