"""Execution-context-bound H3-06 search persistence and retrieval."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.resource_graph.models import Resource, ResourceRelationship
from app.search_context.models import (
    SearchAclProjection,
    SearchDocument,
    SearchEmbedding,
    SearchIndexGeneration,
    SearchReconciliation,
)


class SearchRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, value: object) -> object:
        self.require_workspace(getattr(value, "workspace_id"))
        self.session.add(value)
        await self.session.flush()
        return value

    async def lock(self, identity: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:value, 0))"),
            {"value": f"h3-06:{self.context.tenant.workspace_id}:{identity}"},
        )

    async def generation(self, generation_id: uuid.UUID) -> SearchIndexGeneration | None:
        return await self.session.scalar(
            select(SearchIndexGeneration).where(
                SearchIndexGeneration.workspace_id == self.context.tenant.workspace_id,
                SearchIndexGeneration.id == generation_id,
            )
        )

    async def active_generation(self) -> SearchIndexGeneration | None:
        return await self.session.scalar(
            select(SearchIndexGeneration).where(
                SearchIndexGeneration.workspace_id == self.context.tenant.workspace_id,
                SearchIndexGeneration.status == "active",
            )
        )

    async def document_by_identity(
        self, generation_id: uuid.UUID, digest: str
    ) -> SearchDocument | None:
        return await self.session.scalar(
            select(SearchDocument).where(
                SearchDocument.workspace_id == self.context.tenant.workspace_id,
                SearchDocument.generation_id == generation_id,
                SearchDocument.identity_digest == digest,
            )
        )

    async def graph_neighborhood(self, root_id: uuid.UUID, depth: int) -> frozenset[uuid.UUID]:
        found = {root_id}
        frontier = {root_id}
        for _ in range(depth):
            if not frontier:
                break
            rows = await self.session.execute(
                select(
                    ResourceRelationship.source_resource_id,
                    ResourceRelationship.target_resource_id,
                ).where(
                    ResourceRelationship.workspace_id == self.context.tenant.workspace_id,
                    ResourceRelationship.status == "active",
                    or_(
                        ResourceRelationship.source_resource_id.in_(frontier),
                        ResourceRelationship.target_resource_id.in_(frontier),
                    ),
                )
            )
            next_frontier = {value for row in rows for value in row} - found
            found.update(next_frontier)
            frontier = next_frontier
        return frozenset(found)

    def _authorized(self, actor_id: uuid.UUID):
        return and_(
            SearchAclProjection.status == "active",
            or_(
                and_(
                    SearchAclProjection.principal_type == "workspace",
                    SearchAclProjection.principal_id == self.context.tenant.workspace_id,
                ),
                and_(
                    SearchAclProjection.principal_type == "user",
                    SearchAclProjection.principal_id == actor_id,
                ),
            ),
        )

    async def lexical_candidates(
        self,
        *,
        actor_id: uuid.UUID,
        generation_id: uuid.UUID,
        query: str,
        limit: int,
        source_kinds: frozenset[str],
        classifications: frozenset[str],
        resource_ids: frozenset[uuid.UUID],
    ) -> tuple[SearchDocument, ...]:
        ts_query = func.websearch_to_tsquery("simple", query)
        rank = func.ts_rank_cd(SearchDocument.search_vector, ts_query)
        statement = (
            select(SearchDocument)
            .join(
                SearchAclProjection,
                and_(
                    SearchAclProjection.workspace_id == SearchDocument.workspace_id,
                    SearchAclProjection.document_id == SearchDocument.id,
                ),
            )
            .outerjoin(
                Resource,
                and_(
                    Resource.workspace_id == SearchDocument.workspace_id,
                    Resource.id == SearchDocument.resource_id,
                ),
            )
            .where(
                SearchDocument.workspace_id == self.context.tenant.workspace_id,
                SearchDocument.generation_id == generation_id,
                SearchDocument.status == "active",
                or_(SearchDocument.resource_id.is_(None), Resource.status == "active"),
                self._authorized(actor_id),
                SearchDocument.search_vector.op("@@")(ts_query),
            )
            .order_by(rank.desc(), SearchDocument.id)
            .limit(limit)
        )
        if source_kinds:
            statement = statement.where(SearchDocument.source_kind.in_(source_kinds))
        if classifications:
            statement = statement.where(SearchDocument.classification.in_(classifications))
        if resource_ids:
            statement = statement.where(SearchDocument.resource_id.in_(resource_ids))
        return tuple(dict.fromkeys(await self.session.scalars(statement)))

    async def vector_candidates(
        self,
        *,
        actor_id: uuid.UUID,
        generation_id: uuid.UUID,
        vector: list[float],
        limit: int,
        resource_ids: frozenset[uuid.UUID],
        source_kinds: frozenset[str],
        classifications: frozenset[str],
    ) -> tuple[SearchDocument, ...]:
        distance = SearchEmbedding.embedding.op("<=>")(vector)
        statement = (
            select(SearchDocument)
            .join(
                SearchEmbedding,
                and_(
                    SearchEmbedding.workspace_id == SearchDocument.workspace_id,
                    SearchEmbedding.document_id == SearchDocument.id,
                ),
            )
            .join(
                SearchAclProjection,
                and_(
                    SearchAclProjection.workspace_id == SearchDocument.workspace_id,
                    SearchAclProjection.document_id == SearchDocument.id,
                ),
            )
            .outerjoin(
                Resource,
                and_(
                    Resource.workspace_id == SearchDocument.workspace_id,
                    Resource.id == SearchDocument.resource_id,
                ),
            )
            .where(
                SearchDocument.workspace_id == self.context.tenant.workspace_id,
                SearchDocument.generation_id == generation_id,
                SearchDocument.status == "active",
                or_(SearchDocument.resource_id.is_(None), Resource.status == "active"),
                self._authorized(actor_id),
            )
            .order_by(distance, SearchDocument.id)
            .limit(limit)
        )
        if resource_ids:
            statement = statement.where(SearchDocument.resource_id.in_(resource_ids))
        if source_kinds:
            statement = statement.where(SearchDocument.source_kind.in_(source_kinds))
        if classifications:
            statement = statement.where(SearchDocument.classification.in_(classifications))
        return tuple(dict.fromkeys(await self.session.scalars(statement)))

    async def mark_source_unavailable(self, source_kind: str, source_id: uuid.UUID) -> int:
        result = await self.session.execute(
            update(SearchDocument)
            .where(
                SearchDocument.workspace_id == self.context.tenant.workspace_id,
                SearchDocument.source_kind == source_kind,
                SearchDocument.source_id == source_id,
                SearchDocument.status == "active",
            )
            .values(status="stale")
        )
        return result.rowcount or 0

    async def reconciliations(self) -> tuple[SearchReconciliation, ...]:
        return tuple(
            await self.session.scalars(
                select(SearchReconciliation).where(
                    SearchReconciliation.workspace_id == self.context.tenant.workspace_id
                )
            )
        )

    async def reconciliation(self, idempotency_key: str) -> SearchReconciliation | None:
        return await self.session.scalar(
            select(SearchReconciliation).where(
                SearchReconciliation.workspace_id == self.context.tenant.workspace_id,
                SearchReconciliation.idempotency_key == idempotency_key,
            )
        )
