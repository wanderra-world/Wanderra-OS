"""Workspace export, recovery evidence, and closure lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar_capability.models import CalendarCapabilityRoute
from app.connection_credentials.models import ConnectionCredential
from app.connections.models import Connection
from app.email_capability.models import EmailCapabilityRoute
from app.encryption.models import EncryptedEnvelope
from app.execution_context import ExecutionContext
from app.identity.lifecycle_models import (
    IdentityLifecycleToken,
    IdentitySession,
    SecurityNotification,
)
from app.memberships.models import WorkspaceMembership
from app.messaging.models import (
    AggregateVersion,
    CommandIdempotency,
    ConsumerSequence,
    EventQuarantine,
    InboxEvent,
)
from app.messaging.service import AuditInput, AuditWriterService
from app.recovery.contracts import (
    BackupArtifact,
    ClosureResult,
    ClosureState,
    RestoreEvidence,
    WorkspaceManifest,
)
from app.recovery.models import RecoveryEvidence, WorkspaceClosure, WorkspaceExport
from app.recovery.repository import (
    RecoveryRepository,
    manifest_payload,
    payload_digest,
)
from app.storage_capability.models import StorageCapabilityRoute
from app.tenancy.models import OutboxEvent


class WorkspaceRecoveryError(RuntimeError):
    """Fail-closed recovery or closure operation."""


class WorkspaceRecoveryService:
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        self._session = session
        self._context = context
        self._repository = RecoveryRepository(session, context)
        self._audit = AuditWriterService(session, context)

    async def create_export(
        self,
        *,
        idempotency_key: str,
        authorization_decision_id: uuid.UUID,
        now: datetime | None = None,
    ) -> WorkspaceManifest:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        self._require_authorization(authorization_decision_id)
        existing = await self._repository.export(idempotency_key)
        if existing is not None:
            return self._manifest_from_payload(existing.manifest)
        manifest = await self._repository.manifest(now=now)
        payload = manifest_payload(manifest)
        self._session.add(
            WorkspaceExport(
                workspace_id=manifest.workspace_id,
                idempotency_key=idempotency_key,
                manifest=payload,
                manifest_digest=payload_digest(payload),
            )
        )
        await self._session.flush()
        return manifest

    async def record_restore(
        self,
        evidence: RestoreEvidence,
    ) -> None:
        if evidence.workspace_id != self._context.tenant.workspace_id:
            raise WorkspaceRecoveryError("restore workspace context does not match")
        payload = {
            "backup_id": str(evidence.backup_id),
            "workspace_id": str(evidence.workspace_id),
            "recovery_point_seconds": evidence.recovery_point_seconds,
            "recovery_time_seconds": evidence.recovery_time_seconds,
            "counts_verified": evidence.counts_verified,
            "digests_verified": evidence.digests_verified,
            "isolated_target": evidence.isolated_target,
        }
        await self._repository.add_recovery_evidence(
            RecoveryEvidence(
                workspace_id=evidence.workspace_id,
                backup_id=evidence.backup_id,
                operation="restore",
                status="succeeded",
                isolated_target=evidence.isolated_target,
                recovery_point_seconds=evidence.recovery_point_seconds,
                recovery_time_seconds=evidence.recovery_time_seconds,
                counts_verified=evidence.counts_verified,
                digests_verified=evidence.digests_verified,
                key_access_verified=True,
                evidence_digest=payload_digest(payload),
            )
        )

    async def record_backup(self, artifact: BackupArtifact) -> None:
        if artifact.workspace_id != self._context.tenant.workspace_id:
            raise WorkspaceRecoveryError("backup workspace context does not match")
        payload = {
            "backup_id": str(artifact.backup_id),
            "workspace_id": str(artifact.workspace_id),
            "source_snapshot_at": artifact.source_snapshot_at.isoformat(),
            "completed_at": artifact.completed_at.isoformat(),
            "key_resource": artifact.key_reference.resource,
            "key_version": artifact.key_reference.version,
        }
        await self._repository.add_recovery_evidence(
            RecoveryEvidence(
                workspace_id=artifact.workspace_id,
                backup_id=artifact.backup_id,
                operation="backup",
                status="succeeded",
                source_snapshot_at=artifact.source_snapshot_at,
                recovery_point_seconds=int(
                    (artifact.completed_at - artifact.source_snapshot_at).total_seconds()
                ),
                key_access_verified=True,
                evidence_digest=payload_digest(payload),
            )
        )

    async def record_key_recovery(
        self,
        *,
        backup_id: uuid.UUID,
        succeeded: bool,
        failure_code: str | None = None,
    ) -> None:
        if succeeded and failure_code is not None:
            raise ValueError("successful key recovery cannot have a failure code")
        if not succeeded and not (failure_code and failure_code.strip()):
            raise ValueError("failed key recovery requires a failure code")
        payload = {
            "backup_id": str(backup_id),
            "workspace_id": str(self._context.tenant.workspace_id),
            "status": "succeeded" if succeeded else "failed",
            "failure_code": failure_code,
        }
        await self._repository.add_recovery_evidence(
            RecoveryEvidence(
                workspace_id=self._context.tenant.workspace_id,
                backup_id=backup_id,
                operation="key_recovery",
                status="succeeded" if succeeded else "failed",
                key_access_verified=succeeded,
                failure_code=failure_code,
                evidence_digest=payload_digest(payload),
            )
        )
        await self._audit.write(
            AuditInput(
                action="recovery.key_access_verified",
                target_type="backup",
                target_id=backup_id,
                outcome="success" if succeeded else "failure",
                details={"failure_code": failure_code},
            )
        )

    async def close(
        self,
        *,
        idempotency_key: str,
        reason: str,
        authorization_decision_id: uuid.UUID,
        now: datetime | None = None,
    ) -> ClosureResult:
        if not idempotency_key.strip() or not reason.strip():
            raise ValueError("closure idempotency key and reason are required")
        self._require_authorization(authorization_decision_id)
        current_time = now or datetime.now(UTC)
        await self._session.execute(
            text("SELECT set_config('atlas.closure_operation', 'true', TRUE)")
        )
        workspace = await self._repository.lock_workspace()
        existing = await self._repository.closure(idempotency_key)
        governance = await self._repository.governance()
        if existing is not None and existing.state == ClosureState.CLOSED:
            return self._result(existing, replayed=True)
        if existing is None:
            before = await self._repository.manifest(now=current_time)
            existing = WorkspaceClosure(
                workspace_id=workspace.id,
                idempotency_key=idempotency_key,
                state=ClosureState.WRITES_FROZEN,
                initiated_by=self._context.actor.actor_id,
                authorization_decision_id=(self._context.actor.authorization_decision_id),
                reason=reason,
                before_manifest=manifest_payload(before),
            )
            self._session.add(existing)
            await self._revoke_access(current_time)
            workspace.status = "closing"
            await self._session.flush()

        blocked_reason = self._blocked_reason(governance, current_time)
        if blocked_reason is not None:
            existing.state = ClosureState.RETENTION_BLOCKED
            existing.blocked_reason = blocked_reason
            await self._session.flush()
            return self._result(existing, replayed=False)

        existing.state = ClosureState.ERASING
        existing.blocked_reason = None
        await self._erase_eligible_h1_data()
        workspace.status = "closed"
        after = await self._repository.manifest(now=current_time)
        existing.after_manifest = manifest_payload(after)
        existing.completed_at = current_time
        receipt = {
            "closure_id": str(existing.id),
            "workspace_id": str(workspace.id),
            "completed_at": current_time.isoformat(),
            "before_manifest_digest": payload_digest(existing.before_manifest),
            "after_manifest_digest": payload_digest(existing.after_manifest),
            "provider_reconciliation_required": True,
            "phase_one_provider_data_erased": False,
        }
        existing.receipt_digest = payload_digest(receipt)
        existing.state = ClosureState.CLOSED
        await self._record_closure_evidence(existing, current_time)
        await self._session.flush()
        return self._result(existing, replayed=False)

    async def _revoke_access(self, now: datetime) -> None:
        workspace_id = self._context.tenant.workspace_id
        await self._session.execute(
            update(IdentitySession)
            .where(
                IdentitySession.workspace_id == workspace_id,
                IdentitySession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revocation_reason="workspace_closure")
        )
        await self._session.execute(
            update(IdentityLifecycleToken)
            .where(
                IdentityLifecycleToken.workspace_id == workspace_id,
                IdentityLifecycleToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self._session.execute(
            update(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.status != "revoked",
            )
            .values(
                status="revoked",
                revoked_at=now,
                revocation_reason="workspace_closure",
                version=WorkspaceMembership.version + 1,
            )
        )
        await self._session.execute(
            update(EncryptedEnvelope)
            .where(EncryptedEnvelope.workspace_id == workspace_id)
            .values(status="disabled")
        )
        if await self._table_exists("connection_credentials"):
            await self._session.execute(
                update(ConnectionCredential)
                .where(ConnectionCredential.workspace_id == workspace_id)
                .values(status="disabled", disabled_at=now)
            )
        if await self._table_exists("connections"):
            await self._session.execute(
                update(Connection)
                .where(
                    Connection.workspace_id == workspace_id,
                    Connection.status != "closed",
                )
                .values(status="closed", closed_at=now, version=Connection.version + 1)
            )
        for table_name, route_model in (
            ("email_capability_routes", EmailCapabilityRoute),
            ("calendar_capability_routes", CalendarCapabilityRoute),
            ("storage_capability_routes", StorageCapabilityRoute),
        ):
            if await self._table_exists(table_name):
                if await self._column_exists(table_name, "mutation_route"):
                    await self._session.execute(
                        update(route_model)
                        .where(route_model.workspace_id == workspace_id)
                        .values(
                            route="legacy",
                            mutation_route="legacy",
                            version=route_model.version + 1,
                        )
                    )
                else:
                    await self._session.execute(
                        text(
                            f"UPDATE {table_name} SET route='legacy', version=version+1 "
                            "WHERE workspace_id=:workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    )

    async def _erase_eligible_h1_data(self) -> None:
        workspace_id = self._context.tenant.workspace_id
        for model in (
            IdentitySession,
            IdentityLifecycleToken,
            SecurityNotification,
            InboxEvent,
            EventQuarantine,
            ConsumerSequence,
            CommandIdempotency,
            AggregateVersion,
        ):
            await self._session.execute(delete(model).where(model.workspace_id == workspace_id))
        envelope_delete = delete(EncryptedEnvelope).where(
            EncryptedEnvelope.workspace_id == workspace_id
        )
        if await self._table_exists("connection_credentials"):
            referenced_envelopes = select(ConnectionCredential.envelope_id).where(
                ConnectionCredential.workspace_id == workspace_id
            )
            envelope_delete = envelope_delete.where(
                EncryptedEnvelope.id.not_in(referenced_envelopes)
            )
        await self._session.execute(envelope_delete)

    async def _table_exists(self, table_name: str) -> bool:
        return bool(
            await self._session.scalar(
                text("SELECT to_regclass(:table_name) IS NOT NULL"),
                {"table_name": f"public.{table_name}"},
            )
        )

    async def _column_exists(self, table_name: str, column_name: str) -> bool:
        return bool(
            await self._session.scalar(
                text(
                    """SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=:table_name
                      AND column_name=:column_name)"""
                ),
                {"table_name": table_name, "column_name": column_name},
            )
        )

    async def _record_closure_evidence(
        self,
        closure: WorkspaceClosure,
        now: datetime,
    ) -> None:
        await self._audit.write(
            AuditInput(
                action="workspace.closed",
                target_type="workspace",
                target_id=closure.workspace_id,
                outcome="success",
                details={
                    "closure_id": str(closure.id),
                    "receipt_digest": closure.receipt_digest,
                    "provider_reconciliation_required": True,
                },
            )
        )
        sequence = (
            await self._session.scalar(
                select(func.coalesce(func.max(OutboxEvent.aggregate_sequence), 0)).where(
                    OutboxEvent.workspace_id == closure.workspace_id,
                    OutboxEvent.aggregate_type == "workspace",
                    OutboxEvent.aggregate_id == closure.workspace_id,
                )
            )
        ) + 1
        payload = {
            "closure_id": str(closure.id),
            "receipt_digest": closure.receipt_digest,
            "provider_reconciliation_required": True,
        }
        self._session.add(
            OutboxEvent(
                workspace_id=closure.workspace_id,
                id=uuid.uuid4(),
                event_type="workspace.closed",
                aggregate_type="workspace",
                aggregate_id=closure.workspace_id,
                aggregate_sequence=sequence,
                payload=payload,
                actor_id=self._context.actor.actor_id,
                correlation_id=self._context.request.correlation_id,
                idempotency_key=closure.idempotency_key,
                payload_digest=payload_digest(payload),
                partition_key=now.strftime("%Y-%m"),
            )
        )

    @staticmethod
    def _blocked_reason(governance: object, now: datetime) -> str | None:
        if getattr(governance, "legal_hold"):
            return "legal_hold"
        minimum_retention_until = getattr(governance, "minimum_retention_until")
        if minimum_retention_until is not None and minimum_retention_until > now:
            return "minimum_retention"
        return None

    @staticmethod
    def _result(
        closure: WorkspaceClosure,
        *,
        replayed: bool,
    ) -> ClosureResult:
        return ClosureResult(
            closure_id=closure.id,
            workspace_id=closure.workspace_id,
            state=ClosureState(closure.state),
            receipt_digest=closure.receipt_digest,
            replayed=replayed,
            blocked_reason=closure.blocked_reason,
        )

    def _require_authorization(
        self,
        authorization_decision_id: uuid.UUID,
    ) -> None:
        if authorization_decision_id != self._context.actor.authorization_decision_id:
            raise WorkspaceRecoveryError("recovery authorization does not match execution context")

    @staticmethod
    def _manifest_from_payload(
        payload: dict[str, object],
    ) -> WorkspaceManifest:
        return WorkspaceManifest(
            workspace_id=uuid.UUID(str(payload["workspace_id"])),
            schema_version=int(str(payload["schema_version"])),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            table_counts={
                str(key): int(str(value))
                for key, value in dict(payload["table_counts"]).items()  # type: ignore[arg-type]
            },
            table_digests={
                str(key): str(value)
                for key, value in dict(payload["table_digests"]).items()  # type: ignore[arg-type]
            },
            provider_reconciliation_required=bool(payload["provider_reconciliation_required"]),
        )
