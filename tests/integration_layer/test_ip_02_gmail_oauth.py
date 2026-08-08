"""IP-02 Gmail OAuth provider-boundary contract tests."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations.gmail.credential_store import GmailRefreshingCredentialLoader
from app.integrations.gmail.oauth import (
    GMAIL_COMPOSE_SCOPE,
    GMAIL_READ_SCOPE,
    GMAIL_SEND_SCOPE,
    GmailOAuthConfiguration,
    GmailOAuthError,
    GmailOAuthGrant,
    GmailOAuthProtocol,
    GmailOAuthScopeProfile,
)
from app.integrations.gmail.workspace_oauth import (
    GmailAuthorizationStart,
    GmailWorkspaceOAuthService,
)
from app.oauth_transactions.contracts import OAuthCallback, OAuthPurpose
from app.oauth_transactions.service import OAuthStartResult
from app.provider_capabilities.common import ProviderCapabilityError


def test_scope_profile_is_minimal_and_operation_driven() -> None:
    read = GmailOAuthScopeProfile.for_operations(("profile", "list", "search"))
    compose = GmailOAuthScopeProfile.for_operations(("draft",))
    send = GmailOAuthScopeProfile.for_operations(("send",))

    assert read.scopes == (GMAIL_READ_SCOPE,)
    assert compose.scopes == (GMAIL_COMPOSE_SCOPE,)
    assert send.scopes == (GMAIL_SEND_SCOPE,)
    with pytest.raises(ValueError, match="unsupported Gmail operation"):
        GmailOAuthScopeProfile.for_operations(("calendar",))


def test_authorization_url_uses_state_pkce_offline_and_incremental_consent() -> None:
    protocol = GmailOAuthProtocol(
        GmailOAuthConfiguration(
            client_id="client-id.apps.googleusercontent.com",
            client_secret="client-secret",
            redirect_uri="https://atlas.example/oauth/gmail/callback",
        )
    )
    verifier = "v" * 64
    url = protocol.authorization_url(
        state="opaque-state",
        pkce_verifier=verifier.encode(),
        scopes=(GMAIL_READ_SCOPE,),
    )

    assert "client_secret" not in url
    assert "state=opaque-state" in url
    assert "code_challenge_method=S256" in url
    assert "access_type=offline" in url
    assert "include_granted_scopes=true" in url
    assert "prompt=consent" in url
    assert "calendar" not in url and "drive" not in url


def test_configuration_and_grant_representations_redact_secrets() -> None:
    configuration = GmailOAuthConfiguration(
        client_id="client-id",
        client_secret="raw-client-secret",
        redirect_uri="https://atlas.example/oauth/gmail/callback",
    )
    grant = GmailOAuthGrant(
        payload=b'{"refresh_token":"raw-refresh-token"}',
        scopes=(GMAIL_READ_SCOPE,),
        provider_account_id="account@example.com",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    assert "raw-client-secret" not in repr(configuration)
    assert "raw-refresh-token" not in repr(grant)


@pytest.mark.asyncio
async def test_exchange_validates_account_and_serializes_refreshable_credentials() -> None:
    class Exchange:
        async def exchange(self, **_: object) -> dict[str, object]:
            return {
                "token": "access-secret",
                "refresh_token": "refresh-secret",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "scopes": [
                    GMAIL_READ_SCOPE,
                    "https://www.googleapis.com/auth/calendar",
                ],
                "expiry": "2030-01-01T00:00:00Z",
            }

        async def account(self, _: dict[str, object]) -> str:
            return " Account@Example.com "

    protocol = GmailOAuthProtocol(
        GmailOAuthConfiguration(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://atlas.example/oauth/gmail/callback",
        ),
        transport=Exchange(),
    )
    grant = await protocol.exchange(
        provider_key="google_workspace",
        authorization_code="one-time-code",
        pkce_verifier=b"v" * 64,
        redirect_uri="https://atlas.example/oauth/gmail/callback",
    )

    assert grant.provider_account_id == "account@example.com"
    assert grant.credential_kind == "oauth_refresh_token"
    assert grant.scopes == (GMAIL_READ_SCOPE,)
    assert json.loads(grant.payload)["refresh_token"] == "refresh-secret"


@pytest.mark.asyncio
async def test_exchange_rejects_provider_redirect_and_missing_refresh_token() -> None:
    class Exchange:
        async def exchange(self, **_: object) -> dict[str, object]:
            return {"token": "access", "scopes": [GMAIL_READ_SCOPE]}

        async def account(self, _: dict[str, object]) -> str:
            return "account@example.com"

    protocol = GmailOAuthProtocol(
        GmailOAuthConfiguration(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://atlas.example/oauth/gmail/callback",
        ),
        transport=Exchange(),
    )
    with pytest.raises(GmailOAuthError, match="provider is unsupported"):
        await protocol.exchange(
            provider_key="microsoft",
            authorization_code="code",
            pkce_verifier=b"v" * 64,
            redirect_uri="https://atlas.example/oauth/gmail/callback",
        )
    with pytest.raises(GmailOAuthError, match="refresh authorization"):
        await protocol.exchange(
            provider_key="google_workspace",
            authorization_code="code",
            pkce_verifier=b"v" * 64,
            redirect_uri="https://atlas.example/oauth/gmail/callback",
        )


def test_grant_rejects_non_gmail_scopes_and_blank_account() -> None:
    with pytest.raises(ValueError, match="scope"):
        GmailOAuthGrant(
            payload=b"{}",
            scopes=("https://www.googleapis.com/auth/calendar",),
            provider_account_id="account@example.com",
        )
    with pytest.raises(ValueError, match="account"):
        GmailOAuthGrant(
            payload=b"{}",
            scopes=(GMAIL_READ_SCOPE,),
            provider_account_id=" ",
        )


@pytest.mark.asyncio
async def test_workspace_service_starts_canonical_transaction_before_url() -> None:
    workspace_id = uuid.uuid4()
    connection_id = uuid.uuid4()

    class TransactionService:
        command = None
        verifier = b""

        async def start(self, command, **values):
            self.command = command
            self.verifier = values["pkce_verifier"]
            transaction = type("Transaction", (), {"id": command.transaction_id})()
            return OAuthStartResult(transaction=transaction, state="canonical-state")

        async def complete(self, callback):
            assert callback.state == "canonical-state"
            return type("Transaction", (), {"connection_id": connection_id})()

    transactions = TransactionService()
    protocol = GmailOAuthProtocol(
        GmailOAuthConfiguration(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://atlas.example/oauth/gmail/callback",
        )
    )
    service = GmailWorkspaceOAuthService(
        transactions=transactions,
        protocol=protocol,
        redirect_uri="https://atlas.example/oauth/gmail/callback",
        issuer="https://accounts.google.com",
    )
    result = await service.start(
        GmailAuthorizationStart(
            connection_id=connection_id,
            operations=("profile", "search"),
            idempotency_key=f"gmail:{workspace_id}",
        ),
        key_reference=type("Key", (), {})(),
    )

    assert result.transaction_id == transactions.command.transaction_id
    assert transactions.command.connection_id == connection_id
    assert transactions.command.provider_key == "google_workspace"
    assert transactions.command.purpose is OAuthPurpose.CONNECT
    assert transactions.command.requested_capabilities == ("email",)
    assert transactions.command.required_scopes == (GMAIL_READ_SCOPE,)
    assert len(transactions.verifier) >= 43
    assert "state=canonical-state" in result.authorization_url
    assert await service.complete(
        OAuthCallback(
            state="canonical-state",
            code="code",
            returned_scopes=(GMAIL_READ_SCOPE,),
            issuer="https://accounts.google.com",
            redirect_uri="https://atlas.example/oauth/gmail/callback",
            received_at=datetime.now(UTC),
        )
    ) == connection_id


@pytest.mark.asyncio
async def test_expired_grant_refreshes_and_persists_new_generation() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    original = json.dumps(
        {
            "refresh_token": "old-refresh",
            "expiry": "2026-08-08T11:00:00Z",
            "account_id": "account@example.com",
        }
    ).encode()

    class Base:
        async def load(self) -> bytes:
            return original

    class Sink:
        grant = None

        async def store(self, **values):
            self.grant = values["grant"]
            return uuid.uuid4()

    sink = Sink()

    async def refresh(_: bytes) -> GmailOAuthGrant:
        return GmailOAuthGrant(
            payload=b'{"refresh_token":"new-refresh","expiry":"2030-01-01T00:00:00Z"}',
            scopes=(GMAIL_READ_SCOPE,),
            provider_account_id="account@example.com",
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )

    payload = await GmailRefreshingCredentialLoader(
        Base(),
        sink,
        connection_id=uuid.uuid4(),
        refresher=refresh,
        now=lambda: now,
    ).load()

    assert b"new-refresh" in payload
    assert sink.grant.provider_account_id == "account@example.com"


@pytest.mark.asyncio
async def test_failed_refresh_is_redacted_and_fails_closed() -> None:
    class Base:
        async def load(self) -> bytes:
            return b'{"refresh_token":"sensitive","expiry":"2020-01-01T00:00:00Z"}'

    class Sink:
        async def store(self, **_: object) -> uuid.UUID:
            raise AssertionError("failed refresh must not persist")

    async def refresh(_: bytes) -> GmailOAuthGrant:
        raise RuntimeError("provider leaked sensitive")

    loader = GmailRefreshingCredentialLoader(
        Base(),
        Sink(),
        connection_id=uuid.uuid4(),
        refresher=refresh,
    )
    with pytest.raises(ProviderCapabilityError) as caught:
        await loader.load()
    assert "sensitive" not in str(caught.value)
