"""Context-bound PostgreSQL repository for H1-08 messaging state."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.messaging.contracts import CommandEnvelope, EventEnvelope
from app.messaging.models import (
    AggregateVersion,
    CommandIdempotency,
    ConsumerSequence,
    EventQuarantine,
    InboxEvent,
)


class MessagingRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def claim_command(
        self,
        command: CommandEnvelope,
    ) -> tuple[CommandIdempotency, bool]:
        self.require_workspace(command.workspace_id)
        statement = (
            insert(CommandIdempotency)
            .values(
                workspace_id=command.workspace_id,
                actor_id=command.actor_id,
                command_type=command.command_type,
                idempotency_key=command.idempotency_key,
                request_digest=command.request_digest(),
                correlation_id=command.correlation_id,
            )
            .on_conflict_do_nothing()
            .returning(CommandIdempotency.idempotency_key)
        )
        created = (await self.session.scalar(statement)) is not None
        record = await self.session.scalar(
            select(CommandIdempotency)
            .where(
                CommandIdempotency.workspace_id == command.workspace_id,
                CommandIdempotency.actor_id == command.actor_id,
                CommandIdempotency.command_type == command.command_type,
                CommandIdempotency.idempotency_key == command.idempotency_key,
            )
            .with_for_update()
        )
        assert record is not None
        return record, created

    async def lock_aggregate(
        self,
        *,
        workspace_id: uuid.UUID,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
    ) -> AggregateVersion:
        self.require_workspace(workspace_id)
        await self.session.execute(
            insert(AggregateVersion)
            .values(
                workspace_id=workspace_id,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                version=0,
            )
            .on_conflict_do_nothing()
        )
        aggregate = await self.session.scalar(
            select(AggregateVersion)
            .where(
                AggregateVersion.workspace_id == workspace_id,
                AggregateVersion.aggregate_type == aggregate_type,
                AggregateVersion.aggregate_id == aggregate_id,
            )
            .with_for_update()
        )
        assert aggregate is not None
        return aggregate

    async def claim_inbox(
        self,
        event: EventEnvelope,
        *,
        consumer_id: str,
        status: str,
        payload_digest: str,
    ) -> bool:
        self.require_workspace(event.workspace_id)
        statement = (
            insert(InboxEvent)
            .values(
                workspace_id=event.workspace_id,
                consumer_id=consumer_id,
                event_id=event.event_id,
                event_type=event.event_type,
                schema_major=event.schema_major,
                schema_minor=event.schema_minor,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                aggregate_sequence=event.aggregate_sequence,
                status=status,
                payload_digest=payload_digest,
            )
            .on_conflict_do_nothing()
            .returning(InboxEvent.event_id)
        )
        return (await self.session.scalar(statement)) is not None

    async def lock_consumer_sequence(
        self,
        event: EventEnvelope,
        *,
        consumer_id: str,
    ) -> ConsumerSequence:
        self.require_workspace(event.workspace_id)
        await self.session.execute(
            insert(ConsumerSequence)
            .values(
                workspace_id=event.workspace_id,
                consumer_id=consumer_id,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                last_sequence=0,
            )
            .on_conflict_do_nothing()
        )
        sequence = await self.session.scalar(
            select(ConsumerSequence)
            .where(
                ConsumerSequence.workspace_id == event.workspace_id,
                ConsumerSequence.consumer_id == consumer_id,
                ConsumerSequence.aggregate_type == event.aggregate_type,
                ConsumerSequence.aggregate_id == event.aggregate_id,
            )
            .with_for_update()
        )
        assert sequence is not None
        return sequence

    async def add_quarantine(
        self,
        quarantine: EventQuarantine,
    ) -> EventQuarantine:
        self.require_workspace(quarantine.workspace_id)
        self.session.add(quarantine)
        await self.session.flush()
        return quarantine

    async def get_quarantine(
        self,
        *,
        workspace_id: uuid.UUID,
        quarantine_id: uuid.UUID,
        for_update: bool = False,
    ) -> EventQuarantine | None:
        self.require_workspace(workspace_id)
        statement = select(EventQuarantine).where(
            EventQuarantine.workspace_id == workspace_id,
            EventQuarantine.id == quarantine_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_inbox(
        self,
        *,
        workspace_id: uuid.UUID,
        consumer_id: str,
        event_id: uuid.UUID,
        for_update: bool = False,
    ) -> InboxEvent | None:
        self.require_workspace(workspace_id)
        statement = select(InboxEvent).where(
            InboxEvent.workspace_id == workspace_id,
            InboxEvent.consumer_id == consumer_id,
            InboxEvent.event_id == event_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)
