"""Versioned command, event, and consumer contracts."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MessagingError(RuntimeError):
    """Base fail-closed messaging error."""


class IdempotencyConflict(MessagingError):
    """A caller-owned key was reused with different normalized input."""


class ConcurrencyConflict(MessagingError):
    """The expected aggregate version is stale."""


class ReplayDenied(MessagingError):
    """A replay lacks explicit matching authorization."""


class ConsumerResult(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    GAP = "gap"
    QUARANTINED = "quarantined"
    DRY_RUN = "dry_run"


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    workspace_id: uuid.UUID
    actor_id: uuid.UUID
    command_type: str
    idempotency_key: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    expected_version: int
    correlation_id: str
    payload: dict[str, object]
    causation_id: uuid.UUID | None = None
    delegation_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.command_type, "command type"),
            (self.idempotency_key, "idempotency key"),
            (self.aggregate_type, "aggregate type"),
            (self.correlation_id, "correlation id"),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")
        if self.expected_version < 0:
            raise ValueError("expected version cannot be negative")

    def request_digest(self) -> str:
        normalized = json.dumps(
            {
                "workspace_id": str(self.workspace_id),
                "actor_id": str(self.actor_id),
                "command_type": self.command_type,
                "aggregate_type": self.aggregate_type,
                "aggregate_id": str(self.aggregate_id),
                "expected_version": self.expected_version,
                "correlation_id": self.correlation_id,
                "causation_id": str(self.causation_id) if self.causation_id else None,
                "delegation_id": (
                    str(self.delegation_id) if self.delegation_id else None
                ),
                "payload": self.payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(normalized.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: uuid.UUID
    event_type: str
    schema_major: int
    schema_minor: int
    workspace_id: uuid.UUID
    aggregate_type: str
    aggregate_id: uuid.UUID
    aggregate_sequence: int
    actor_id: uuid.UUID | None
    correlation_id: str
    occurred_at: datetime
    classification: str
    payload: dict[str, object]
    causation_id: uuid.UUID | None = None
    delegation_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.schema_major < 1 or self.schema_minor < 0:
            raise ValueError("event schema version is invalid")
        if self.aggregate_sequence < 1:
            raise ValueError("aggregate sequence must be positive")
        for value, name in (
            (self.event_type, "event type"),
            (self.aggregate_type, "aggregate type"),
            (self.correlation_id, "correlation id"),
            (self.classification, "classification"),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")


@dataclass(frozen=True, slots=True)
class CommandResult:
    event_id: uuid.UUID
    aggregate_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class AuditInput:
    action: str
    target_type: str
    target_id: uuid.UUID
    outcome: str
    decision_id: uuid.UUID | None = None
    classification: str = "internal"
    details: dict[str, object] | None = None
