"""Disposable H0 prototype for events, idempotency, concurrency, and replay."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class EventContractError(ValueError):
    """Base error for rejected commands, events, and replays."""


class ConcurrencyConflict(EventContractError):
    """Raised when a command uses a stale aggregate version."""


class IdempotencyConflict(EventContractError):
    """Raised when an idempotency key is reused with changed input."""


class ConsumerResult(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    GAP = "gap"
    QUARANTINED = "quarantined"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class Aggregate:
    id: UUID
    workspace_id: UUID
    aggregate_type: str
    version: int
    value: int


@dataclass(frozen=True, slots=True)
class Command:
    workspace_id: UUID
    actor_id: UUID
    aggregate_id: UUID
    command_type: str
    expected_version: int
    payload: dict[str, Any]
    idempotency_key: str
    correlation_id: UUID
    causation_id: UUID | None = None
    delegation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Event:
    event_id: UUID
    event_type: str
    schema_version: str
    workspace_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    aggregate_sequence: int
    actor_id: UUID
    delegation_id: UUID | None
    correlation_id: UUID
    causation_id: UUID | None
    occurred_at: datetime
    recorded_at: datetime
    classification: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AuditRecord:
    workspace_id: UUID
    actor_id: UUID
    command_type: str
    aggregate_id: UUID
    resulting_version: int


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    aggregate: Aggregate
    event: Event


class EventStore:
    """Transactional state, audit, outbox, and idempotency evidence store."""

    def __init__(self) -> None:
        self.aggregates: dict[UUID, Aggregate] = {}
        self.audit: list[AuditRecord] = []
        self.outbox: list[Event] = []
        self.idempotency: dict[
            tuple[UUID, UUID, str, str],
            tuple[str, CommandOutcome],
        ] = {}
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            snapshot = deepcopy(
                (
                    self.aggregates,
                    self.audit,
                    self.outbox,
                    self.idempotency,
                )
            )
            try:
                yield
            except Exception:
                (
                    self.aggregates,
                    self.audit,
                    self.outbox,
                    self.idempotency,
                ) = snapshot
                raise


class CommandHandler:
    """Optimistic command boundary with atomic audit/outbox publication."""

    def __init__(self, store: EventStore) -> None:
        self._store = store

    def execute(
        self,
        command: Command,
        *,
        now: datetime,
        fail_before_commit: bool = False,
    ) -> CommandOutcome:
        if not command.idempotency_key.strip():
            raise EventContractError("command requires an idempotency key")
        idempotency_scope = (
            command.workspace_id,
            command.actor_id,
            command.command_type,
            command.idempotency_key,
        )
        request_hash = self._request_hash(command)
        with self._store.transaction():
            prior = self._store.idempotency.get(idempotency_scope)
            if prior is not None:
                if prior[0] != request_hash:
                    raise IdempotencyConflict(
                        "idempotency key was reused with changed input"
                    )
                return prior[1]

            aggregate = self._store.aggregates[command.aggregate_id]
            if aggregate.workspace_id != command.workspace_id:
                raise EventContractError("command workspace does not match aggregate")
            if aggregate.version != command.expected_version:
                raise ConcurrencyConflict("aggregate version precondition failed")
            amount = command.payload.get("amount")
            if not isinstance(amount, int):
                raise EventContractError("increment command requires integer amount")
            updated = replace(
                aggregate,
                version=aggregate.version + 1,
                value=aggregate.value + amount,
            )
            event = Event(
                event_id=uuid4(),
                event_type="counter.incremented",
                schema_version="1.0",
                workspace_id=command.workspace_id,
                aggregate_type=aggregate.aggregate_type,
                aggregate_id=aggregate.id,
                aggregate_sequence=updated.version,
                actor_id=command.actor_id,
                delegation_id=command.delegation_id,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
                occurred_at=now,
                recorded_at=now,
                classification="internal",
                payload={"amount": amount, "value": updated.value},
            )
            outcome = CommandOutcome(aggregate=updated, event=event)
            self._store.aggregates[aggregate.id] = updated
            self._store.audit.append(
                AuditRecord(
                    workspace_id=command.workspace_id,
                    actor_id=command.actor_id,
                    command_type=command.command_type,
                    aggregate_id=aggregate.id,
                    resulting_version=updated.version,
                )
            )
            self._store.outbox.append(event)
            self._store.idempotency[idempotency_scope] = (request_hash, outcome)
            if fail_before_commit:
                raise EventContractError("injected transaction failure")
            return outcome

    @staticmethod
    def _request_hash(command: Command) -> str:
        normalized = json.dumps(
            {
                "workspace_id": str(command.workspace_id),
                "actor_id": str(command.actor_id),
                "aggregate_id": str(command.aggregate_id),
                "command_type": command.command_type,
                "expected_version": command.expected_version,
                "payload": command.payload,
                "correlation_id": str(command.correlation_id),
                "causation_id": (
                    str(command.causation_id)
                    if command.causation_id is not None
                    else None
                ),
                "delegation_id": (
                    str(command.delegation_id)
                    if command.delegation_id is not None
                    else None
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(normalized.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EventSchema:
    event_type: str
    major_version: int
    payload_fields: frozenset[str]


class EventSchemaRegistry:
    """Additive schema registry; unknown majors are quarantined."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, int], EventSchema] = {}

    def register(self, schema: EventSchema) -> None:
        key = (schema.event_type, schema.major_version)
        current = self._schemas.get(key)
        if current is not None and not current.payload_fields <= schema.payload_fields:
            raise EventContractError(
                "schema changes within a major version must be additive"
            )
        self._schemas[key] = schema

    def recognizes(self, event: Event) -> bool:
        try:
            major_version = int(event.schema_version.split(".", maxsplit=1)[0])
        except ValueError:
            return False
        schema = self._schemas.get((event.event_type, major_version))
        return schema is not None and schema.payload_fields <= event.payload.keys()


@dataclass(frozen=True, slots=True)
class DeadLetter:
    consumer_name: str
    event_id: UUID
    reason: str
    attempts: int


class EventConsumer:
    """At-least-once consumer with inbox, gap detection, and dead letter."""

    def __init__(
        self,
        *,
        name: str,
        schemas: EventSchemaRegistry,
        handler: Callable[[Event], None],
        maximum_attempts: int = 3,
    ) -> None:
        self.name = name
        self._schemas = schemas
        self._handler = handler
        self._maximum_attempts = maximum_attempts
        self.inbox: set[UUID] = set()
        self.last_sequence: dict[tuple[UUID, UUID], int] = {}
        self.pending_gaps: list[Event] = []
        self.quarantine: list[Event] = []
        self.dead_letters: list[DeadLetter] = []
        self.attempts: dict[UUID, int] = {}

    def process(self, event: Event) -> ConsumerResult:
        if event.event_id in self.inbox:
            return ConsumerResult.DUPLICATE
        if not self._schemas.recognizes(event):
            self.quarantine.append(event)
            return ConsumerResult.QUARANTINED
        sequence_key = (event.workspace_id, event.aggregate_id)
        expected_sequence = self.last_sequence.get(sequence_key, 0) + 1
        if event.aggregate_sequence > expected_sequence:
            self.pending_gaps.append(event)
            return ConsumerResult.GAP
        if event.aggregate_sequence < expected_sequence:
            self.inbox.add(event.event_id)
            return ConsumerResult.DUPLICATE
        attempts = self.attempts.get(event.event_id, 0) + 1
        self.attempts[event.event_id] = attempts
        try:
            self._handler(event)
        except Exception as error:
            if attempts < self._maximum_attempts:
                return ConsumerResult.RETRY
            self.dead_letters.append(
                DeadLetter(
                    consumer_name=self.name,
                    event_id=event.event_id,
                    reason=type(error).__name__,
                    attempts=attempts,
                )
            )
            return ConsumerResult.DEAD_LETTER
        self.inbox.add(event.event_id)
        self.last_sequence[sequence_key] = event.aggregate_sequence
        return ConsumerResult.PROCESSED


@dataclass(frozen=True, slots=True)
class ReplayAudit:
    workspace_id: UUID
    actor_id: UUID
    event_ids: tuple[UUID, ...]
    dry_run: bool


class ReplayService:
    """Privileged, workspace-scoped, audited, dry-runnable replay boundary."""

    def __init__(self) -> None:
        self.audit: list[ReplayAudit] = []

    def replay(
        self,
        events: tuple[Event, ...],
        *,
        workspace_id: UUID,
        actor_id: UUID,
        privileged: bool,
        dry_run: bool,
        consumer: EventConsumer,
    ) -> tuple[ConsumerResult, ...]:
        if not privileged:
            raise EventContractError("event replay requires privileged authority")
        if any(event.workspace_id != workspace_id for event in events):
            raise EventContractError("event replay cannot cross workspace boundary")
        self.audit.append(
            ReplayAudit(
                workspace_id=workspace_id,
                actor_id=actor_id,
                event_ids=tuple(event.event_id for event in events),
                dry_run=dry_run,
            )
        )
        if dry_run:
            return ()
        return tuple(consumer.process(event) for event in events)


class MockExternalProvider:
    """Preconditioned, idempotent external effect with readable verification."""

    def __init__(self) -> None:
        self.version = 0
        self.value = ""
        self.effects = 0
        self._outcomes: dict[str, tuple[str, tuple[int, str]]] = {}
        self.drift_after_write = False

    def write(
        self,
        *,
        value: str,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[int, str]:
        prior = self._outcomes.get(idempotency_key)
        if prior is not None:
            if prior[0] != value:
                raise IdempotencyConflict(
                    "external idempotency key changed input"
                )
            return prior[1]
        if self.version != expected_version:
            raise ConcurrencyConflict("external provider precondition failed")
        self.version += 1
        self.value = value
        self.effects += 1
        outcome = (self.version, self.value)
        self._outcomes[idempotency_key] = (value, outcome)
        if self.drift_after_write:
            self.version += 1
            self.value = "provider-drift"
        return outcome

    def fetch(self) -> tuple[int, str]:
        return self.version, self.value


class ExternalEffectExecutor:
    """Verifies external writes and records reconciliation when they diverge."""

    def __init__(self, provider: MockExternalProvider) -> None:
        self._provider = provider
        self.reconciliation: list[UUID] = []

    def execute(
        self,
        event: Event,
        *,
        value: str,
        expected_version: int,
    ) -> None:
        written = self._provider.write(
            value=value,
            expected_version=expected_version,
            idempotency_key=str(event.event_id),
        )
        if self._provider.fetch() != written:
            self.reconciliation.append(event.event_id)
            raise EventContractError(
                "external effect verification failed; reconciliation required"
            )
