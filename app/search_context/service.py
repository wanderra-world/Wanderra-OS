"""Authorized, deterministic H3-06 indexing, retrieval, and context assembly."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import AuthorizationRequest, AuthorizationService, DecisionEffect
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.search_context.contracts import (
    AssembledContext,
    ContextPolicy,
    EmbeddingPort,
    SearchAuthorizationError,
    SearchDocumentInput,
    SearchError,
    SearchQuery,
    assemble_context,
    reciprocal_rank_fusion,
)
from app.search_context.models import (
    SearchAclProjection,
    SearchDocument,
    SearchEmbedding,
    SearchIndexGeneration,
    SearchReconciliation,
)
from app.search_context.repository import SearchRepository
from app.tenancy.models import OutboxEvent


class SearchAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class H1SearchAuthorizer:
    def __init__(self, session: AsyncSession) -> None:
        self._service = AuthorizationService(session)

    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool:
        decision = await self._service.authorize(
            AuthorizationRequest(
                actor_id=context.actor.actor_id,
                session_id=context.actor.session_id,
                organization_id=context.tenant.organization_id,
                requested_workspace_id=context.tenant.workspace_id,
                membership_workspace_id=context.tenant.workspace_id,
                membership_id=context.actor.membership_id,
                permission_key=permission_key,
                request_reference=context.request.request_id,
            )
        )
        return decision.effect is DecisionEffect.ALLOW


class SearchContextService:
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: SearchAuthorizer | None = None,
        embedding: EmbeddingPort | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._authorizer = authorizer or H1SearchAuthorizer(session)
        self._embedding = embedding
        self._repository = SearchRepository(session, context)
        self._audit = AuditWriterService(session, context)

    def _tenant(self) -> dict[str, uuid.UUID]:
        return {
            "organization_id": self._context.tenant.organization_id,
            "workspace_id": self._context.tenant.workspace_id,
            "cell_id": self._context.tenant.cell_id,
        }

    async def create_generation(
        self,
        *,
        generation_id: uuid.UUID,
        index_version: str,
        chunker_version: str,
        policy_version: int,
        manifest_digest: str,
    ) -> SearchIndexGeneration:
        await self._require("update_content")
        if len(manifest_digest) != 64 or policy_version < 1:
            raise SearchError("invalid generation manifest")
        await self._repository.lock(f"generation:{index_version}")
        existing = await self._repository.generation(generation_id)
        if existing:
            if existing.manifest_digest != manifest_digest:
                raise SearchError("generation replay changed manifest")
            return existing
        model = self._embedding
        generation = SearchIndexGeneration(
            **self._tenant(),
            id=generation_id,
            index_version=index_version,
            chunker_version=chunker_version,
            embedding_model=model.model_key if model else "disabled",
            embedding_version=model.model_version if model else "disabled",
            dimensions=model.dimensions if model else 1,
            policy_version=policy_version,
            status="building",
            manifest_digest=manifest_digest,
            created_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add(generation)
        await self._record(generation.id, "search.generation.created", "internal")
        return generation

    async def activate_generation(
        self, generation_id: uuid.UUID, *, now: datetime | None = None
    ) -> SearchIndexGeneration:
        await self._require("update_content")
        generation = await self._repository.generation(generation_id)
        if generation is None or generation.status not in {"building", "active"}:
            raise SearchError("generation cannot be activated")
        active = await self._repository.active_generation()
        if active and active.id != generation.id:
            active.status = "disabled"
        generation.status = "active"
        generation.activated_at = now or datetime.now(UTC)
        await self._record(generation.id, "search.generation.activated", "internal")
        return generation

    async def index(
        self, generation_id: uuid.UUID, value: SearchDocumentInput, *, now: datetime | None = None
    ) -> SearchDocument:
        await self._require("update_content")
        generation = await self._repository.generation(generation_id)
        if generation is None or generation.status not in {"building", "active"}:
            raise SearchError("index generation is unavailable")
        digest = value.identity_digest()
        await self._repository.lock(f"document:{generation_id}:{digest}")
        existing = await self._repository.document_by_identity(generation_id, digest)
        if existing:
            return existing
        occurred_at = now or datetime.now(UTC)
        document = SearchDocument(
            **self._tenant(),
            id=uuid.uuid4(),
            generation_id=generation_id,
            source_kind=str(value.source_kind),
            source_id=value.source_id,
            source_version=value.source_version,
            source_digest=value.source_digest,
            identity_digest=digest,
            resource_id=value.resource_id,
            owner_user_id=value.owner_user_id,
            title=value.title,
            content=value.content,
            visibility=value.visibility,
            classification=value.classification.value,
            policy_version=value.policy_version,
            chunker_version=value.chunker_version,
            status="active",
            source_changed_at=occurred_at,
        )
        await self._repository.add(document)
        principal_type = "user" if value.visibility == "private" else "workspace"
        principal_id = (
            value.owner_user_id if principal_type == "user" else self._context.tenant.workspace_id
        )
        if principal_id is None:
            raise SearchError("private search document requires an owner")
        await self._repository.add(
            SearchAclProjection(
                **self._tenant(),
                id=uuid.uuid4(),
                document_id=document.id,
                principal_type=principal_type,
                principal_id=principal_id,
                policy_version=value.policy_version,
                status="active",
            )
        )
        if self._embedding is not None:
            vector = list(await self._embedding.embed(f"{value.title}\n{value.content}"))
            if len(vector) != self._embedding.dimensions:
                raise SearchError("embedding dimensions do not match the generation")
            await self._repository.add(
                SearchEmbedding(
                    **self._tenant(),
                    id=uuid.uuid4(),
                    document_id=document.id,
                    model_key=self._embedding.model_key,
                    model_version=self._embedding.model_version,
                    dimensions=len(vector),
                    embedding=vector,
                    input_digest=hashlib.sha256(
                        f"{value.title}\n{value.content}".encode()
                    ).hexdigest(),
                )
            )
        await self._record(document.id, "search.document.indexed", value.classification.value)
        return document

    async def search(self, query: SearchQuery) -> tuple[SearchDocument, ...]:
        await self._require("read_content")
        generation = await self._repository.active_generation()
        if generation is None:
            return ()
        resources = query.resource_ids
        if query.graph_root_id:
            resources = resources | await self._repository.graph_neighborhood(
                query.graph_root_id, query.graph_depth
            )
        kwargs = dict(
            actor_id=self._context.actor.actor_id,
            generation_id=generation.id,
            limit=min(query.limit * 4, 100),
            resource_ids=resources,
            source_kinds=frozenset(value.value for value in query.source_kinds),
            classifications=frozenset(value.value for value in query.classifications),
        )
        lexical = await self._repository.lexical_candidates(
            query=query.text,
            **kwargs,
        )
        vector: tuple[SearchDocument, ...] = ()
        if self._embedding is not None and query.text.strip():
            vector = await self._repository.vector_candidates(
                vector=list(await self._embedding.embed(query.text)), **kwargs
            )
        exact = frozenset(
            item.id
            for item in lexical
            if query.text.casefold() in {item.title.casefold(), str(item.source_id).casefold()}
        )
        ranked = reciprocal_rank_fusion(
            lexical=tuple(item.id for item in lexical),
            vector=tuple(item.id for item in vector),
            exact_ids=exact,
        )
        by_id = {item.id: item for item in (*lexical, *vector)}
        return tuple(by_id[item_id] for item_id, _ in ranked[: query.limit])

    async def context(self, query: SearchQuery, policy: ContextPolicy) -> AssembledContext:
        results = await self.search(query)
        return assemble_context(
            results=tuple(
                {
                    "document_id": item.id,
                    "source_id": item.source_id,
                    "source_version": item.source_version,
                    "source_digest": item.source_digest,
                    "content": item.content,
                    "classification": item.classification,
                    "policy_version": item.policy_version,
                    "index_version": str(item.generation_id),
                }
                for item in results
            ),
            policy=policy,
        )

    async def dispose_source(
        self, source_kind: str, source_id: uuid.UUID, *, reason: str = "source_unavailable"
    ) -> int:
        await self._require("update_content")
        digest = hashlib.sha256(
            json.dumps(
                {"source_kind": source_kind, "source_id": str(source_id), "reason": reason},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        await self._repository.lock(f"dispose:{digest}")
        if await self._repository.reconciliation(digest) is not None:
            return 0
        changed = await self._repository.mark_source_unavailable(source_kind, source_id)
        await self._repository.add(
            SearchReconciliation(
                **self._tenant(),
                id=uuid.uuid4(),
                idempotency_key=digest,
                source_kind=source_kind,
                source_id=source_id,
                input_digest=digest,
                reason=reason,
                status="completed",
                completed_at=datetime.now(UTC),
            )
        )
        await self._record(source_id, "search.source.disposed", "internal")
        return changed

    async def _require(self, permission: str) -> None:
        if not await self._authorizer.authorize(self._context, permission):
            raise SearchAuthorizationError(f"{permission} authorization denied")

    async def _record(self, aggregate_id: uuid.UUID, event_type: str, classification: str) -> None:
        await self._audit.write(
            AuditInput(
                action=event_type,
                target_type="search",
                target_id=aggregate_id,
                outcome="success",
                classification=classification,
                details=self._context.audit_references(),
            )
        )
        sequence = (
            int(
                await self._session.scalar(
                    select(func.coalesce(func.max(OutboxEvent.aggregate_sequence), 0)).where(
                        OutboxEvent.workspace_id == self._context.tenant.workspace_id,
                        OutboxEvent.aggregate_type == "search",
                        OutboxEvent.aggregate_id == aggregate_id,
                    )
                )
                or 0
            )
            + 1
        )
        self._session.add(
            OutboxEvent(
                workspace_id=self._context.tenant.workspace_id,
                event_type=event_type,
                aggregate_type="search",
                aggregate_id=aggregate_id,
                aggregate_sequence=sequence,
                payload={"event_type": event_type, "aggregate_id": str(aggregate_id)},
                actor_id=self._context.actor.actor_id,
                correlation_id=self._context.request.correlation_id,
                classification=classification,
            )
        )
