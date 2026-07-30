"""Atomic command, audit, inbox, quarantine, and replay services."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ExecutionContext
from app.messaging.contracts import (
    AuditInput,
    CommandEnvelope,
    CommandResult,
    ConcurrencyConflict,
    ConsumerResult,
    EventEnvelope,
    IdempotencyConflict,
    MessagingError,
    ReplayDenied,
)
from app.messaging.models import EventQuarantine
from app.messaging.repository import MessagingRepository
from app.tenancy.models import AuditEvent, OutboxEvent

FORBIDDEN_PAYLOAD_TERMS = (
    "password",
    "secret",
    "token",
    "credential",
    "ciphertext",
    "private_key",
)


def _safe_payload(payload: dict[str, object]) -> dict[str, object]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    lowered = encoded.lower()
    if any(term in lowered for term in FORBIDDEN_PAYLOAD_TERMS):
        raise MessagingError("sensitive messaging payload is prohibited")
    return payload


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class AuditWriterService:
    """Append minimal audit records; PostgreSQL owns chain sequencing."""

    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        self._session = session
        self._context = context

    async def write(self, audit: AuditInput) -> AuditEvent:
        details = _safe_payload(audit.details or {})
        event = AuditEvent(
            workspace_id=self._context.tenant.workspace_id,
            id=uuid.uuid4(),
            actor_type="user",
            actor_id=self._context.actor.actor_id,
            action=audit.action,
            target_type=audit.target_type,
            target_id=audit.target_id,
            outcome=audit.outcome,
            details=details,
            decision_id=(
                audit.decision_id
                or self._context.actor.authorization_decision_id
            ),
            correlation_id=self._context.request.correlation_id,
            classification=audit.classification,
        )
        self._session.add(event)
        await self._session.flush()
        await self._session.refresh(
            event,
            attribute_names=[
                "chain_sequence",
                "previous_digest",
                "safe_digest",
                "partition_key",
            ],
        )
        return event

    async def verify_chain(self) -> bool:
        return bool(
            await self._session.scalar(
                text("SELECT verify_audit_chain(:workspace_id)"),
                {"workspace_id": self._context.tenant.workspace_id},
            )
        )


class CommandService:
    """Atomic optimistic command evidence with caller-owned idempotency."""

    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        self._session = session
        self._context = context
        self._repository = MessagingRepository(session, context)
        self._audit = AuditWriterService(session, context)

    async def record(
        self,
        command: CommandEnvelope,
        *,
        event_type: str,
        event_payload: dict[str, object],
        schema_major: int = 1,
        schema_minor: int = 0,
        now: datetime | None = None,
    ) -> CommandResult:
        if command.workspace_id != self._context.tenant.workspace_id:
            raise MessagingError("command workspace context does not match")
        if command.actor_id != self._context.actor.actor_id:
            raise MessagingError("command actor context does not match")
        safe_event_payload = _safe_payload(event_payload)
        idempotency, created = await self._repository.claim_command(command)
        if not created:
            if idempotency.request_digest != command.request_digest():
                raise IdempotencyConflict(
                    "idempotency key was reused with changed input"
                )
            if (
                idempotency.status == "completed"
                and idempotency.outcome_event_id is not None
                and idempotency.aggregate_version is not None
            ):
                return CommandResult(
                    event_id=idempotency.outcome_event_id,
                    aggregate_version=idempotency.aggregate_version,
                    replayed=True,
                )
            raise IdempotencyConflict("matching command is still in progress")

        aggregate = await self._repository.lock_aggregate(
            workspace_id=command.workspace_id,
            aggregate_type=command.aggregate_type,
            aggregate_id=command.aggregate_id,
        )
        if aggregate.version != command.expected_version:
            raise ConcurrencyConflict("aggregate version precondition failed")
        aggregate.version += 1
        event_id = uuid.uuid4()
        occurred_at = now or datetime.now(UTC)
        audit = await self._audit.write(
            AuditInput(
                action=command.command_type,
                target_type=command.aggregate_type,
                target_id=command.aggregate_id,
                outcome="success",
                details={
                    "aggregate_version": aggregate.version,
                    "event_id": str(event_id),
                },
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=command.workspace_id,
                id=event_id,
                event_type=event_type,
                schema_version=schema_major,
                schema_major=schema_major,
                schema_minor=schema_minor,
                aggregate_type=command.aggregate_type,
                aggregate_id=command.aggregate_id,
                aggregate_sequence=aggregate.version,
                actor_id=command.actor_id,
                delegation_id=command.delegation_id,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
                classification="internal",
                idempotency_key=command.idempotency_key,
                payload=safe_event_payload,
                payload_digest=_digest(safe_event_payload),
                recorded_at=occurred_at,
                partition_key=occurred_at.strftime("%Y-%m"),
            )
        )
        idempotency.status = "completed"
        idempotency.outcome_event_id = event_id
        idempotency.aggregate_version = aggregate.version
        idempotency.completed_at = occurred_at
        await self._session.flush()
        assert audit.safe_digest is not None
        return CommandResult(
            event_id=event_id,
            aggregate_version=aggregate.version,
            replayed=False,
        )


class EventConsumerService:
    """Deduplicate, order, quarantine, and explicitly replay events."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        supported_schemas: dict[str, int],
    ) -> None:
        self._session = session
        self._context = context
        self._repository = MessagingRepository(session, context)
        self._audit = AuditWriterService(session, context)
        self._supported_schemas = supported_schemas

    async def consume(
        self,
        event: EventEnvelope,
        *,
        consumer_id: str,
        apply: Callable[[], Awaitable[None]] | None = None,
    ) -> ConsumerResult:
        if event.workspace_id != self._context.tenant.workspace_id:
            raise MessagingError("event workspace context does not match")
        payload = _safe_payload(event.payload)
        payload_digest = _digest(payload)
        recognized = self._supported_schemas.get(event.event_type)
        if recognized != event.schema_major:
            return await self._quarantine(
                event,
                consumer_id=consumer_id,
                reason="unknown_schema",
                expected_sequence=None,
                payload_digest=payload_digest,
            )

        sequence = await self._repository.lock_consumer_sequence(
            event,
            consumer_id=consumer_id,
        )
        expected = sequence.last_sequence + 1
        if event.aggregate_sequence != expected:
            reason = (
                "sequence_gap"
                if event.aggregate_sequence > expected
                else "stale_sequence"
            )
            return await self._quarantine(
                event,
                consumer_id=consumer_id,
                reason=reason,
                expected_sequence=expected,
                payload_digest=payload_digest,
            )

        claimed = await self._repository.claim_inbox(
            event,
            consumer_id=consumer_id,
            status="processed",
            payload_digest=payload_digest,
        )
        if not claimed:
            return ConsumerResult.DUPLICATE
        if apply is not None:
            try:
                async with self._session.begin_nested():
                    await apply()
            except Exception:
                return await self._quarantine_claimed(
                    event,
                    consumer_id=consumer_id,
                    reason="poison_message",
                    expected_sequence=expected,
                    payload_digest=payload_digest,
                )
        sequence.last_sequence = event.aggregate_sequence
        await self._session.flush()
        return ConsumerResult.PROCESSED

    async def replay(
        self,
        *,
        quarantine_id: uuid.UUID,
        authorization_decision_id: uuid.UUID,
        dry_run: bool,
    ) -> ConsumerResult:
        if (
            authorization_decision_id
            != self._context.actor.authorization_decision_id
        ):
            raise ReplayDenied("replay authorization does not match context")
        quarantine = await self._repository.get_quarantine(
            workspace_id=self._context.tenant.workspace_id,
            quarantine_id=quarantine_id,
            for_update=True,
        )
        if quarantine is None or quarantine.status != "quarantined":
            raise ReplayDenied("quarantined event is unavailable")
        if dry_run:
            return ConsumerResult.DRY_RUN
        event = self._deserialize_event(quarantine.event_payload)
        recognized = self._supported_schemas.get(event.event_type)
        if recognized != event.schema_major:
            raise ReplayDenied("event schema remains unsupported")
        sequence = await self._repository.lock_consumer_sequence(
            event,
            consumer_id=quarantine.consumer_id,
        )
        if event.aggregate_sequence != sequence.last_sequence + 1:
            raise ReplayDenied("event sequence gap remains unresolved")
        inbox = await self._repository.get_inbox(
            workspace_id=event.workspace_id,
            consumer_id=quarantine.consumer_id,
            event_id=event.event_id,
            for_update=True,
        )
        assert inbox is not None
        inbox.status = "processed"
        sequence.last_sequence = event.aggregate_sequence
        quarantine.status = "replayed"
        quarantine.replayed_at = datetime.now(UTC)
        quarantine.replayed_by = self._context.actor.actor_id
        quarantine.replay_decision_id = authorization_decision_id
        await self._audit.write(
            AuditInput(
                action="event.replayed",
                target_type="event_quarantine",
                target_id=quarantine.id,
                outcome="success",
                decision_id=authorization_decision_id,
                details={"event_id": str(event.event_id)},
            )
        )
        await self._session.flush()
        return ConsumerResult.PROCESSED

    async def _quarantine(
        self,
        event: EventEnvelope,
        *,
        consumer_id: str,
        reason: str,
        expected_sequence: int | None,
        payload_digest: str,
    ) -> ConsumerResult:
        claimed = await self._repository.claim_inbox(
            event,
            consumer_id=consumer_id,
            status="quarantined",
            payload_digest=payload_digest,
        )
        if not claimed:
            return ConsumerResult.DUPLICATE
        return await self._add_quarantine(
            event,
            consumer_id=consumer_id,
            reason=reason,
            expected_sequence=expected_sequence,
            payload_digest=payload_digest,
        )

    async def _quarantine_claimed(
        self,
        event: EventEnvelope,
        *,
        consumer_id: str,
        reason: str,
        expected_sequence: int,
        payload_digest: str,
    ) -> ConsumerResult:
        inbox = await self._repository.get_inbox(
            workspace_id=event.workspace_id,
            consumer_id=consumer_id,
            event_id=event.event_id,
            for_update=True,
        )
        assert inbox is not None
        inbox.status = "quarantined"
        return await self._add_quarantine(
            event,
            consumer_id=consumer_id,
            reason=reason,
            expected_sequence=expected_sequence,
            payload_digest=payload_digest,
        )

    async def _add_quarantine(
        self,
        event: EventEnvelope,
        *,
        consumer_id: str,
        reason: str,
        expected_sequence: int | None,
        payload_digest: str,
    ) -> ConsumerResult:
        await self._repository.add_quarantine(
            EventQuarantine(
                workspace_id=event.workspace_id,
                consumer_id=consumer_id,
                event_id=event.event_id,
                reason=reason,
                expected_sequence=expected_sequence,
                observed_sequence=event.aggregate_sequence,
                event_payload=self._serialize_event(event),
                payload_digest=payload_digest,
            )
        )
        return (
            ConsumerResult.GAP
            if reason == "sequence_gap"
            else ConsumerResult.QUARANTINED
        )

    @staticmethod
    def _serialize_event(event: EventEnvelope) -> dict[str, object]:
        return {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "schema_major": event.schema_major,
            "schema_minor": event.schema_minor,
            "workspace_id": str(event.workspace_id),
            "aggregate_type": event.aggregate_type,
            "aggregate_id": str(event.aggregate_id),
            "aggregate_sequence": event.aggregate_sequence,
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "correlation_id": event.correlation_id,
            "occurred_at": event.occurred_at.isoformat(),
            "classification": event.classification,
            "payload": event.payload,
            "causation_id": str(event.causation_id) if event.causation_id else None,
            "delegation_id": (
                str(event.delegation_id) if event.delegation_id else None
            ),
        }

    @staticmethod
    def _deserialize_event(value: dict[str, object]) -> EventEnvelope:
        return EventEnvelope(
            event_id=uuid.UUID(str(value["event_id"])),
            event_type=str(value["event_type"]),
            schema_major=int(str(value["schema_major"])),
            schema_minor=int(str(value["schema_minor"])),
            workspace_id=uuid.UUID(str(value["workspace_id"])),
            aggregate_type=str(value["aggregate_type"]),
            aggregate_id=uuid.UUID(str(value["aggregate_id"])),
            aggregate_sequence=int(str(value["aggregate_sequence"])),
            actor_id=(
                uuid.UUID(str(value["actor_id"]))
                if value.get("actor_id")
                else None
            ),
            correlation_id=str(value["correlation_id"]),
            occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
            classification=str(value["classification"]),
            payload=dict(value["payload"]),  # type: ignore[arg-type]
            causation_id=(
                uuid.UUID(str(value["causation_id"]))
                if value.get("causation_id")
                else None
            ),
            delegation_id=(
                uuid.UUID(str(value["delegation_id"]))
                if value.get("delegation_id")
                else None
            ),
        )
