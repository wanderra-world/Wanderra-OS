"""Canonical immutable execution-context contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

EXECUTION_CONTEXT_VERSION = 1


def _require_reference(value: str, name: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} is required")
    if len(value) > 128:
        raise ValueError(f"{name} must not exceed 128 characters")


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Trace identifiers supplied at one application boundary."""

    request_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        _require_reference(self.request_id, "request_id")
        _require_reference(self.correlation_id, "correlation_id")


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Authenticated human actor and revocable authority references."""

    actor_id: uuid.UUID
    session_id: uuid.UUID
    membership_id: uuid.UUID
    authorization_decision_id: uuid.UUID
    delegation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Canonical organization, workspace, and placement coordinates."""

    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    cell_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Complete context required by an H1 tenant transaction."""

    request: RequestContext
    actor: ActorContext
    tenant: TenantContext
    version: int = EXECUTION_CONTEXT_VERSION

    def __post_init__(self) -> None:
        if self.version != EXECUTION_CONTEXT_VERSION:
            raise ValueError("unsupported execution context version")

    def audit_references(self) -> dict[str, str]:
        """Return the non-sensitive trace fields safe for audit and outbox records."""
        values = {
            "request_id": self.request.request_id,
            "correlation_id": self.request.correlation_id,
            "authorization_decision_id": str(
                self.actor.authorization_decision_id
            ),
            "execution_context_version": str(self.version),
        }
        if self.actor.delegation_id is not None:
            values["delegation_id"] = str(self.actor.delegation_id)
        return values
