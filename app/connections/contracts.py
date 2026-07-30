"""Canonical contracts for the H2-01 connection lifecycle."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum

CONNECTION_KIND_VERSION = 1
CONNECTION_CAPABILITY_VERSION = 1
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{1,95}$")


class ConnectionLifecycleError(ValueError):
    """Raised when a connection lifecycle operation is invalid."""


class ConnectionRegistryError(ValueError):
    """Raised when registry metadata is unknown or inactive."""


class ConnectionAuthorizationError(PermissionError):
    """Raised before connection persistence when H1 authorization denies access."""


class ConnectionConcurrencyError(RuntimeError):
    """Raised when optimistic connection state is stale."""


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DEGRADED = "degraded"
    REAUTHORIZATION_REQUIRED = "reauthorization_required"
    REVOKED = "revoked"
    CLOSED = "closed"


_TRANSITIONS: dict[ConnectionStatus, frozenset[ConnectionStatus]] = {
    ConnectionStatus.PENDING: frozenset(
        {
            ConnectionStatus.ACTIVE,
            ConnectionStatus.REAUTHORIZATION_REQUIRED,
            ConnectionStatus.REVOKED,
            ConnectionStatus.CLOSED,
        }
    ),
    ConnectionStatus.ACTIVE: frozenset(
        {
            ConnectionStatus.DEGRADED,
            ConnectionStatus.REAUTHORIZATION_REQUIRED,
            ConnectionStatus.REVOKED,
            ConnectionStatus.CLOSED,
        }
    ),
    ConnectionStatus.DEGRADED: frozenset(
        {
            ConnectionStatus.ACTIVE,
            ConnectionStatus.REAUTHORIZATION_REQUIRED,
            ConnectionStatus.REVOKED,
            ConnectionStatus.CLOSED,
        }
    ),
    ConnectionStatus.REAUTHORIZATION_REQUIRED: frozenset(
        {
            ConnectionStatus.ACTIVE,
            ConnectionStatus.REVOKED,
            ConnectionStatus.CLOSED,
        }
    ),
    ConnectionStatus.REVOKED: frozenset({ConnectionStatus.CLOSED}),
    ConnectionStatus.CLOSED: frozenset(),
}


def normalize_identifier(value: str, name: str) -> str:
    normalized = value.strip().lower()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{name} is invalid")
    return normalized


def normalize_scopes(scopes: tuple[str, ...]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for scope in scopes:
        value = scope.strip()
        if not value or len(value) > 512:
            raise ValueError("scope metadata is invalid")
        normalized.add(value)
    if len(normalized) > 128:
        raise ValueError("scope metadata exceeds the supported limit")
    return tuple(sorted(normalized))


def require_transition(
    current: ConnectionStatus,
    target: ConnectionStatus,
) -> None:
    if target not in _TRANSITIONS[current]:
        raise ConnectionLifecycleError("connection status transition is invalid")


@dataclass(frozen=True, slots=True, order=True)
class CapabilityGrant:
    capability_key: str
    version: int = CONNECTION_CAPABILITY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_key",
            normalize_identifier(self.capability_key, "capability key"),
        )
        if self.version < 1:
            raise ValueError("capability version must be positive")


@dataclass(frozen=True, slots=True)
class ConnectionCreate:
    connection_id: uuid.UUID
    provider_key: str
    connection_kind: str
    provider_account_id: str
    display_name: str
    granted_scopes: tuple[str, ...] = ()
    capability_grants: tuple[CapabilityGrant, ...] = ()
    connection_kind_version: int = CONNECTION_KIND_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_key",
            normalize_identifier(self.provider_key, "provider key"),
        )
        object.__setattr__(
            self,
            "connection_kind",
            normalize_identifier(self.connection_kind, "connection kind"),
        )
        account_id = self.provider_account_id.strip()
        display_name = self.display_name.strip()
        if not account_id or len(account_id) > 255:
            raise ValueError("provider account identifier is invalid")
        if not display_name or len(display_name) > 255:
            raise ValueError("display name is invalid")
        if self.connection_kind_version < 1:
            raise ValueError("connection kind version must be positive")
        object.__setattr__(self, "provider_account_id", account_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "granted_scopes", normalize_scopes(self.granted_scopes))
        object.__setattr__(
            self,
            "capability_grants",
            tuple(sorted(set(self.capability_grants))),
        )
