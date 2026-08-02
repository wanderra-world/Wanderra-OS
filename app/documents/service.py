"""Authorized transactional H3-03 document custody and derivation service."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import AuthorizationRequest, AuthorizationService, DecisionEffect
from app.documents.contracts import (
    Classification,
    ContentVerifierPort,
    CustodyError,
    CustodyStatus,
    DeletionDisposition,
    DeletionJobPort,
    DocumentAuthorizationError,
    DocumentCreate,
    DocumentVersionCreate,
    ExtractionJobPort,
    ExtractionRequest,
    ExtractorPort,
    MalwareVerdict,
    ObjectStoragePort,
    build_chunks,
    deletion_disposition,
    derivative_digest,
    require_derivative_classification,
    require_extractable,
)
from app.documents.models import (
    Document,
    DocumentChunk,
    DocumentDeletion,
    DocumentDerivative,
    DocumentVersion,
)
from app.documents.repository import DocumentRepository
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent


class DocumentAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class H1DocumentAuthorizer:
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


class DocumentService:
    """Manage document state inside the caller-owned execution-context transaction."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        object_storage: ObjectStoragePort,
        authorizer: DocumentAuthorizer | None = None,
        extraction_jobs: ExtractionJobPort | None = None,
        deletion_jobs: DeletionJobPort | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._storage = object_storage
        self._authorizer = authorizer or H1DocumentAuthorizer(session)
        self._extraction_jobs = extraction_jobs
        self._deletion_jobs = deletion_jobs
        self._repository = DocumentRepository(session, context)
        self._audit = AuditWriterService(session, context)

    def _tenant(self) -> dict[str, uuid.UUID]:
        return {
            "organization_id": self._context.tenant.organization_id,
            "workspace_id": self._context.tenant.workspace_id,
            "cell_id": self._context.tenant.cell_id,
        }

    async def create(self, command: DocumentCreate, *, now: datetime | None = None) -> Document:
        await self._require_authorized("update_content")
        resource = await self._repository.resource(command.resource_id)
        if resource is None or resource.resource_type != "document":
            raise CustodyError("document requires an active typed document resource")
        if await self._repository.document(command.document_id) is not None:
            raise CustodyError("document identity already exists")
        occurred_at = now or datetime.now(UTC)
        value = Document(
            **self._tenant(),
            id=command.document_id,
            resource_id=command.resource_id,
            title=command.title,
            status="active",
            classification=command.classification.value,
            classification_policy_version=command.classification_policy_version,
            legal_hold=command.legal_hold,
            retain_until=command.retain_until,
            state_version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        await self._repository.add(value)
        await self._record(value.id, value.state_version, "document.created", occurred_at)
        return value

    async def ingest(
        self, command: DocumentVersionCreate, *, now: datetime | None = None
    ) -> DocumentVersion:
        await self._require_authorized("update_content")
        document = await self._require_document(command.document_id, for_update=True)
        if document.status != "active":
            raise CustodyError("deleted document cannot accept a version")
        require_derivative_classification(
            source=Classification(document.classification),
            derivative=command.classification,
        )
        occurred_at = now or datetime.now(UTC)
        quarantine_key = self._object_key(command.version_id, command.sha256, quarantine=True)
        object_key = self._object_key(command.version_id, command.sha256, quarantine=False)
        await self._storage.put_quarantined(quarantine_key, command.content)
        value = DocumentVersion(
            **self._tenant(),
            id=command.version_id,
            document_id=document.id,
            version_number=await self._repository.next_version_number(document.id),
            content_hash=command.sha256,
            size_bytes=command.size_bytes,
            media_type=command.media_type,
            quarantine_key=quarantine_key,
            object_key=object_key,
            custody_status=CustodyStatus.QUARANTINED.value,
            malware_verdict=MalwareVerdict.PENDING.value,
            media_type_verified=False,
            classification=command.classification.value,
            classification_policy_version=command.classification_policy_version,
            encryption_key_version=command.encryption_key_version,
            source_external_reference_id=command.source_external_reference_id,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
        )
        await self._repository.add(value)
        document.state_version += 1
        document.updated_at = occurred_at
        await self._record(
            document.id, document.state_version, "document.version_quarantined", occurred_at
        )
        return value

    async def verify(
        self,
        version_id: uuid.UUID,
        *,
        verifier: ContentVerifierPort,
        now: datetime | None = None,
    ) -> DocumentVersion:
        await self._require_authorized("update_content")
        version = await self._require_version(version_id, for_update=True)
        if version.custody_status != CustodyStatus.QUARANTINED.value:
            raise CustodyError("only quarantined content can be verified")
        content = await self._storage.read(version.quarantine_key)
        occurred_at = now or datetime.now(UTC)
        if hashlib.sha256(content).hexdigest() != version.content_hash:
            version.custody_status = CustodyStatus.REJECTED.value
            version.malware_verdict = MalwareVerdict.ERROR.value
            version.media_type_verified = False
            version.verifier_version = "custody-hash/1"
            version.verified_at = occurred_at
            document = await self._require_document(version.document_id, for_update=True)
            await self._changed(document, "document.version_rejected", occurred_at)
            return version
        evidence = await verifier.verify(content, version.media_type)
        occurred_at = now or evidence.verified_at
        version.malware_verdict = evidence.malware_verdict.value
        version.media_type_verified = evidence.media_type_verified
        version.verifier_version = evidence.verifier_version
        version.verified_at = evidence.verified_at
        try:
            require_extractable(evidence, expected_hash=version.content_hash)
        except CustodyError:
            version.custody_status = CustodyStatus.REJECTED.value
            document = await self._require_document(version.document_id, for_update=True)
            await self._changed(document, "document.version_rejected", occurred_at)
            return version
        await self._storage.promote(version.quarantine_key, version.object_key)
        version.custody_status = CustodyStatus.VERIFIED.value
        document = await self._require_document(version.document_id, for_update=True)
        await self._changed(document, "document.version_verified", occurred_at)
        return version

    async def request_extraction(self, request: ExtractionRequest) -> uuid.UUID:
        await self._require_authorized("update_content")
        version = await self._require_version(request.version_id)
        self._require_verified(version)
        require_derivative_classification(
            source=Classification(version.classification),
            derivative=request.classification,
        )
        if self._extraction_jobs is None:
            raise CustodyError("durable extraction job port is unavailable")
        digest = derivative_digest(
            source_hash=version.content_hash,
            processor_key=request.processor_key,
            processor_version=request.processor_version,
            policy_version=request.policy_version,
        )
        return await self._extraction_jobs.enqueue_extraction(version.id, digest)

    async def complete_extraction(
        self,
        request: ExtractionRequest,
        *,
        extractor: ExtractorPort,
        extraction_job_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> DocumentDerivative:
        await self._require_authorized("update_content")
        version = await self._require_version(request.version_id, for_update=True)
        self._require_verified(version)
        require_derivative_classification(
            source=Classification(version.classification),
            derivative=request.classification,
        )
        input_digest = derivative_digest(
            source_hash=version.content_hash,
            processor_key=request.processor_key,
            processor_version=request.processor_version,
            policy_version=request.policy_version,
        )
        existing = await self._repository.derivative_by_input(version.id, input_digest)
        if existing is not None:
            return existing
        content = await self._storage.read(version.object_key)
        if hashlib.sha256(content).hexdigest() != version.content_hash:
            raise CustodyError("verified object substitution detected")
        texts = await extractor.extract(content, version.media_type)
        chunks = build_chunks(
            source_version_id=version.id,
            derivative_id=request.derivative_id,
            texts=texts,
            classification=request.classification,
            policy_version=request.policy_version,
        )
        if not chunks:
            raise CustodyError("extractor produced no governed chunks")
        content_hash = hashlib.sha256(
            "\n".join(chunk.text for chunk in chunks).encode()
        ).hexdigest()
        occurred_at = now or datetime.now(UTC)
        derivative = DocumentDerivative(
            **self._tenant(),
            id=request.derivative_id,
            source_version_id=version.id,
            derivative_kind="text_chunks",
            processor_key=request.processor_key,
            processor_version=request.processor_version,
            input_digest=input_digest,
            content_hash=content_hash,
            object_key=None,
            status="verified",
            classification=request.classification.value,
            policy_version=request.policy_version,
            extraction_job_id=extraction_job_id,
            created_at=occurred_at,
        )
        await self._repository.add(derivative)
        for chunk in chunks:
            await self._repository.add(
                DocumentChunk(
                    **self._tenant(),
                    id=chunk.chunk_id,
                    source_version_id=chunk.source_version_id,
                    derivative_id=chunk.derivative_id,
                    position=chunk.position,
                    content=chunk.text,
                    content_hash=chunk.content_hash,
                    classification=chunk.classification.value,
                    policy_version=chunk.policy_version,
                    created_at=occurred_at,
                )
            )
        document = await self._require_document(version.document_id, for_update=True)
        await self._changed(document, "document.derivative_created", occurred_at)
        return derivative

    async def delete(
        self, document_id: uuid.UUID, *, reason: str, now: datetime | None = None
    ) -> DocumentDeletion:
        await self._require_authorized("delete_content")
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 256:
            raise CustodyError("deletion reason is invalid")
        occurred_at = now or datetime.now(UTC)
        document = await self._require_document(document_id, for_update=True)
        disposition = deletion_disposition(
            now=occurred_at,
            legal_hold=document.legal_hold,
            retain_until=document.retain_until,
        )
        deletion = DocumentDeletion(
            **self._tenant(),
            id=uuid.uuid4(),
            document_id=document.id,
            status="blocked" if disposition is not DeletionDisposition.ELIGIBLE else "pending",
            disposition=disposition.value,
            reason=normalized_reason,
            exception_code=None,
            deletion_job_id=None,
            requested_by_user_id=self._context.actor.actor_id,
            requested_at=occurred_at,
            completed_at=None,
        )
        if disposition is not DeletionDisposition.ELIGIBLE:
            await self._repository.add(deletion)
            await self._changed(
                document,
                "document.deletion_blocked",
                occurred_at,
                details={"reason": normalized_reason, "disposition": disposition.value},
            )
            return deletion
        if self._deletion_jobs is None:
            raise CustodyError("durable deletion job port is unavailable")
        await self._repository.add(deletion)
        deletion.deletion_job_id = await self._deletion_jobs.enqueue_deletion(
            deletion.id, document.id
        )
        await self._changed(
            document,
            "document.deletion_requested",
            occurred_at,
            details={"reason": normalized_reason},
        )
        return deletion

    async def process_deletion(
        self, deletion_id: uuid.UUID, *, now: datetime | None = None
    ) -> DocumentDeletion:
        """Idempotently propagate one committed deletion request across owned targets."""
        await self._require_authorized("delete_content")
        occurred_at = now or datetime.now(UTC)
        deletion = await self._repository.deletion(deletion_id, for_update=True)
        if deletion is None:
            raise CustodyError("document deletion request does not exist")
        if deletion.status == "completed":
            return deletion
        if deletion.status not in {"pending", "exception"}:
            raise CustodyError("blocked deletion cannot be processed")
        document = await self._require_document(deletion.document_id, for_update=True)
        current = deletion_disposition(
            now=occurred_at,
            legal_hold=document.legal_hold,
            retain_until=document.retain_until,
        )
        if current is not DeletionDisposition.ELIGIBLE:
            deletion.status = "blocked"
            deletion.disposition = current.value
            deletion.exception_code = None
            await self._changed(
                document,
                "document.deletion_blocked",
                occurred_at,
                details={"reason": deletion.reason, "disposition": current.value},
            )
            return deletion
        versions = await self._repository.versions(document.id)
        derivatives = await self._repository.derivatives(tuple(version.id for version in versions))
        chunks = await self._repository.chunks(tuple(value.id for value in derivatives))
        try:
            for derivative in derivatives:
                if derivative.object_key is not None:
                    await self._storage.delete(derivative.object_key)
            for version in versions:
                key = (
                    version.object_key
                    if version.custody_status == "verified"
                    else version.quarantine_key
                )
                await self._storage.delete(key)
        except Exception:
            deletion.status = "exception"
            deletion.exception_code = "object_delete_failed"
            await self._changed(
                document,
                "document.deletion_exception",
                occurred_at,
                details={"reason": deletion.reason, "exception_code": deletion.exception_code},
            )
            return deletion
        for chunk in chunks:
            chunk.deleted_at = occurred_at
            chunk.content = ""
        for derivative in derivatives:
            derivative.status = "deleted"
            derivative.deleted_at = occurred_at
        for version in versions:
            version.custody_status = "deleted"
            version.deleted_at = occurred_at
        document.status = "deleted"
        document.deleted_at = occurred_at
        document.updated_at = occurred_at
        deletion.status = "completed"
        deletion.exception_code = None
        deletion.completed_at = occurred_at
        await self._changed(
            document,
            "document.deleted",
            occurred_at,
            details={"reason": deletion.reason},
        )
        return deletion

    async def set_governance(
        self,
        document_id: uuid.UUID,
        *,
        legal_hold: bool,
        retain_until: datetime | None,
        reason: str,
        now: datetime | None = None,
    ) -> Document:
        """Apply an authorized hold/retention decision without broadening read access."""
        await self._require_authorized("manage_workspace")
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 256:
            raise CustodyError("governance reason is invalid")
        if retain_until is not None and (
            retain_until.tzinfo is None or retain_until.utcoffset() is None
        ):
            raise CustodyError("retain_until must be timezone-aware")
        occurred_at = now or datetime.now(UTC)
        document = await self._require_document(document_id, for_update=True)
        if document.status != "active":
            raise CustodyError("deleted document governance cannot be changed")
        document.legal_hold = legal_hold
        document.retain_until = retain_until
        await self._changed(
            document,
            "document.governance_changed",
            occurred_at,
            details={"reason": normalized_reason},
        )
        return document

    async def export_manifest(self, document_id: uuid.UUID) -> dict[str, object]:
        await self._require_authorized("export_workspace")
        document = await self._require_document(document_id)
        versions = await self._repository.versions(document.id)
        derivatives = await self._repository.derivatives(tuple(value.id for value in versions))
        deletions = await self._repository.document_deletions(document.id)
        return {
            "document_id": str(document.id),
            "resource_id": str(document.resource_id),
            "classification": document.classification,
            "classification_policy_version": document.classification_policy_version,
            "legal_hold": document.legal_hold,
            "retain_until": document.retain_until.isoformat() if document.retain_until else None,
            "versions": [
                {
                    "version_id": str(version.id),
                    "content_hash": version.content_hash,
                    "custody_status": version.custody_status,
                    "object_key": version.object_key,
                    "encryption_key_version": version.encryption_key_version,
                }
                for version in versions
            ],
            "derivatives": [
                {
                    "derivative_id": str(derivative.id),
                    "source_version_id": str(derivative.source_version_id),
                    "input_digest": derivative.input_digest,
                    "content_hash": derivative.content_hash,
                    "processor_key": derivative.processor_key,
                    "processor_version": derivative.processor_version,
                    "classification": derivative.classification,
                    "policy_version": derivative.policy_version,
                    "status": derivative.status,
                }
                for derivative in derivatives
            ],
            "deletion_exceptions": [
                {
                    "deletion_id": str(deletion.id),
                    "status": deletion.status,
                    "disposition": deletion.disposition,
                    "exception_code": deletion.exception_code,
                }
                for deletion in deletions
                if deletion.status in {"blocked", "exception"}
            ],
        }

    async def verify_restore(self, version_id: uuid.UUID) -> bool:
        await self._require_authorized("read_content")
        version = await self._require_version(version_id)
        if version.custody_status != "verified":
            return False
        content = await self._storage.read(version.object_key)
        return hashlib.sha256(content).hexdigest() == version.content_hash

    async def _require_document(
        self, document_id: uuid.UUID, *, for_update: bool = False
    ) -> Document:
        value = await self._repository.document(document_id, for_update=for_update)
        if value is None:
            raise CustodyError("document does not exist")
        return value

    async def _require_version(
        self, version_id: uuid.UUID, *, for_update: bool = False
    ) -> DocumentVersion:
        value = await self._repository.version(version_id, for_update=for_update)
        if value is None:
            raise CustodyError("document version does not exist")
        return value

    @staticmethod
    def _require_verified(version: DocumentVersion) -> None:
        if version.custody_status != CustodyStatus.VERIFIED.value:
            raise CustodyError("unverified content cannot enter extraction")

    async def _require_authorized(self, permission_key: str) -> None:
        if not await self._authorizer.authorize(self._context, permission_key):
            raise DocumentAuthorizationError("document operation is denied")

    def _object_key(self, version_id: uuid.UUID, digest: str, *, quarantine: bool) -> str:
        prefix = "quarantine" if quarantine else "documents"
        return (
            f"{prefix}/{self._context.tenant.organization_id}/"
            f"{self._context.tenant.workspace_id}/{version_id}/{digest}"
        )

    async def _record(
        self,
        document_id: uuid.UUID,
        sequence: int,
        event_type: str,
        now: datetime,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        safe_details = {"state_version": sequence, **(details or {})}
        await self._audit.write(
            AuditInput(
                action=event_type,
                target_type="document",
                target_id=document_id,
                outcome="success",
                details=safe_details,
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
                aggregate_type="document",
                aggregate_id=document_id,
                aggregate_sequence=sequence,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="internal",
                payload={"document_id": str(document_id), "state_version": sequence},
                recorded_at=now,
                partition_key=now.strftime("%Y-%m"),
            )
        )
        await self._session.flush()

    async def _changed(
        self,
        document: Document,
        event_type: str,
        now: datetime,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        document.state_version += 1
        document.updated_at = now
        await self._record(
            document.id,
            document.state_version,
            event_type,
            now,
            details=details,
        )
