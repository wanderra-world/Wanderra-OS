"""Execution-context-bound H3-04 persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import DocumentChunk, DocumentVersion
from app.execution_context import ContextBoundRepository, ExecutionContext
from app.knowledge.models import (
    KnowledgeClaim,
    KnowledgeEvidence,
    KnowledgeRelation,
    KnowledgeSourceDisposition,
    TimelineCheckpoint,
    TimelineEntry,
)
from app.resource_graph.models import Resource


class KnowledgeRepository(ContextBoundRepository):
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
            {"identity": f"h3-04:{namespace}:{self.context.tenant.workspace_id}:{value}"},
        )

    async def resource(self, resource_id: uuid.UUID) -> Resource | None:
        return await self.session.scalar(
            select(Resource).where(
                Resource.workspace_id == self.context.tenant.workspace_id,
                Resource.id == resource_id,
                Resource.status == "active",
            )
        )

    async def version(self, version_id: uuid.UUID) -> DocumentVersion | None:
        return await self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.workspace_id == self.context.tenant.workspace_id,
                DocumentVersion.id == version_id,
            )
        )

    async def chunk(self, chunk_id: uuid.UUID) -> DocumentChunk | None:
        return await self.session.scalar(
            select(DocumentChunk).where(
                DocumentChunk.workspace_id == self.context.tenant.workspace_id,
                DocumentChunk.id == chunk_id,
            )
        )

    async def claim(
        self, claim_id: uuid.UUID, *, for_update: bool = False
    ) -> KnowledgeClaim | None:
        statement = select(KnowledgeClaim).where(
            KnowledgeClaim.workspace_id == self.context.tenant.workspace_id,
            KnowledgeClaim.id == claim_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def claim_by_digest(self, digest: str) -> KnowledgeClaim | None:
        return await self.session.scalar(
            select(KnowledgeClaim).where(
                KnowledgeClaim.workspace_id == self.context.tenant.workspace_id,
                KnowledgeClaim.identity_digest == digest,
            )
        )

    async def evidence_for_claim(self, claim_id: uuid.UUID) -> tuple[KnowledgeEvidence, ...]:
        values = await self.session.scalars(
            select(KnowledgeEvidence).where(
                KnowledgeEvidence.workspace_id == self.context.tenant.workspace_id,
                KnowledgeEvidence.claim_id == claim_id,
            )
        )
        return tuple(values)

    async def claims_for_source(self, version_id: uuid.UUID) -> tuple[KnowledgeClaim, ...]:
        values = await self.session.scalars(
            select(KnowledgeClaim)
            .join(
                KnowledgeEvidence,
                (
                    (KnowledgeEvidence.workspace_id == KnowledgeClaim.workspace_id)
                    & (KnowledgeEvidence.claim_id == KnowledgeClaim.id)
                ),
            )
            .where(
                KnowledgeClaim.workspace_id == self.context.tenant.workspace_id,
                KnowledgeEvidence.source_version_id == version_id,
            )
            .with_for_update()
        )
        return tuple(dict.fromkeys(values))

    async def disposition_by_source(
        self, source_version_id: uuid.UUID
    ) -> KnowledgeSourceDisposition | None:
        return await self.session.scalar(
            select(KnowledgeSourceDisposition).where(
                KnowledgeSourceDisposition.workspace_id == self.context.tenant.workspace_id,
                KnowledgeSourceDisposition.source_version_id == source_version_id,
            )
        )

    async def disposition(
        self, disposition_id: uuid.UUID, *, for_update: bool = False
    ) -> KnowledgeSourceDisposition | None:
        statement = select(KnowledgeSourceDisposition).where(
            KnowledgeSourceDisposition.workspace_id == self.context.tenant.workspace_id,
            KnowledgeSourceDisposition.id == disposition_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def timeline_by_source(self, source_event_id: uuid.UUID) -> TimelineEntry | None:
        return await self.session.scalar(
            select(TimelineEntry).where(
                TimelineEntry.workspace_id == self.context.tenant.workspace_id,
                TimelineEntry.source_event_id == source_event_id,
            )
        )

    async def timeline(
        self, projection_key: str, *, for_update: bool = False
    ) -> tuple[TimelineEntry, ...]:
        statement = (
            select(TimelineEntry)
            .where(
                TimelineEntry.workspace_id == self.context.tenant.workspace_id,
                TimelineEntry.projection_key == projection_key,
            )
            .order_by(
                TimelineEntry.occurred_at,
                TimelineEntry.source_sequence,
                TimelineEntry.source_event_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return tuple(await self.session.scalars(statement))

    async def checkpoint(
        self, projection_key: str, *, for_update: bool = False
    ) -> TimelineCheckpoint | None:
        statement = select(TimelineCheckpoint).where(
            TimelineCheckpoint.workspace_id == self.context.tenant.workspace_id,
            TimelineCheckpoint.projection_key == projection_key,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def timeline_for_claims(
        self, claim_ids: tuple[uuid.UUID, ...]
    ) -> tuple[TimelineEntry, ...]:
        if not claim_ids:
            return ()
        return tuple(
            await self.session.scalars(
                select(TimelineEntry)
                .where(
                    TimelineEntry.workspace_id == self.context.tenant.workspace_id,
                    TimelineEntry.source_claim_id.in_(claim_ids),
                )
                .with_for_update()
            )
        )

    async def export_rows(
        self,
    ) -> tuple[
        tuple[KnowledgeClaim, ...],
        tuple[KnowledgeEvidence, ...],
        tuple[KnowledgeRelation, ...],
        tuple[KnowledgeSourceDisposition, ...],
    ]:
        claims = tuple(
            await self.session.scalars(
                select(KnowledgeClaim)
                .where(KnowledgeClaim.workspace_id == self.context.tenant.workspace_id)
                .order_by(KnowledgeClaim.id)
            )
        )
        evidence = tuple(
            await self.session.scalars(
                select(KnowledgeEvidence)
                .where(KnowledgeEvidence.workspace_id == self.context.tenant.workspace_id)
                .order_by(KnowledgeEvidence.id)
            )
        )
        relations = tuple(
            await self.session.scalars(
                select(KnowledgeRelation)
                .where(KnowledgeRelation.workspace_id == self.context.tenant.workspace_id)
                .order_by(KnowledgeRelation.id)
            )
        )
        dispositions = tuple(
            await self.session.scalars(
                select(KnowledgeSourceDisposition)
                .where(KnowledgeSourceDisposition.workspace_id == self.context.tenant.workspace_id)
                .order_by(KnowledgeSourceDisposition.id)
            )
        )
        return claims, evidence, relations, dispositions
