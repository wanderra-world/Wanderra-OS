"""IP-03 operator-facing Gmail lifecycle contract tests."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.routing import APIRoute

from app.api.v1.gmail import router as legacy_router
from app.api.v1.gmail_connections import GmailConnectionResponse, _configuration
from app.api.v1.gmail_connections import router as operator_router
from app.core.config import Settings
from app.integrations.gmail.operator import (
    GmailConnectionState,
    GmailConnectionStatusService,
)


def _connection(status: str = "pending") -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        status=status,
        workspace_id=uuid.uuid4(),
        provider_key="google_workspace",
        id=uuid.uuid4(),
        provider_account_id="operator@example.com",
        granted_scopes=[],
        created_at=now,
        updated_at=now,
        activated_at=None,
    )


def test_lifecycle_state_is_deterministic_and_fail_closed() -> None:
    now = datetime.now(UTC)
    connection = _connection()

    assert (
        GmailConnectionStatusService._state(connection, None, None, now)
        is GmailConnectionState.INITIATED
    )
    pending = SimpleNamespace(
        status="pending",
        failure_code=None,
        expires_at=now + timedelta(minutes=5),
    )
    assert (
        GmailConnectionStatusService._state(connection, None, pending, now)
        is GmailConnectionState.AUTHORIZATION_PENDING
    )
    pending.expires_at = now - timedelta(seconds=1)
    assert (
        GmailConnectionStatusService._state(connection, None, pending, now)
        is GmailConnectionState.EXPIRED
    )
    failed = SimpleNamespace(
        status="failed",
        failure_code="binding_mismatch",
        expires_at=now,
    )
    assert (
        GmailConnectionStatusService._state(connection, None, failed, now)
        is GmailConnectionState.MISMATCHED
    )


def test_revoked_disabled_expired_invalid_and_active_states_are_explicit() -> None:
    now = datetime.now(UTC)
    connection = _connection("active")
    active = SimpleNamespace(status="active")

    assert (
        GmailConnectionStatusService._state(connection, active, None, now)
        is GmailConnectionState.ACTIVE
    )
    connection.status = "revoked"
    assert (
        GmailConnectionStatusService._state(connection, active, None, now)
        is GmailConnectionState.REVOKED
    )
    connection.status = "active"
    disabled = SimpleNamespace(status="disabled")
    assert (
        GmailConnectionStatusService._state(connection, disabled, None, now)
        is GmailConnectionState.DISABLED
    )
    invalid = SimpleNamespace(status="reauthorization_required")
    assert (
        GmailConnectionStatusService._state(connection, invalid, None, now)
        is GmailConnectionState.INVALID
    )
    expired = SimpleNamespace(
        status="expired",
        failure_code="expired",
        expires_at=now,
    )
    assert (
        GmailConnectionStatusService._state(connection, None, expired, now)
        is GmailConnectionState.EXPIRED
    )


def test_operator_response_contract_cannot_serialize_secrets() -> None:
    fields = set(GmailConnectionResponse.model_fields)

    assert fields == {
        "connection_id",
        "workspace_id",
        "provider",
        "provider_account_id",
        "state",
        "granted_scopes",
        "created_at",
        "updated_at",
        "activated_at",
    }
    assert not fields & {
        "access_token",
        "refresh_token",
        "client_secret",
        "authorization_code",
        "oauth_state",
        "pkce_verifier",
        "ciphertext",
    }


def test_operator_oauth_reuses_the_existing_google_client_file(tmp_path) -> None:
    client_file = tmp_path / "client.json"
    client_file.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "workspace-client.apps.googleusercontent.com",
                    "client_secret": "workspace-client-secret",
                }
            }
        )
    )

    configuration = _configuration(
        Settings(
            _env_file=None,
            google_oauth_client_id=None,
            google_oauth_client_secret=None,
            google_oauth_client_secret_file=str(client_file),
        )
    )

    assert configuration.client_id == "workspace-client.apps.googleusercontent.com"
    assert "workspace-client-secret" not in repr(configuration)


def test_operator_routes_are_bounded_and_legacy_gmail_routes_remain_registered() -> None:
    operator_routes = {
        route.path: route.methods
        for route in operator_router.routes
        if isinstance(route, APIRoute)
    }
    legacy_routes = {
        route.path for route in legacy_router.routes if isinstance(route, APIRoute)
    }

    assert operator_routes["/workspaces/{workspace_id}/connections/oauth"] == {"POST"}
    assert operator_routes["/connections/oauth/callback"] == {"GET"}
    assert operator_routes["/workspaces/{workspace_id}/connections/{connection_id}"] == {
        "GET"
    }
    assert "/oauth/authorize" in legacy_routes
    assert "/oauth/callback" in legacy_routes
