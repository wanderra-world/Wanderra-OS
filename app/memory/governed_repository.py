"""Execution-context-bound H3-05 governed-memory persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentVersion
from app.execution_context import ContextBoundRepository, ExecutionContext
from app.knowledge.models import KnowledgeClaim
from app.memory.governed_models import (
    GovernedMemoryDisposition,
    GovernedMemoryFeedback,
    GovernedMemoryItem,
    GovernedMemorySource,
)
from app.resource_graph.models import Resource


class GovernedMemoryRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, value: object) -> object:
        self.require_workspace(getattr(value, "workspace_id"))
        self.session.add(value)
        await self.session.flush()
        return value

    async def lock_identity(self, namespace: str, value: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"h3-05:{namespace}:{self.context.tenant.workspace_id}:{value}"},
        )

    async def item(
        self, memory_id: uuid.UUID, *, for_update: bool = False
    ) -> GovernedMemoryItem | None:
        statement = select(GovernedMemoryItem).where(
            GovernedMemoryItem.workspace_id == self.context.tenant.workspace_id,
            GovernedMemoryItem.id == memory_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def item_by_digest(self, digest: str) -> GovernedMemoryItem | None:
        return await self.session.scalar(
            select(GovernedMemoryItem).where(
                GovernedMemoryItem.workspace_id == self.context.tenant.workspace_id,
                GovernedMemoryItem.identity_digest == digest,
            )
        )

    async def resource(self, resource_id: uuid.UUID) -> Resource | None:
        return await self.session.scalar(
            select(Resource).where(
                Resource.workspace_id == self.context.tenant.workspace_id,
                Resource.id == resource_id,
                Resource.status == "active",
            )
        )

    async def document_version(self, version_id: uuid.UUID) -> DocumentVersion | None:
        return await self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.workspace_id == self.context.tenant.workspace_id,
                DocumentVersion.id == version_id,
            )
        )

    async def claim(self, claim_id: uuid.UUID) -> KnowledgeClaim | None:
        return await self.session.scalar(
            select(KnowledgeClaim).where(
                KnowledgeClaim.workspace_id == self.context.tenant.workspace_id,
                KnowledgeClaim.id == claim_id,
            )
        )

    async def sources(self, memory_id: uuid.UUID) -> tuple[GovernedMemorySource, ...]:
        return tuple(
            await self.session.scalars(
                select(GovernedMemorySource).where(
                    GovernedMemorySource.workspace_id == self.context.tenant.workspace_id,
                    GovernedMemorySource.memory_id == memory_id,
                )
            )
        )

    async def feedback(self, memory_id: uuid.UUID) -> tuple[GovernedMemoryFeedback, ...]:
        return tuple(
            await self.session.scalars(
                select(GovernedMemoryFeedback).where(
                    GovernedMemoryFeedback.workspace_id == self.context.tenant.workspace_id,
                    GovernedMemoryFeedback.memory_id == memory_id,
                )
            )
        )

    async def due(self, *, now, for_update: bool = False) -> tuple[GovernedMemoryItem, ...]:
        statement = select(GovernedMemoryItem).where(
            GovernedMemoryItem.workspace_id == self.context.tenant.workspace_id,
            GovernedMemoryItem.status == "active",
            GovernedMemoryItem.pinned.is_(False),
            GovernedMemoryItem.expires_at.is_not(None),
            GovernedMemoryItem.expires_at <= now,
        )
        if for_update:
            statement = statement.with_for_update()
        return tuple(await self.session.scalars(statement))

    async def dependents(
        self, source_kind: str, source_id: uuid.UUID, *, for_update: bool = False
    ) -> tuple[GovernedMemoryItem, ...]:
        statement = (
            select(GovernedMemoryItem)
            .join(
                GovernedMemorySource,
                (GovernedMemorySource.workspace_id == GovernedMemoryItem.workspace_id)
                & (GovernedMemorySource.memory_id == GovernedMemoryItem.id),
            )
            .where(
                GovernedMemoryItem.workspace_id == self.context.tenant.workspace_id,
                GovernedMemorySource.source_kind == source_kind,
                GovernedMemorySource.source_reference_id == source_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return tuple(dict.fromkeys(await self.session.scalars(statement)))

    async def disposition(
        self, memory_id: uuid.UUID, reason: str
    ) -> GovernedMemoryDisposition | None:
        return await self.session.scalar(
            select(GovernedMemoryDisposition).where(
                GovernedMemoryDisposition.workspace_id == self.context.tenant.workspace_id,
                GovernedMemoryDisposition.memory_id == memory_id,
                GovernedMemoryDisposition.reason == reason,
            )
        )

    async def export_rows(
        self,
    ) -> tuple[
        tuple[GovernedMemoryItem, ...],
        tuple[GovernedMemorySource, ...],
        tuple[GovernedMemoryFeedback, ...],
        tuple[GovernedMemoryDisposition, ...],
    ]:
        workspace_id = self.context.tenant.workspace_id
        items = tuple(
            await self.session.scalars(
                select(GovernedMemoryItem).where(GovernedMemoryItem.workspace_id == workspace_id)
            )
        )
        sources = tuple(
            await self.session.scalars(
                select(GovernedMemorySource).where(
                    GovernedMemorySource.workspace_id == workspace_id
                )
            )
        )
        feedback = tuple(
            await self.session.scalars(
                select(GovernedMemoryFeedback).where(
                    GovernedMemoryFeedback.workspace_id == workspace_id
                )
            )
        )
        dispositions = tuple(
            await self.session.scalars(
                select(GovernedMemoryDisposition).where(
                    GovernedMemoryDisposition.workspace_id == workspace_id
                )
            )
        )
        return items, sources, feedback, dispositions
