"""Context-bound repository for H1-09 recovery and closure state."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.recovery.contracts import WorkspaceManifest
from app.recovery.models import (
    RecoveryEvidence,
    WorkspaceClosure,
    WorkspaceDataGovernance,
    WorkspaceExport,
)
from app.tenancy.models import Workspace

MANIFEST_TABLES = (
    "workspaces",
    "identity_sessions",
    "identity_lifecycle_tokens",
    "security_notifications",
    "workspace_memberships",
    "encrypted_envelopes",
    "audit_events",
    "outbox_events",
    "command_idempotency",
    "aggregate_versions",
    "inbox_events",
    "consumer_sequences",
    "event_quarantine",
    "connections",
    "connection_capability_grants",
    "connection_credentials",
    "credential_migration_inventory",
    "oauth_transactions",
    "provider_mirrors",
    "provider_external_references",
    "provider_mirror_comparisons",
    "provider_mirror_conflicts",
    "email_capability_routes",
    "email_shadow_comparisons",
    "calendar_capability_routes",
    "calendar_shadow_comparisons",
    "storage_capability_routes",
    "storage_shadow_comparisons",
    "connection_backfill_evidence",
    "capability_cutover_evidence",
)


def manifest_payload(manifest: WorkspaceManifest) -> dict[str, object]:
    return {
        "workspace_id": str(manifest.workspace_id),
        "schema_version": manifest.schema_version,
        "created_at": manifest.created_at.isoformat(),
        "table_counts": manifest.table_counts,
        "table_digests": manifest.table_digests,
        "provider_reconciliation_required": (manifest.provider_reconciliation_required),
    }


def payload_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class RecoveryRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def lock_workspace(self) -> Workspace:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        workspace = await self.session.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None
        return workspace

    async def manifest(
        self,
        *,
        now: datetime | None = None,
    ) -> WorkspaceManifest:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        counts: dict[str, int] = {}
        digests: dict[str, str] = {}
        for table_name in MANIFEST_TABLES:
            if not await self.session.scalar(
                text("SELECT to_regclass(:table_name) IS NOT NULL"),
                {"table_name": f"public.{table_name}"},
            ):
                continue
            result = (
                (
                    await self.session.execute(
                        text(
                            f"""
                        SELECT count(*) AS row_count,
                               encode(
                                   digest(
                                       COALESCE(
                                           string_agg(row_data, '' ORDER BY row_data),
                                           ''
                                       ),
                                       'sha256'
                                   ),
                                   'hex'
                               ) AS row_digest
                        FROM (
                            SELECT to_jsonb(source_row)::text AS row_data
                            FROM {table_name} AS source_row
                            WHERE workspace_id = :workspace_id
                        ) AS rows
                        """
                        ),
                        {"workspace_id": workspace_id},
                    )
                )
                .mappings()
                .one()
            )
            counts[table_name] = int(result["row_count"])
            digests[table_name] = str(result["row_digest"])
        return WorkspaceManifest(
            workspace_id=workspace_id,
            schema_version=1,
            created_at=now or datetime.now(UTC),
            table_counts=counts,
            table_digests=digests,
        )

    async def governance(self) -> WorkspaceDataGovernance:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        await self.session.execute(
            insert(WorkspaceDataGovernance)
            .values(workspace_id=workspace_id)
            .on_conflict_do_nothing()
        )
        governance = await self.session.scalar(
            select(WorkspaceDataGovernance)
            .where(WorkspaceDataGovernance.workspace_id == workspace_id)
            .with_for_update()
        )
        assert governance is not None
        return governance

    async def closure(
        self,
        idempotency_key: str,
    ) -> WorkspaceClosure | None:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        return await self.session.scalar(
            select(WorkspaceClosure)
            .where(
                WorkspaceClosure.workspace_id == workspace_id,
                WorkspaceClosure.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )

    async def export(
        self,
        idempotency_key: str,
    ) -> WorkspaceExport | None:
        workspace_id = self.context.tenant.workspace_id
        self.require_workspace(workspace_id)
        return await self.session.scalar(
            select(WorkspaceExport).where(
                WorkspaceExport.workspace_id == workspace_id,
                WorkspaceExport.idempotency_key == idempotency_key,
            )
        )

    async def add_recovery_evidence(
        self,
        evidence: RecoveryEvidence,
    ) -> bool:
        self.require_workspace(evidence.workspace_id)
        statement = (
            insert(RecoveryEvidence)
            .values(
                workspace_id=evidence.workspace_id,
                backup_id=evidence.backup_id,
                operation=evidence.operation,
                status=evidence.status,
                isolated_target=evidence.isolated_target,
                source_snapshot_at=evidence.source_snapshot_at,
                recovery_point_seconds=evidence.recovery_point_seconds,
                recovery_time_seconds=evidence.recovery_time_seconds,
                counts_verified=bool(evidence.counts_verified),
                digests_verified=bool(evidence.digests_verified),
                key_access_verified=bool(evidence.key_access_verified),
                failure_code=evidence.failure_code,
                evidence_digest=evidence.evidence_digest,
            )
            .on_conflict_do_nothing()
            .returning(RecoveryEvidence.backup_id)
        )
        created = (await self.session.scalar(statement)) is not None
        existing_digest = await self.session.scalar(
            select(RecoveryEvidence.evidence_digest).where(
                RecoveryEvidence.workspace_id == evidence.workspace_id,
                RecoveryEvidence.backup_id == evidence.backup_id,
                RecoveryEvidence.operation == evidence.operation,
            )
        )
        if existing_digest != evidence.evidence_digest:
            raise ValueError("recovery evidence replay does not match")
        return created
