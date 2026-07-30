"""Workspace-scoped provider-neutral connection foundation."""

from app.connections.contracts import (
    CONNECTION_CAPABILITY_VERSION,
    CONNECTION_KIND_VERSION,
    CapabilityGrant,
    ConnectionAuthorizationError,
    ConnectionConcurrencyError,
    ConnectionCreate,
    ConnectionLifecycleError,
    ConnectionRegistryError,
    ConnectionStatus,
)
from app.connections.models import (
    Connection,
    ConnectionCapabilityGrant,
    ConnectionKind,
    ConnectionKindCapability,
    ProviderCapability,
    ProviderRegistryEntry,
)
from app.connections.repository import ConnectionRepository
from app.connections.service import ConnectionService

__all__ = [
    "CONNECTION_CAPABILITY_VERSION",
    "CONNECTION_KIND_VERSION",
    "CapabilityGrant",
    "Connection",
    "ConnectionAuthorizationError",
    "ConnectionCapabilityGrant",
    "ConnectionConcurrencyError",
    "ConnectionCreate",
    "ConnectionKind",
    "ConnectionKindCapability",
    "ConnectionLifecycleError",
    "ConnectionRegistryError",
    "ConnectionRepository",
    "ConnectionService",
    "ConnectionStatus",
    "ProviderCapability",
    "ProviderRegistryEntry",
]
