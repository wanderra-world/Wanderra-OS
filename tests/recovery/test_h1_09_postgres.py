"""PostgreSQL, RLS, restore, closure, and rollback evidence for H1-09."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.encryption import KeyReference
from app.execution_context import (
    ActorContext,
    ExecutionContext,
    ExecutionContextService,
    RequestContext,
    TenantContext,
)
from app.recovery import (
    BackupSnapshot,
    ClosureState,
    EncryptedBackupService,
    WorkspaceRecoveryError,
    WorkspaceRecoveryService,
)
from app.recovery.repository import RecoveryRepository, manifest_payload
from tests.encryption.support import MockManagedKeyProvider
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _migration,
    _require_migration,
    _seed_business_workspace,
)

H1_09_REVISION = "0013_h1_recovery_closure"
H1_08_REVISION = "0012_h1_audit_messaging"
BACKUP_KEY = KeyReference("atlas-recovery-test", "1")


def context(
    organization_id: UUID,
    workspace_id: UUID,
    cell_id: UUID,
    owner_id: UUID,
) -> ExecutionContext:
    return ExecutionContext(
        request=RequestContext(
            request_id=f"h1-09-{uuid4()}",
            correlation_id=f"h1-09-{uuid4()}",
        ),
        actor=ActorContext(
            actor_id=owner_id,
            session_id=uuid4(),
            membership_id=uuid4(),
            authorization_decision_id=uuid4(),
        ),
        tenant=TenantContext(
            organization_id=organization_id,
            workspace_id=workspace_id,
            cell_id=cell_id,
        ),
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_09_additive_migration_rls_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    role = f"h1_09_reader_{uuid4().hex}"
    try:
        _require_migration(database_name, H1_09_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                """
                SELECT bool_and(relrowsecurity AND relforcerowsecurity)
                FROM pg_class
                WHERE oid IN (
                    'workspace_data_governance'::regclass,
                    'workspace_exports'::regclass,
                    'workspace_closures'::regclass,
                    'workspace_recovery_evidence'::regclass
                )
                """
            )
        finally:
            await database.close()
        _require_migration(database_name, H1_08_REVISION, direction="downgrade")
        _require_migration(database_name, H1_09_REVISION)

        (
            _,
            workspace_id,
            second_workspace_id,
            _,
            _,
        ) = await _seed_business_workspace(database_name)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            for current_workspace in (workspace_id, second_workspace_id):
                await database.execute(
                    """
                    INSERT INTO workspace_data_governance (workspace_id)
                    VALUES ($1)
                    """,
                    current_workspace,
                )
            await database.execute(
                f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
            await database.execute(
                f"GRANT SELECT ON workspace_data_governance TO {role}"
            )
            await database.execute(f"SET ROLE {role}")
            await database.execute(
                "SELECT set_config('atlas.workspace_id', $1, false)",
                str(workspace_id),
            )
            assert await database.fetchval(
                "SELECT count(*) FROM workspace_data_governance"
            ) == 1
            await database.execute("RESET ROLE")
            await database.execute(f"DROP OWNED BY {role}")
            await database.execute(f"DROP ROLE {role}")
        finally:
            await database.close()
        refused = _migration(
            database_name,
            H1_08_REVISION,
            direction="downgrade",
        )
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_09_encrypted_backup_isolated_restore_and_evidence() -> None:
    admin, source_name = await _create_database()
    restore_name = f"h1_09_restore_{uuid4().hex}"
    source_engine = None
    restore_engine = None
    try:
        _require_migration(source_name, H1_09_REVISION)
        (
            organization_id,
            workspace_id,
            _,
            owner_id,
            _,
        ) = await _seed_business_workspace(source_name)
        database = await asyncpg.connect(_database_url(source_name))
        try:
            cell_id = await database.fetchval(
                "SELECT cell_id FROM workspaces WHERE workspace_id = $1",
                workspace_id,
            )
        finally:
            await database.close()
        execution_context = context(
            organization_id, workspace_id, cell_id, owner_id
        )
        source_engine = create_async_engine(
            _database_url(source_name, async_sqlalchemy=True)
        )
        source_sessions = async_sessionmaker(source_engine, expire_on_commit=False)
        execution = ExecutionContextService()
        snapshot_time = datetime.now(UTC)
        async with source_sessions() as session:
            async with execution.transaction(session, execution_context):
                source_manifest = await RecoveryRepository(
                    session, execution_context
                ).manifest(now=snapshot_time)
        await source_engine.dispose()
        source_engine = None

        snapshot_payload = json.dumps(
            manifest_payload(source_manifest),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        backup = EncryptedBackupService(
            MockManagedKeyProvider({BACKUP_KEY: b"r" * 32})
        )
        artifact = await backup.create(
            BackupSnapshot(
                payload=snapshot_payload,
                source_snapshot_at=snapshot_time,
                manifest=source_manifest,
            ),
            key_reference=BACKUP_KEY,
            now=snapshot_time + timedelta(minutes=1),
        )
        await admin.execute(f'CREATE DATABASE "{restore_name}" TEMPLATE "{source_name}"')
        restore_engine = create_async_engine(
            _database_url(restore_name, async_sqlalchemy=True)
        )
        restore_sessions = async_sessionmaker(restore_engine, expire_on_commit=False)

        async def restore(payload: bytes):
            assert payload == snapshot_payload
            async with restore_sessions() as session:
                async with execution.transaction(session, execution_context):
                    return await RecoveryRepository(
                        session, execution_context
                    ).manifest(now=source_manifest.created_at)

        evidence = await backup.restore(
            artifact,
            isolated_target=restore_name,
            restore=restore,
            started_at=snapshot_time + timedelta(minutes=1),
            now=snapshot_time + timedelta(minutes=4),
        )
        assert evidence.counts_verified and evidence.digests_verified
        assert evidence.rpo_met and evidence.rto_met
        failed_key_backup_id = uuid4()
        async with restore_sessions() as session:
            async with execution.transaction(session, execution_context):
                service = WorkspaceRecoveryService(session, execution_context)
                await service.record_restore(evidence)
                await service.record_restore(evidence)
                await service.record_backup(artifact)
                await service.record_key_recovery(
                    backup_id=artifact.backup_id,
                    succeeded=True,
                )
                await service.record_key_recovery(
                    backup_id=failed_key_backup_id,
                    succeeded=False,
                    failure_code="kms_access_denied",
                )
            assert await session.scalar(
                text(
                    """
                    SELECT count(*) FROM workspace_recovery_evidence
                    WHERE workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": workspace_id},
            ) == 4
            assert await session.scalar(
                text("SELECT verify_audit_chain(:workspace_id)"),
                {"workspace_id": workspace_id},
            )
    finally:
        if source_engine is not None:
            await source_engine.dispose()
        if restore_engine is not None:
            await restore_engine.dispose()
        await _drop_database(admin, restore_name)
        await _drop_database(admin, source_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_09_closure_retention_erasure_receipt_and_idempotency() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H1_09_REVISION)
        (
            organization_id,
            workspace_id,
            second_workspace_id,
            owner_id,
            _,
        ) = await _seed_business_workspace(database_name)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            cell_id = await database.fetchval(
                "SELECT cell_id FROM workspaces WHERE workspace_id = $1",
                workspace_id,
            )
            session_id = uuid4()
            await database.execute(
                """
                INSERT INTO identity_sessions (
                    workspace_id, id, user_id, token_hash, device_id,
                    authentication_strength, authenticated_at, last_seen_at,
                    expires_at
                )
                VALUES (
                    $1, $2, $3, $4, 'device', 'mfa', now(), now(),
                    now() + interval '1 hour'
                )
                """,
                workspace_id,
                session_id,
                owner_id,
                uuid4().hex + uuid4().hex,
            )
            await database.execute(
                """
                INSERT INTO gmail_credentials (user_id, encrypted_payload)
                VALUES ($1, 'phase-one-provider-ciphertext')
                """,
                owner_id,
            )
            await database.execute(
                """
                INSERT INTO encrypted_envelopes (
                    workspace_id, id, connection_id, record_type, record_id,
                    algorithm, ciphertext, nonce, wrapped_dek,
                    kms_key_resource, kms_key_version, checksum
                )
                VALUES (
                    $1, $2, $3, 'credential', $4, 'AES-256-GCM',
                    decode('01', 'hex'), decode('02', 'hex'),
                    decode('03', 'hex'), 'managed-key', '1',
                    repeat('0', 64)
                )
                """,
                workspace_id,
                uuid4(),
                uuid4(),
                uuid4(),
            )
            await database.execute(
                """
                INSERT INTO workspace_data_governance (
                    workspace_id, legal_hold, legal_hold_reason
                )
                VALUES ($1, true, 'active case')
                """,
                workspace_id,
            )
        finally:
            await database.close()
        execution_context = context(
            organization_id, workspace_id, cell_id, owner_id
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        now = datetime.now(UTC)
        async with sessions() as session:
            async with execution.transaction(session, execution_context):
                service = WorkspaceRecoveryService(session, execution_context)
                with pytest.raises(
                    WorkspaceRecoveryError,
                    match="authorization",
                ):
                    await service.create_export(
                        idempotency_key="denied",
                        authorization_decision_id=uuid4(),
                        now=now,
                    )
                exported = await service.create_export(
                    idempotency_key="export-1",
                    authorization_decision_id=(
                        execution_context.actor.authorization_decision_id
                    ),
                    now=now,
                )
                replayed_export = await service.create_export(
                    idempotency_key="export-1",
                    authorization_decision_id=(
                        execution_context.actor.authorization_decision_id
                    ),
                    now=now + timedelta(minutes=1),
                )
                assert replayed_export == exported
                blocked = await service.close(
                    idempotency_key="close-1",
                    reason="contract ended",
                    authorization_decision_id=(
                        execution_context.actor.authorization_decision_id
                    ),
                    now=now,
                )
                assert blocked.state == ClosureState.RETENTION_BLOCKED
                assert blocked.blocked_reason == "legal_hold"

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                """
                SELECT count(*) FROM identity_sessions
                WHERE workspace_id = $1 AND revoked_at IS NOT NULL
                """,
                workspace_id,
            ) == 1
            assert await database.fetchval(
                """
                SELECT count(*) FROM encrypted_envelopes
                WHERE workspace_id = $1 AND status = 'disabled'
                """,
                workspace_id,
            ) == 1
            with pytest.raises(asyncpg.RaiseError, match="writes are frozen"):
                await database.execute(
                    """
                    INSERT INTO aggregate_versions (
                        workspace_id, aggregate_type, aggregate_id
                    )
                    VALUES ($1, 'project', $2)
                    """,
                    workspace_id,
                    uuid4(),
                )
            await database.execute(
                "SELECT set_config('atlas.closure_operation', 'true', false)"
            )
            await database.execute(
                """
                UPDATE workspace_data_governance
                SET legal_hold = false, legal_hold_reason = NULL
                WHERE workspace_id = $1
                """,
                workspace_id,
            )
        finally:
            await database.close()

        async with sessions() as session:
            async with execution.transaction(session, execution_context):
                service = WorkspaceRecoveryService(session, execution_context)
                closed = await service.close(
                    idempotency_key="close-1",
                    reason="contract ended",
                    authorization_decision_id=(
                        execution_context.actor.authorization_decision_id
                    ),
                    now=now + timedelta(days=1),
                )
                replay = await service.close(
                    idempotency_key="close-1",
                    reason="contract ended",
                    authorization_decision_id=(
                        execution_context.actor.authorization_decision_id
                    ),
                    now=now + timedelta(days=1),
                )
                assert closed.state == ClosureState.CLOSED
                assert closed.receipt_digest is not None
                assert replay.replayed
                assert replay.receipt_digest == closed.receipt_digest

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT status FROM workspaces WHERE workspace_id = $1",
                workspace_id,
            ) == "closed"
            assert await database.fetchval(
                "SELECT count(*) FROM identity_sessions WHERE workspace_id = $1",
                workspace_id,
            ) == 0
            assert await database.fetchval(
                "SELECT count(*) FROM encrypted_envelopes WHERE workspace_id = $1",
                workspace_id,
            ) == 0
            assert await database.fetchval(
                "SELECT encrypted_payload FROM gmail_credentials WHERE user_id = $1",
                owner_id,
            ) == "phase-one-provider-ciphertext"
            assert await database.fetchval(
                "SELECT status FROM workspaces WHERE workspace_id = $1",
                second_workspace_id,
            ) == "active"
            assert await database.fetchval(
                """
                SELECT provider_reconciliation_required
                FROM workspace_closures WHERE workspace_id = $1
                """,
                workspace_id,
            )
            assert await database.fetchval(
                "SELECT verify_audit_chain($1)", workspace_id
            )
            with pytest.raises(asyncpg.RaiseError, match="immutable"):
                await database.execute(
                    """
                    UPDATE workspace_closures SET receipt_digest = repeat('0', 64)
                    WHERE workspace_id = $1
                    """,
                    workspace_id,
                )
        finally:
            await database.close()
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
