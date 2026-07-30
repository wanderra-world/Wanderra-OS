"""Unit evidence for the H2-01 connection lifecycle contract."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.connections.contracts import (
    CONNECTION_CAPABILITY_VERSION,
    CONNECTION_KIND_VERSION,
    CapabilityGrant,
    ConnectionCreate,
    ConnectionLifecycleError,
    ConnectionStatus,
    normalize_scopes,
    require_transition,
)


def test_connection_create_normalizes_non_secret_metadata() -> None:
    command = ConnectionCreate(
        connection_id=uuid4(),
        provider_key=" google_workspace ",
        connection_kind=" workspace_suite ",
        provider_account_id=" account-123 ",
        display_name=" Atlas Workspace ",
        granted_scopes=("scope.b", "scope.a", "scope.a"),
        capability_grants=(
            CapabilityGrant("storage.write"),
            CapabilityGrant("email.read"),
            CapabilityGrant("email.read"),
        ),
    )

    assert command.provider_key == "google_workspace"
    assert command.connection_kind == "workspace_suite"
    assert command.provider_account_id == "account-123"
    assert command.display_name == "Atlas Workspace"
    assert command.granted_scopes == ("scope.a", "scope.b")
    assert command.capability_grants == (
        CapabilityGrant("email.read"),
        CapabilityGrant("storage.write"),
    )
    assert command.connection_kind_version == CONNECTION_KIND_VERSION
    assert all(
        grant.version == CONNECTION_CAPABILITY_VERSION
        for grant in command.capability_grants
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ConnectionStatus.PENDING, ConnectionStatus.ACTIVE),
        (ConnectionStatus.ACTIVE, ConnectionStatus.DEGRADED),
        (ConnectionStatus.DEGRADED, ConnectionStatus.ACTIVE),
        (
            ConnectionStatus.REAUTHORIZATION_REQUIRED,
            ConnectionStatus.ACTIVE,
        ),
        (ConnectionStatus.ACTIVE, ConnectionStatus.REVOKED),
        (ConnectionStatus.REVOKED, ConnectionStatus.CLOSED),
    ],
)
def test_approved_connection_lifecycle_transitions(
    current: ConnectionStatus,
    target: ConnectionStatus,
) -> None:
    require_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ConnectionStatus.PENDING, ConnectionStatus.DEGRADED),
        (ConnectionStatus.REVOKED, ConnectionStatus.ACTIVE),
        (ConnectionStatus.CLOSED, ConnectionStatus.ACTIVE),
        (ConnectionStatus.ACTIVE, ConnectionStatus.ACTIVE),
    ],
)
def test_invalid_connection_lifecycle_transitions_fail_closed(
    current: ConnectionStatus,
    target: ConnectionStatus,
) -> None:
    with pytest.raises(ConnectionLifecycleError, match="invalid"):
        require_transition(current, target)


@pytest.mark.parametrize(
    "scopes",
    [
        ("",),
        ("scope.valid", " "),
        ("a" * 513,),
    ],
)
def test_invalid_scope_metadata_is_rejected(scopes: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="scope"):
        normalize_scopes(scopes)


def test_unknown_status_is_rejected_deterministically() -> None:
    with pytest.raises(ValueError):
        ConnectionStatus("unknown")
