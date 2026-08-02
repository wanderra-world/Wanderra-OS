"""Authorized transactional H3-05 governed Memory Manager."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import AuthorizationRequest, AuthorizationService, DecisionEffect
from app.documents.contracts import Classification
from app.execution_context import ExecutionContext
from app.memory.governance_contracts import (
    ConsolidationCreate,
    MemoryAuthorizationError,
    MemoryCreate,
    MemoryError,
    MemoryFeedbackCreate,
    MemorySource,
    MemorySourceKind,
    MemoryStatus,
    ModelRoute,
    effective_classification,
    evaluate_status,
    require_model_egress,
    versioned_source_digest,
)
from app.memory.governed_models import (
    GovernedMemoryDisposition,
    GovernedMemoryFeedback,
    GovernedMemoryItem,
    GovernedMemorySource,
)
from app.memory.governed_repository import GovernedMemoryRepository
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent


class MemoryAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class H1MemoryAuthorizer:
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


class GovernedMemoryService:
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: MemoryAuthorizer | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._authorizer = authorizer or H1MemoryAuthorizer(session)
        self._repository = GovernedMemoryRepository(session, context)
        self._audit = AuditWriterService(session, context)

    def _tenant(self) -> dict[str, uuid.UUID]:
        return {
            "organization_id": self._context.tenant.organization_id,
            "workspace_id": self._context.tenant.workspace_id,
            "cell_id": self._context.tenant.cell_id,
        }

    async def create(
        self, command: MemoryCreate, *, now: datetime | None = None
    ) -> GovernedMemoryItem:
        await self._require_authorized("update_content")
        await self._repository.lock_identity("identity", command.identity_digest)
        existing = await self._repository.item_by_digest(command.identity_digest)
        if existing is not None:
            return existing
        if command.subject_resource_id is not None:
            if await self._repository.resource(command.subject_resource_id) is None:
                raise MemoryError("memory subject resource is unavailable")
        await self._validate_sources(command.sources)
        occurred_at = now or datetime.now(UTC)
        item = GovernedMemoryItem(
            **self._tenant(),
            id=command.memory_id,
            memory_kind=command.memory_kind.value,
            content=command.content,
            identity_digest=command.identity_digest,
            subject_resource_id=command.subject_resource_id,
            owner_user_id=command.owner_user_id,
            visibility=command.visibility.value,
            confidence_basis_points=round(command.confidence * 10000),
            classification=command.classification.value,
            policy_version=command.policy_version,
            creation_method=command.creation_method,
            status=MemoryStatus.ACTIVE.value,
            pinned=False,
            human_confirmed=command.creation_method == "human_confirmed",
            confirmed_by_user_id=(
                self._context.actor.actor_id
                if command.creation_method == "human_confirmed"
                else None
            ),
            confirmed_at=occurred_at if command.creation_method == "human_confirmed" else None,
            expires_at=command.expires_at,
            superseded_by_id=None,
            processor_key=None,
            processor_version=None,
            input_digest=None,
            state_version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        await self._repository.add(item)
        for source in command.sources:
            await self._repository.add(self._source_model(item.id, source, occurred_at))
        await self._record(item, "memory.item.created", occurred_at)
        return item

    async def consolidate(
        self,
        command: ConsolidationCreate,
        memory: MemoryCreate,
        *,
        now: datetime | None = None,
    ) -> GovernedMemoryItem:
        await self._require_authorized("update_content")
        if command.memory_id != memory.memory_id:
            raise MemoryError("consolidation output identity does not match memory")
        expected_sources: list[MemorySource] = []
        for memory_id in command.input_memory_ids:
            item = await self._require_available(memory_id, now=now)
            expected_sources.append(
                MemorySource(
                    source_id=item.id,
                    source_kind=MemorySourceKind.MEMORY_ITEM,
                    source_version=item.state_version,
                    source_digest=item.identity_digest,
                    classification=Classification(item.classification),
                    policy_version=item.policy_version,
                )
            )
        if tuple(memory.sources) != tuple(expected_sources):
            raise MemoryError("consolidation provenance does not match inputs")
        if memory.classification is not effective_classification(
            item.classification for item in expected_sources
        ):
            raise MemoryError("consolidation classification must equal its effective source class")
        item = await self.create(memory, now=now)
        if item.processor_key is not None and item.input_digest != command.input_digest:
            raise MemoryError("consolidation replay changed inputs")
        item.processor_key = command.processor_key
        item.processor_version = command.processor_version
        item.input_digest = command.input_digest
        return item

    async def get(
        self,
        memory_id: uuid.UUID,
        *,
        now: datetime | None = None,
        model_route: ModelRoute | None = None,
    ) -> GovernedMemoryItem:
        await self._require_authorized("read_content")
        item = await self._require_available(memory_id, now=now)
        await self._revalidate_sources(item.id)
        if model_route is not None:
            require_model_egress(Classification(item.classification), model_route)
        if item.visibility == "private" and item.owner_user_id != self._context.actor.actor_id:
            raise MemoryAuthorizationError("private memory is not visible to this actor")
        return item

    async def set_pinned(
        self, memory_id: uuid.UUID, pinned: bool, *, now: datetime | None = None
    ) -> GovernedMemoryItem:
        await self._require_authorized("update_content")
        item = await self._require_item(memory_id, for_update=True)
        if item.status != MemoryStatus.ACTIVE.value:
            raise MemoryError("only active memory can be pinned")
        if item.pinned == pinned:
            return item
        item.pinned = pinned
        await self._change(item, "memory.item.pinned" if pinned else "memory.item.unpinned", now)
        return item

    async def confirm(
        self, memory_id: uuid.UUID, *, now: datetime | None = None
    ) -> GovernedMemoryItem:
        await self._require_authorized("update_content")
        item = await self._require_item(memory_id, for_update=True)
        if item.status != MemoryStatus.ACTIVE.value:
            raise MemoryError("only active memory can be confirmed")
        if item.human_confirmed:
            return item
        occurred_at = now or datetime.now(UTC)
        item.human_confirmed = True
        item.confirmed_by_user_id = self._context.actor.actor_id
        item.confirmed_at = occurred_at
        await self._change(item, "memory.item.confirmed", occurred_at)
        return item

    async def add_feedback(
        self, command: MemoryFeedbackCreate, *, now: datetime | None = None
    ) -> GovernedMemoryFeedback:
        await self._require_authorized("update_content")
        item = await self._require_item(command.memory_id)
        occurred_at = now or datetime.now(UTC)
        feedback = GovernedMemoryFeedback(
            **self._tenant(),
            id=command.feedback_id,
            memory_id=item.id,
            kind=command.kind.value,
            reason=command.reason,
            classification=item.classification,
            policy_version=item.policy_version,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
        )
        await self._repository.add(feedback)
        await self._change(item, "memory.feedback.recorded", occurred_at)
        return feedback

    async def supersede(
        self,
        memory_id: uuid.UUID,
        replacement_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> GovernedMemoryItem:
        await self._require_authorized("update_content")
        if memory_id == replacement_id:
            raise MemoryError("memory cannot supersede itself")
        prior = await self._require_item(memory_id, for_update=True)
        replacement = await self._require_available(replacement_id, now=now)
        if prior.status == MemoryStatus.SUPERSEDED.value:
            if prior.superseded_by_id != replacement.id:
                raise MemoryError("memory supersession replay changed replacement")
            return prior
        if prior.status != MemoryStatus.ACTIVE.value:
            raise MemoryError("only active memory can be superseded")
        prior.superseded_by_id = replacement.id
        await self._dispose(prior, "superseded", MemoryStatus.SUPERSEDED, now)
        return prior

    async def expire_due(self, *, now: datetime) -> tuple[GovernedMemoryItem, ...]:
        await self._require_authorized("delete_content")
        values = await self._repository.due(now=now, for_update=True)
        for item in values:
            await self._dispose(item, "expired", MemoryStatus.EXPIRED, now)
        return values

    async def delete(
        self, memory_id: uuid.UUID, *, now: datetime | None = None
    ) -> GovernedMemoryItem:
        await self._require_authorized("delete_content")
        item = await self._require_item(memory_id, for_update=True)
        if item.status == MemoryStatus.DELETED.value:
            return item
        await self._dispose(item, "user_deleted", MemoryStatus.DELETED, now)
        return item

    async def dispose_source(
        self,
        source_kind: MemorySourceKind,
        source_id: uuid.UUID,
        *,
        reason: str = "source_deleted",
        now: datetime | None = None,
    ) -> tuple[GovernedMemoryItem, ...]:
        await self._require_authorized("delete_content")
        if reason not in {"source_deleted", "permission_revoked", "workspace_closure"}:
            raise MemoryError("source disposition reason is invalid")
        occurred_at = now or datetime.now(UTC)
        queue = list(
            await self._repository.dependents(
                MemorySourceKind(source_kind).value, source_id, for_update=True
            )
        )
        changed: list[GovernedMemoryItem] = []
        seen: set[uuid.UUID] = set()
        while queue:
            item = queue.pop(0)
            if item.id in seen:
                continue
            seen.add(item.id)
            if item.status == MemoryStatus.ACTIVE.value:
                await self._dispose(item, reason, MemoryStatus.INVALIDATED, occurred_at)
                changed.append(item)
            queue.extend(
                await self._repository.dependents(
                    MemorySourceKind.MEMORY_ITEM.value, item.id, for_update=True
                )
            )
        return tuple(changed)

    async def export_manifest(self) -> dict[str, object]:
        await self._require_authorized("export_workspace")
        items, sources, feedback, dispositions = await self._repository.export_rows()
        return {
            "workspace_id": str(self._context.tenant.workspace_id),
            "memories": [
                {
                    "memory_id": str(item.id),
                    "memory_kind": item.memory_kind,
                    "content": item.content,
                    "identity_digest": item.identity_digest,
                    "subject_resource_id": str(item.subject_resource_id)
                    if item.subject_resource_id
                    else None,
                    "owner_user_id": str(item.owner_user_id),
                    "visibility": item.visibility,
                    "confidence_basis_points": item.confidence_basis_points,
                    "classification": item.classification,
                    "policy_version": item.policy_version,
                    "status": item.status,
                    "pinned": item.pinned,
                    "human_confirmed": item.human_confirmed,
                    "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                    "superseded_by_id": str(item.superseded_by_id)
                    if item.superseded_by_id
                    else None,
                }
                for item in items
            ],
            "sources": [
                {
                    "memory_id": str(source.memory_id),
                    "source_kind": source.source_kind,
                    "source_reference_id": str(source.source_reference_id),
                    "source_version": source.source_version,
                    "source_digest": source.source_digest,
                    "classification": source.classification,
                    "policy_version": source.policy_version,
                }
                for source in sources
            ],
            "feedback": [
                {
                    "feedback_id": str(value.id),
                    "memory_id": str(value.memory_id),
                    "kind": value.kind,
                    "reason": value.reason,
                }
                for value in feedback
            ],
            "dispositions": [
                {
                    "disposition_id": str(value.id),
                    "memory_id": str(value.memory_id),
                    "reason": value.reason,
                    "target_status": value.target_status,
                    "status": value.status,
                    "receipt_digest": value.receipt_digest,
                }
                for value in dispositions
            ],
        }

    async def _validate_sources(self, sources: tuple[MemorySource, ...]) -> None:
        for source in sources:
            actual_digest, actual_version = await self._source_state(source)
            if source.source_digest != actual_digest or source.source_version != actual_version:
                raise MemoryError("memory source provenance does not match current source")

    async def _source_state(self, source: MemorySource) -> tuple[str, int]:
        if source.source_kind is MemorySourceKind.DOCUMENT_VERSION:
            version = await self._repository.document_version(source.source_id)
            if version is None or version.custody_status != "verified":
                raise MemoryError("document source is unavailable")
            return version.content_hash, version.version_number
        if source.source_kind is MemorySourceKind.KNOWLEDGE_CLAIM:
            claim = await self._repository.claim(source.source_id)
            if claim is None or claim.status == "invalidated":
                raise MemoryError("knowledge source is unavailable")
            return claim.derivation_digest, claim.state_version
        if source.source_kind is MemorySourceKind.RESOURCE:
            resource = await self._repository.resource(source.source_id)
            if resource is None:
                raise MemoryError("resource source is unavailable")
            return versioned_source_digest(
                source.source_kind, resource.id, resource.version
            ), resource.version
        item = await self._repository.item(source.source_id)
        if item is None or item.status != MemoryStatus.ACTIVE.value:
            raise MemoryError("memory source is unavailable")
        return item.identity_digest, item.state_version

    async def _revalidate_sources(self, memory_id: uuid.UUID) -> None:
        for value in await self._repository.sources(memory_id):
            source = MemorySource(
                source_id=value.source_reference_id,
                source_kind=MemorySourceKind(value.source_kind),
                source_version=value.source_version,
                source_digest=value.source_digest,
                classification=Classification(value.classification),
                policy_version=value.policy_version,
            )
            actual_digest, actual_version = await self._source_state(source)
            if source.source_digest != actual_digest or source.source_version != actual_version:
                raise MemoryError("memory source provenance is stale")

    def _source_model(
        self, memory_id: uuid.UUID, source: MemorySource, now: datetime
    ) -> GovernedMemorySource:
        columns = {
            "source_document_version_id": None,
            "source_claim_id": None,
            "source_resource_id": None,
            "source_memory_id": None,
        }
        columns[
            {
                MemorySourceKind.DOCUMENT_VERSION: "source_document_version_id",
                MemorySourceKind.KNOWLEDGE_CLAIM: "source_claim_id",
                MemorySourceKind.RESOURCE: "source_resource_id",
                MemorySourceKind.MEMORY_ITEM: "source_memory_id",
            }[source.source_kind]
        ] = source.source_id
        return GovernedMemorySource(
            **self._tenant(),
            id=uuid.uuid5(
                memory_id, f"atlas.memory.source:{source.source_kind}:{source.source_id}"
            ),
            memory_id=memory_id,
            source_kind=source.source_kind.value,
            source_reference_id=source.source_id,
            source_version=source.source_version,
            source_digest=source.source_digest,
            classification=source.classification.value,
            policy_version=source.policy_version,
            created_at=now,
            **columns,
        )

    async def _require_item(
        self, memory_id: uuid.UUID, *, for_update: bool = False
    ) -> GovernedMemoryItem:
        item = await self._repository.item(memory_id, for_update=for_update)
        if item is None:
            raise MemoryError("governed memory does not exist")
        return item

    async def _require_available(
        self, memory_id: uuid.UUID, *, now: datetime | None
    ) -> GovernedMemoryItem:
        item = await self._require_item(memory_id)
        status = evaluate_status(
            MemoryStatus(item.status), item.expires_at, item.pinned, now or datetime.now(UTC)
        )
        if status is not MemoryStatus.ACTIVE:
            raise MemoryError(f"governed memory is {status.value}")
        return item

    async def _dispose(
        self,
        item: GovernedMemoryItem,
        reason: str,
        status: MemoryStatus,
        now: datetime | None,
    ) -> GovernedMemoryDisposition:
        occurred_at = now or datetime.now(UTC)
        existing = await self._repository.disposition(item.id, reason)
        if existing is not None:
            return existing
        item.status = status.value
        item.pinned = False
        item.state_version += 1
        item.updated_at = occurred_at
        receipt = hashlib.sha256(
            json.dumps(
                {
                    "memory_id": str(item.id),
                    "reason": reason,
                    "status": status.value,
                    "state_version": item.state_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        disposition = GovernedMemoryDisposition(
            **self._tenant(),
            id=uuid.uuid5(item.id, f"atlas.memory.disposition:{reason}"),
            memory_id=item.id,
            reason=reason,
            target_status=status.value,
            status="completed",
            receipt_digest=receipt,
            exception_code=None,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
        )
        await self._repository.add(disposition)
        await self._record(item, f"memory.item.{status.value}", occurred_at)
        return disposition

    async def _change(
        self, item: GovernedMemoryItem, event_type: str, now: datetime | None
    ) -> None:
        occurred_at = now or datetime.now(UTC)
        item.state_version += 1
        item.updated_at = occurred_at
        await self._record(item, event_type, occurred_at)

    async def _record(self, item: GovernedMemoryItem, event_type: str, now: datetime) -> None:
        await self._audit.write(
            AuditInput(
                action=event_type,
                target_type="governed_memory_item",
                target_id=item.id,
                outcome="success",
                details={"status": item.status, "state_version": item.state_version},
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=self._context.tenant.workspace_id,
                id=uuid.uuid4(),
                event_type=event_type,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="governed_memory_item",
                aggregate_id=item.id,
                aggregate_sequence=item.state_version,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification=item.classification,
                payload={"memory_id": str(item.id), "state_version": item.state_version},
                recorded_at=now,
                partition_key=now.strftime("%Y-%m"),
            )
        )
        await self._session.flush()

    async def _require_authorized(self, permission_key: str) -> None:
        if not await self._authorizer.authorize(self._context, permission_key):
            raise MemoryAuthorizationError("governed-memory operation is denied")
