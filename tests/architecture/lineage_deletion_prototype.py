"""Disposable H0 prototype for derivative lineage and governed erasure."""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class LineageError(ValueError):
    """Raised when lineage or deletion governance would be violated."""


class ArtifactKind(StrEnum):
    PROVIDER_MIRROR = "provider_mirror"
    RAW_PAYLOAD = "raw_payload"
    DOCUMENT_VERSION = "document_version"
    DOCUMENT_CHUNK = "document_chunk"
    EXTRACTED_CLAIM = "extracted_claim"
    TIMELINE_PROJECTION = "timeline_projection"
    SEARCH_PROJECTION = "search_projection"
    EMBEDDING = "embedding"
    MEMORY = "memory"
    NOTE = "note"
    CACHE = "cache"
    EXPORT = "export"
    BACKUP = "backup"


class ArtifactState(StrEnum):
    ACTIVE = "active"
    TOMBSTONED = "tombstoned"
    RETAINED = "retained"
    DELETED = "deleted"


class BackupDisposition(StrEnum):
    SCHEDULED_EXPIRY = "scheduled_expiry"
    KEY_ERASURE = "key_erasure"


@dataclass(frozen=True, slots=True)
class Governance:
    legal_hold: bool = False
    statutory_retain_until: datetime | None = None
    security_preserve_until: datetime | None = None
    security_preservation_approved: bool = False
    workspace_retain_until: datetime | None = None
    provider_delete_required: bool = False
    backup_disposition: BackupDisposition | None = None

    def retention_reason(self, *, now: datetime) -> str | None:
        if self.legal_hold:
            return "legal_hold"
        if (
            self.statutory_retain_until is not None
            and now < self.statutory_retain_until
        ):
            return "statutory_or_contractual_minimum"
        if (
            self.security_preservation_approved
            and self.security_preserve_until is not None
            and now < self.security_preserve_until
        ):
            return "approved_security_preservation"
        if (
            self.workspace_retain_until is not None
            and now < self.workspace_retain_until
        ):
            return "workspace_policy"
        return None


@dataclass(frozen=True, slots=True)
class Artifact:
    id: UUID
    workspace_id: UUID
    kind: ArtifactKind
    direct_sources: tuple[UUID, ...]
    created_at: datetime
    policy_version: str
    classification_version: str
    content_hash: str | None
    governance: Governance
    derivation_type: str | None = None
    tool_or_model_version: str | None = None
    state: ArtifactState = ArtifactState.ACTIVE

    def __post_init__(self) -> None:
        if not self.policy_version.strip() or not self.classification_version.strip():
            raise LineageError("policy and classification versions are required")
        if self.direct_sources and (
            not self.derivation_type
            or not self.tool_or_model_version
        ):
            raise LineageError(
                "derivatives require derivation type and tool or model version"
            )


class LineageGraph:
    """Workspace-scoped DAG of original sources and all governed derivatives."""

    def __init__(self) -> None:
        self._artifacts: dict[UUID, Artifact] = {}

    def add(self, artifact: Artifact) -> None:
        if artifact.id in self._artifacts:
            raise LineageError("artifact identifier already exists")
        for source_id in artifact.direct_sources:
            source = self.get(source_id)
            if source.workspace_id != artifact.workspace_id:
                raise LineageError("cross-workspace lineage is prohibited")
            if source.state is not ArtifactState.ACTIVE:
                raise LineageError("tombstoned source cannot produce a new derivative")
        self._artifacts[artifact.id] = artifact

    def get(self, artifact_id: UUID) -> Artifact:
        try:
            return self._artifacts[artifact_id]
        except KeyError as error:
            raise LineageError("artifact does not exist") from error

    def save(self, artifact: Artifact) -> None:
        if artifact.id not in self._artifacts:
            raise LineageError("artifact does not exist")
        self._artifacts[artifact.id] = artifact

    def deletion_scope(self, root_id: UUID) -> tuple[Artifact, ...]:
        root = self.get(root_id)
        selected: list[Artifact] = []
        seen: set[UUID] = set()
        pending = deque((root.id,))
        while pending:
            artifact_id = pending.popleft()
            if artifact_id in seen:
                continue
            seen.add(artifact_id)
            selected.append(self.get(artifact_id))
            pending.extend(
                artifact.id
                for artifact in self._artifacts.values()
                if artifact_id in artifact.direct_sources
            )
        return tuple(selected)

    def read(self, artifact_id: UUID) -> Artifact:
        artifact = self.get(artifact_id)
        if artifact.state is not ArtifactState.ACTIVE:
            raise LineageError("artifact is unavailable for ordinary access")
        return artifact


@dataclass(frozen=True, slots=True)
class ErasureRequest:
    workspace_id: UUID
    root_artifact_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RetainedException:
    artifact_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class DeletionReceipt:
    receipt_id: UUID
    request_key: str
    root_artifact_id: UUID
    deleted_ids: tuple[UUID, ...]
    retained: tuple[RetainedException, ...]
    invalidated_projection_ids: tuple[UUID, ...]
    verified_provider_ids: tuple[UUID, ...]
    backup_expiry_ids: tuple[UUID, ...]
    completed_at: datetime
    verification_hash: str


@dataclass(frozen=True, slots=True)
class MinimalAuditEvidence:
    receipt_id: UUID
    workspace_id: UUID
    root_artifact_id: UUID
    completed_at: datetime
    verification_hash: str


class MockProviderDeletion:
    """Records provider deletion verification without retaining provider payloads."""

    def __init__(self, *, verification_succeeds: bool = True) -> None:
        self.verification_succeeds = verification_succeeds
        self.calls: list[UUID] = []

    def delete_and_verify(self, artifact_id: UUID) -> bool:
        self.calls.append(artifact_id)
        return self.verification_succeeds


class ErasureWorkflow:
    """Idempotent lineage traversal with policy and external-action verification."""

    PROJECTION_KINDS = frozenset(
        {
            ArtifactKind.TIMELINE_PROJECTION,
            ArtifactKind.SEARCH_PROJECTION,
            ArtifactKind.EMBEDDING,
            ArtifactKind.CACHE,
        }
    )

    def __init__(
        self,
        graph: LineageGraph,
        provider_deletion: MockProviderDeletion,
    ) -> None:
        self._graph = graph
        self._provider_deletion = provider_deletion
        self._outcomes: dict[str, tuple[tuple[UUID, UUID], DeletionReceipt]] = {}
        self.audit_evidence: list[MinimalAuditEvidence] = []

    def execute(self, request: ErasureRequest, *, now: datetime) -> DeletionReceipt:
        if not request.idempotency_key.strip():
            raise LineageError("erasure request requires an idempotency key")
        fingerprint = (request.workspace_id, request.root_artifact_id)
        prior = self._outcomes.get(request.idempotency_key)
        if prior is not None:
            if prior[0] != fingerprint:
                raise LineageError("idempotency key was reused with changed scope")
            return prior[1]

        scope = self._graph.deletion_scope(request.root_artifact_id)
        if any(artifact.workspace_id != request.workspace_id for artifact in scope):
            raise LineageError("erasure scope does not belong to workspace")

        for artifact in scope:
            if artifact.state is ArtifactState.ACTIVE:
                self._graph.save(replace(artifact, state=ArtifactState.TOMBSTONED))

        deleted: list[UUID] = []
        retained: list[RetainedException] = []
        invalidated: list[UUID] = []
        verified_provider: list[UUID] = []
        backup_expiry: list[UUID] = []

        for scoped_artifact in scope:
            artifact = self._graph.get(scoped_artifact.id)
            retention_reason = artifact.governance.retention_reason(now=now)
            if retention_reason is not None:
                self._graph.save(replace(artifact, state=ArtifactState.RETAINED))
                retained.append(RetainedException(artifact.id, retention_reason))
                continue
            if artifact.governance.provider_delete_required:
                if not self._provider_deletion.delete_and_verify(artifact.id):
                    self._graph.save(replace(artifact, state=ArtifactState.RETAINED))
                    retained.append(
                        RetainedException(artifact.id, "provider_action_unverified")
                    )
                    continue
                verified_provider.append(artifact.id)
            if artifact.kind is ArtifactKind.BACKUP:
                disposition = artifact.governance.backup_disposition
                if disposition is None:
                    self._graph.save(replace(artifact, state=ArtifactState.RETAINED))
                    retained.append(
                        RetainedException(artifact.id, "backup_policy_missing")
                    )
                    continue
                if disposition is BackupDisposition.SCHEDULED_EXPIRY:
                    self._graph.save(replace(artifact, state=ArtifactState.RETAINED))
                    backup_expiry.append(artifact.id)
                    retained.append(
                        RetainedException(artifact.id, "backup_scheduled_expiry")
                    )
                    continue
            self._graph.save(replace(artifact, state=ArtifactState.DELETED))
            deleted.append(artifact.id)
            if artifact.kind in self.PROJECTION_KINDS:
                invalidated.append(artifact.id)

        verification_hash = self._receipt_hash(
            request=request,
            deleted=deleted,
            retained=retained,
        )
        receipt = DeletionReceipt(
            receipt_id=uuid4(),
            request_key=request.idempotency_key,
            root_artifact_id=request.root_artifact_id,
            deleted_ids=tuple(deleted),
            retained=tuple(retained),
            invalidated_projection_ids=tuple(invalidated),
            verified_provider_ids=tuple(verified_provider),
            backup_expiry_ids=tuple(backup_expiry),
            completed_at=now,
            verification_hash=verification_hash,
        )
        self._outcomes[request.idempotency_key] = (fingerprint, receipt)
        self.audit_evidence.append(
            MinimalAuditEvidence(
                receipt_id=receipt.receipt_id,
                workspace_id=request.workspace_id,
                root_artifact_id=request.root_artifact_id,
                completed_at=now,
                verification_hash=verification_hash,
            )
        )
        return receipt

    @staticmethod
    def _receipt_hash(
        *,
        request: ErasureRequest,
        deleted: list[UUID],
        retained: list[RetainedException],
    ) -> str:
        evidence = "|".join(
            (
                str(request.workspace_id),
                str(request.root_artifact_id),
                *sorted(str(artifact_id) for artifact_id in deleted),
                *sorted(
                    f"{exception.artifact_id}:{exception.reason}"
                    for exception in retained
                ),
            )
        )
        return hashlib.sha256(evidence.encode()).hexdigest()
