"""Provider-neutral contracts for the IP-01 integration composition boundary."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.connection_credentials.contracts import normalize_scopes, normalized_identifier
from app.connections.contracts import normalize_identifier


class IntegrationResolutionError(RuntimeError):
    """Base fail-closed error for inert integration resolution."""


class IntegrationAuthorizationError(IntegrationResolutionError, PermissionError):
    """Canonical authorization denied the requested integration operation."""


class IntegrationStateError(IntegrationResolutionError):
    """The workspace-owned connection is missing, mismatched, or unavailable."""


class IntegrationCapabilityError(IntegrationResolutionError):
    """The requested capability or operation is unavailable."""


class IntegrationCredentialError(IntegrationResolutionError):
    """Usable managed credential metadata is unavailable."""


@dataclass(frozen=True, slots=True)
class IntegrationResolutionRequest:
    """One provider-neutral request to resolve an inert integration boundary."""

    connection_id: uuid.UUID
    capability_key: str
    capability_version: int
    operation: str
    permission_key: str
    credential_kind: str
    required_scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_key",
            normalize_identifier(self.capability_key, "capability key"),
        )
        object.__setattr__(
            self,
            "credential_kind",
            normalized_identifier(self.credential_kind, field="credential kind"),
        )
        operation = normalize_identifier(self.operation, "operation")
        permission = normalize_identifier(self.permission_key, "permission key")
        if self.capability_version < 1:
            raise ValueError("capability version must be positive")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "permission_key", permission)
        object.__setattr__(self, "required_scopes", normalize_scopes(self.required_scopes))


@dataclass(frozen=True, slots=True)
class IntegrationResolution:
    """Non-secret, inert metadata required to construct a later adapter call."""

    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    connection_id: uuid.UUID
    provider_key: str
    provider_account_id: str
    capability_key: str
    capability_version: int
    operation: str
    credential_id: uuid.UUID
    credential_kind: str
    credential_generation: int
    authorization_decision_id: uuid.UUID
    correlation_id: str

