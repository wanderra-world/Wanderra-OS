"""Authorized transactional H3-04 Knowledge Service and Timeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import AuthorizationRequest, AuthorizationService, DecisionEffect
from app.documents.contracts import Classification
from app.execution_context import ExecutionContext
from app.knowledge.contracts import (
    ClaimCreate,
    ClaimEvidence,
    ClaimStatus,
    ContradictionCreate,
    KnowledgeAuthorizationError,
    KnowledgeError,
    ReviewState,
    TimelineInput,
    checkpoint_digest,
    effective_classification,
    rebuild_timeline,
)
from app.knowledge.models import (
    KnowledgeClaim,
    KnowledgeEvidence,
    KnowledgeRelation,
    KnowledgeSourceDisposition,
    TimelineCheckpoint,
    TimelineEntry,
)
from app.knowledge.repository import KnowledgeRepository
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent


class KnowledgeAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class SourceDispositionJobPort(Protocol):
    async def enqueue_source_disposition(self, source_version_id: uuid.UUID) -> uuid.UUID: ...


class H1KnowledgeAuthorizer:
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


class KnowledgeService:
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: KnowledgeAuthorizer | None = None,
        disposition_jobs: SourceDispositionJobPort | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._authorizer = authorizer or H1KnowledgeAuthorizer(session)
        self._jobs = disposition_jobs
        self._repository = KnowledgeRepository(session, context)
        self._audit = AuditWriterService(session, context)

    def _tenant(self) -> dict[str, uuid.UUID]:
        return {
            "organization_id": self._context.tenant.organization_id,
            "workspace_id": self._context.tenant.workspace_id,
            "cell_id": self._context.tenant.cell_id,
        }

    async def create_claim(
        self,
        command: ClaimCreate,
        evidence: tuple[ClaimEvidence, ...],
        *,
        now: datetime | None = None,
    ) -> KnowledgeClaim:
        await self._require_authorized("update_content")
        if not evidence:
            raise KnowledgeError("a knowledge claim requires accessible evidence")
        derivation_digest = command.derivation_digest(evidence)
        subject = await self._repository.resource(command.subject_resource_id)
        if subject is None:
            raise KnowledgeError("claim subject resource does not exist")
        await self._repository.lock_identity("claim", command.identity_digest)
        existing = await self._repository.claim_by_digest(command.identity_digest)
        if existing is not None:
            if existing.derivation_digest != derivation_digest:
                raise KnowledgeError("claim identity replay changed derivation input")
            return existing
        sources: list[Classification] = []
        for item in evidence:
            version = await self._repository.version(item.source_version_id)
            if version is None or version.custody_status != "verified":
                raise KnowledgeError("claim evidence source is unavailable")
            expected_hash = version.content_hash
            if item.source_chunk_id is not None:
                chunk = await self._repository.chunk(item.source_chunk_id)
                if (
                    chunk is None
                    or chunk.source_version_id != version.id
                    or chunk.deleted_at is not None
                    or item.span_end > len(chunk.content)
                ):
                    raise KnowledgeError("claim source span is inaccessible")
                expected_hash = chunk.content_hash
            if item.source_hash != expected_hash:
                raise KnowledgeError("claim evidence hash does not match source custody")
            sources.extend((Classification(version.classification), item.classification))
        required = effective_classification(tuple(sources))
        if (
            effective_classification((required, command.classification))
            is not command.classification
        ):
            raise KnowledgeError("claim classification downgrade is prohibited")
        occurred_at = now or datetime.now(UTC)
        claim = KnowledgeClaim(
            **self._tenant(),
            id=command.claim_id,
            subject_resource_id=command.subject_resource_id,
            predicate=command.predicate,
            value_type=command.value_type.value,
            canonical_value=command.canonical_value,
            identity_digest=command.identity_digest,
            derivation_digest=derivation_digest,
            confidence_basis_points=round(command.confidence * 10_000),
            status=ClaimStatus.ACTIVE.value,
            review_state=ReviewState.PENDING.value,
            review_reason=None,
            reviewed_by_user_id=None,
            reviewed_at=None,
            extractor_key=command.extractor_key,
            extractor_version=command.extractor_version,
            classification=command.classification.value,
            policy_version=command.policy_version,
            valid_from=command.valid_from,
            valid_to=command.valid_to,
            state_version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        await self._repository.add(claim)
        for item in evidence:
            await self._repository.add(
                KnowledgeEvidence(
                    **self._tenant(),
                    id=item.evidence_id,
                    claim_id=claim.id,
                    source_version_id=item.source_version_id,
                    source_chunk_id=item.source_chunk_id,
                    source_hash=item.source_hash,
                    span_start=item.span_start,
                    span_end=item.span_end,
                    classification=item.classification.value,
                    policy_version=item.policy_version,
                    created_at=occurred_at,
                )
            )
        await self._record_claim(claim, "knowledge.claim.created", occurred_at)
        return claim

    async def relate_claims(
        self, command: ContradictionCreate, *, now: datetime | None = None
    ) -> KnowledgeRelation:
        await self._require_authorized("update_content")
        occurred_at = now or datetime.now(UTC)
        claim = await self._require_claim(command.claim_id, for_update=True)
        conflict = await self._require_claim(command.conflicting_claim_id, for_update=True)
        relation = KnowledgeRelation(
            **self._tenant(),
            id=command.relation_id,
            claim_id=claim.id,
            conflicting_claim_id=conflict.id,
            relation_type=command.relation_type,
            reason=command.reason,
            classification=effective_classification(
                (Classification(claim.classification), Classification(conflict.classification))
            ).value,
            policy_version=max(claim.policy_version, conflict.policy_version),
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
        )
        await self._repository.add(relation)
        if command.relation_type == "contradicts":
            await self._change_claim(
                claim, ClaimStatus.CONTRADICTED, "knowledge.claim.contradicted", occurred_at
            )
            await self._change_claim(
                conflict, ClaimStatus.CONTRADICTED, "knowledge.claim.contradicted", occurred_at
            )
        else:
            await self._change_claim(
                conflict, ClaimStatus.SUPERSEDED, "knowledge.claim.superseded", occurred_at
            )
        return relation

    async def review_claim(
        self,
        claim_id: uuid.UUID,
        *,
        state: ReviewState,
        reason: str,
        now: datetime | None = None,
    ) -> KnowledgeClaim:
        await self._require_authorized("update_content")
        normalized = reason.strip()
        if not normalized or len(normalized) > 256:
            raise KnowledgeError("review reason is invalid")
        claim = await self._require_claim(claim_id, for_update=True)
        claim.review_state = ReviewState(state).value
        occurred_at = now or datetime.now(UTC)
        claim.review_reason = normalized
        claim.reviewed_by_user_id = self._context.actor.actor_id
        claim.reviewed_at = occurred_at
        await self._change_claim(
            claim, ClaimStatus(claim.status), "knowledge.claim.reviewed", occurred_at
        )
        return claim

    async def claim(self, claim_id: uuid.UUID) -> KnowledgeClaim:
        await self._require_authorized("read_content")
        claim = await self._require_claim(claim_id)
        if claim.status == ClaimStatus.INVALIDATED.value:
            raise KnowledgeError("knowledge claim is invalidated")
        evidence = await self._repository.evidence_for_claim(claim.id)
        if not evidence:
            raise KnowledgeError("claim has no accessible evidence")
        for item in evidence:
            version = await self._repository.version(item.source_version_id)
            if version is None or version.custody_status != "verified":
                raise KnowledgeError("claim evidence is unavailable")
        return claim

    async def project_timeline(
        self,
        value: TimelineInput,
        *,
        projection_key: str = "workspace",
        projection_version: int = 1,
        now: datetime | None = None,
    ) -> TimelineEntry:
        await self._require_authorized("update_content")
        if projection_version < 1 or not projection_key.strip():
            raise KnowledgeError("timeline projection contract is invalid")
        if (
            value.resource_id is not None
            and await self._repository.resource(value.resource_id) is None
        ):
            raise KnowledgeError("timeline resource is unavailable")
        if value.source_claim_id is not None:
            claim = await self.claim(value.source_claim_id)
            if (
                effective_classification(
                    (Classification(claim.classification), value.classification)
                )
                is not value.classification
            ):
                raise KnowledgeError("timeline classification downgrade is prohibited")
        await self._repository.lock_identity("timeline", str(value.source_event_id))
        existing = await self._repository.timeline_by_source(value.source_event_id)
        if existing is not None:
            if self._timeline_digest(existing) != checkpoint_digest((value,)):
                raise KnowledgeError("timeline source replay changed input")
            existing.status = "active"
            existing.removed_at = None
            return existing
        occurred_at = now or datetime.now(UTC)
        entry = TimelineEntry(
            **self._tenant(),
            id=uuid.uuid5(value.source_event_id, "atlas.timeline.entry"),
            projection_key=projection_key.strip(),
            source_event_id=value.source_event_id,
            source_event_type=value.source_event_type,
            source_sequence=value.source_sequence,
            resource_id=value.resource_id,
            source_claim_id=value.source_claim_id,
            title=value.title,
            visibility=value.visibility,
            classification=value.classification.value,
            policy_version=value.policy_version,
            projection_version=projection_version,
            status="active",
            occurred_at=value.occurred_at,
            created_at=occurred_at,
            removed_at=None,
        )
        await self._repository.add(entry)
        await self._record_timeline(entry, "timeline.entry.projected", occurred_at)
        return entry

    async def rebuild_timeline(
        self,
        values: tuple[TimelineInput, ...],
        *,
        projection_key: str = "workspace",
        projection_version: int = 1,
        now: datetime | None = None,
    ) -> TimelineCheckpoint:
        ordered = rebuild_timeline(values)
        occurred_at = now or datetime.now(UTC)
        await self._repository.lock_identity("timeline-rebuild", projection_key)
        existing = await self._repository.timeline(projection_key, for_update=True)
        expected_ids = {value.source_event_id for value in ordered}
        for entry in existing:
            if entry.source_event_id not in expected_ids and entry.status == "active":
                entry.status = "removed"
                entry.removed_at = occurred_at
        for value in ordered:
            await self.project_timeline(
                value,
                projection_key=projection_key,
                projection_version=projection_version,
                now=occurred_at,
            )
        checksum = checkpoint_digest(ordered)
        checkpoint = await self._repository.checkpoint(projection_key, for_update=True)
        if checkpoint is None:
            checkpoint = TimelineCheckpoint(
                **self._tenant(),
                projection_key=projection_key,
                projection_version=projection_version,
                entry_count=len(ordered),
                checksum=checksum,
                last_occurred_at=ordered[-1].occurred_at if ordered else None,
                last_source_event_id=ordered[-1].source_event_id if ordered else None,
                built_at=occurred_at,
            )
            await self._repository.add(checkpoint)
        else:
            checkpoint.projection_version = projection_version
            checkpoint.entry_count = len(ordered)
            checkpoint.checksum = checksum
            checkpoint.last_occurred_at = ordered[-1].occurred_at if ordered else None
            checkpoint.last_source_event_id = ordered[-1].source_event_id if ordered else None
            checkpoint.built_at = occurred_at
        return checkpoint

    async def request_source_disposition(
        self, source_version_id: uuid.UUID, *, now: datetime | None = None
    ) -> KnowledgeSourceDisposition:
        await self._require_authorized("delete_content")
        if self._jobs is None:
            raise KnowledgeError("durable source disposition job port is unavailable")
        await self._repository.lock_identity("source-disposition", str(source_version_id))
        existing = await self._repository.disposition_by_source(source_version_id)
        if existing is not None:
            return existing
        if await self._repository.version(source_version_id) is None:
            raise KnowledgeError("source version does not exist")
        occurred_at = now or datetime.now(UTC)
        disposition = KnowledgeSourceDisposition(
            **self._tenant(),
            id=uuid.uuid5(
                source_version_id,
                f"atlas.knowledge.disposition:{self._context.tenant.workspace_id}",
            ),
            source_version_id=source_version_id,
            status="pending",
            job_id=None,
            exception_code=None,
            requested_by_user_id=self._context.actor.actor_id,
            requested_at=occurred_at,
            completed_at=None,
        )
        await self._repository.add(disposition)
        disposition.job_id = await self._jobs.enqueue_source_disposition(source_version_id)
        await self._record_disposition(
            disposition, 1, "knowledge.source_disposition.requested", occurred_at
        )
        return disposition

    async def process_source_disposition(
        self, disposition_id: uuid.UUID, *, now: datetime | None = None
    ) -> KnowledgeSourceDisposition:
        await self._require_authorized("delete_content")
        occurred_at = now or datetime.now(UTC)
        disposition = await self._repository.disposition(disposition_id, for_update=True)
        if disposition is None:
            raise KnowledgeError("source disposition does not exist")
        if disposition.status == "completed":
            return disposition
        claims = await self._repository.claims_for_source(disposition.source_version_id)
        for claim in claims:
            if claim.status != ClaimStatus.INVALIDATED.value:
                await self._change_claim(
                    claim, ClaimStatus.INVALIDATED, "knowledge.claim.invalidated", occurred_at
                )
        for entry in await self._repository.timeline_for_claims(
            tuple(value.id for value in claims)
        ):
            entry.status = "removed"
            entry.removed_at = occurred_at
        disposition.status = "completed"
        disposition.exception_code = None
        disposition.completed_at = occurred_at
        await self._record_disposition(
            disposition, 2, "knowledge.source_disposition.completed", occurred_at
        )
        return disposition

    async def export_manifest(self) -> dict[str, object]:
        await self._require_authorized("export_workspace")
        claims, evidence, relations, dispositions = await self._repository.export_rows()
        timeline = await self._repository.timeline("workspace")
        checkpoint = await self._repository.checkpoint("workspace")
        return {
            "workspace_id": str(self._context.tenant.workspace_id),
            "claims": [
                {
                    "claim_id": str(value.id),
                    "subject_resource_id": str(value.subject_resource_id),
                    "predicate": value.predicate,
                    "value_type": value.value_type,
                    "canonical_value": value.canonical_value,
                    "identity_digest": value.identity_digest,
                    "derivation_digest": value.derivation_digest,
                    "confidence_basis_points": value.confidence_basis_points,
                    "status": value.status,
                    "review_state": value.review_state,
                    "extractor_key": value.extractor_key,
                    "extractor_version": value.extractor_version,
                    "classification": value.classification,
                    "policy_version": value.policy_version,
                }
                for value in claims
            ],
            "evidence": [
                {
                    "evidence_id": str(value.id),
                    "claim_id": str(value.claim_id),
                    "source_version_id": str(value.source_version_id),
                    "source_chunk_id": str(value.source_chunk_id)
                    if value.source_chunk_id
                    else None,
                    "source_hash": value.source_hash,
                    "span_start": value.span_start,
                    "span_end": value.span_end,
                    "classification": value.classification,
                    "policy_version": value.policy_version,
                }
                for value in evidence
            ],
            "relations": [
                {
                    "relation_id": str(value.id),
                    "claim_id": str(value.claim_id),
                    "conflicting_claim_id": str(value.conflicting_claim_id),
                    "relation_type": value.relation_type,
                    "classification": value.classification,
                    "policy_version": value.policy_version,
                }
                for value in relations
            ],
            "source_dispositions": [
                {
                    "disposition_id": str(value.id),
                    "source_version_id": str(value.source_version_id),
                    "status": value.status,
                    "exception_code": value.exception_code,
                }
                for value in dispositions
            ],
            "timeline": [
                {
                    "entry_id": str(value.id),
                    "source_event_id": str(value.source_event_id),
                    "source_claim_id": str(value.source_claim_id)
                    if value.source_claim_id
                    else None,
                    "status": value.status,
                    "classification": value.classification,
                    "policy_version": value.policy_version,
                }
                for value in timeline
            ],
            "timeline_checkpoint": (
                {
                    "projection_version": checkpoint.projection_version,
                    "entry_count": checkpoint.entry_count,
                    "checksum": checkpoint.checksum,
                }
                if checkpoint
                else None
            ),
        }

    async def _require_claim(
        self, claim_id: uuid.UUID, *, for_update: bool = False
    ) -> KnowledgeClaim:
        value = await self._repository.claim(claim_id, for_update=for_update)
        if value is None:
            raise KnowledgeError("knowledge claim does not exist")
        return value

    async def _require_authorized(self, permission_key: str) -> None:
        if not await self._authorizer.authorize(self._context, permission_key):
            raise KnowledgeAuthorizationError("knowledge operation is denied")

    async def _change_claim(
        self,
        claim: KnowledgeClaim,
        status: ClaimStatus,
        event_type: str,
        now: datetime,
    ) -> None:
        claim.status = status.value
        claim.state_version += 1
        claim.updated_at = now
        await self._record_claim(claim, event_type, now)

    async def _record_claim(self, claim: KnowledgeClaim, event_type: str, now: datetime) -> None:
        await self._audit.write(
            AuditInput(
                action=event_type,
                target_type="knowledge_claim",
                target_id=claim.id,
                outcome="success",
                details={"state_version": claim.state_version, "status": claim.status},
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
                aggregate_type="knowledge_claim",
                aggregate_id=claim.id,
                aggregate_sequence=claim.state_version,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification=claim.classification,
                payload={"claim_id": str(claim.id), "state_version": claim.state_version},
                recorded_at=now,
                partition_key=now.strftime("%Y-%m"),
            )
        )
        await self._session.flush()

    async def _record_timeline(self, entry: TimelineEntry, event_type: str, now: datetime) -> None:
        await self._audit.write(
            AuditInput(
                action=event_type,
                target_type="timeline_entry",
                target_id=entry.id,
                outcome="success",
                details={"source_event_id": str(entry.source_event_id)},
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
                aggregate_type="timeline_entry",
                aggregate_id=entry.id,
                aggregate_sequence=1,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification=entry.classification,
                payload={"entry_id": str(entry.id), "source_event_id": str(entry.source_event_id)},
                recorded_at=now,
                partition_key=now.strftime("%Y-%m"),
            )
        )
        await self._session.flush()

    async def _record_disposition(
        self,
        disposition: KnowledgeSourceDisposition,
        sequence: int,
        event_type: str,
        now: datetime,
    ) -> None:
        await self._audit.write(
            AuditInput(
                action=event_type,
                target_type="knowledge_source_disposition",
                target_id=disposition.id,
                outcome="success",
                details={
                    "status": disposition.status,
                    "source_version_id": str(disposition.source_version_id),
                },
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
                aggregate_type="knowledge_source_disposition",
                aggregate_id=disposition.id,
                aggregate_sequence=sequence,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="internal",
                payload={"disposition_id": str(disposition.id), "status": disposition.status},
                recorded_at=now,
                partition_key=now.strftime("%Y-%m"),
            )
        )
        await self._session.flush()

    @staticmethod
    def _timeline_digest(entry: TimelineEntry) -> str:
        return checkpoint_digest(
            (
                TimelineInput(
                    source_event_id=entry.source_event_id,
                    source_event_type=entry.source_event_type,
                    source_sequence=entry.source_sequence,
                    occurred_at=entry.occurred_at,
                    resource_id=entry.resource_id,
                    source_claim_id=entry.source_claim_id,
                    title=entry.title,
                    visibility=entry.visibility,
                    classification=Classification(entry.classification),
                    policy_version=entry.policy_version,
                ),
            )
        )
