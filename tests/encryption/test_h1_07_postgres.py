"""Migration, RLS, rotation, audit, and failure evidence for H1-07."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.encryption import EncryptionError, EnvelopeEncryptionService, KeyReference
from app.encryption.models import EncryptedEnvelope
from app.execution_context import (
    ActorContext,
    ExecutionContext,
    ExecutionContextService,
    RequestContext,
    TenantContext,
)
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.encryption.support import MockManagedKeyProvider
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _insert_phase_one_user,
    _migration,
    _require_migration,
    _seed_business_workspace,
)

H1_07_REVISION = "0011_h1_envelopes"
H1_06_REVISION = "0010_h1_authorization"
RLS_ROLE = "h1_07_envelope_reader"
OLD_KEY = KeyReference("managed-test-key", "1")
NEW_KEY = KeyReference("managed-test-key", "2")


def _execution_context(
    organization_id: UUID,
    workspace_id: UUID,
    cell_id: UUID,
    actor_id: UUID,
) -> ExecutionContext:
    return ExecutionContext(
        request=RequestContext(
            request_id="h1-07-request",
            correlation_id="h1-07-correlation",
        ),
        actor=ActorContext(
            actor_id=actor_id,
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
async def test_h1_07_additive_migration_rls_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    user_id = uuid4()
    try:
        _require_migration(database_name, "0005_add_drive_integration")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await _insert_phase_one_user(database, user_id)
            for table_name in (
                "gmail_credentials",
                "calendar_credentials",
                "drive_credentials",
            ):
                await database.execute(
                    f"""
                    INSERT INTO {table_name} (user_id, encrypted_payload)
                    VALUES ($1, 'legacy-ciphertext')
                    """,
                    user_id,
                )
        finally:
            await database.close()

        _require_migration(database_name, H1_07_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_07_REVISION
            for table_name in (
                "gmail_credentials",
                "calendar_credentials",
                "drive_credentials",
            ):
                row = await database.fetchrow(
                    f"""
                    SELECT encrypted_payload, workspace_id, envelope_id,
                           envelope_cutover, reauthorization_required
                    FROM {table_name} WHERE user_id = $1
                    """,
                    user_id,
                )
                assert row["encrypted_payload"] == "legacy-ciphertext"
                assert row["workspace_id"] is not None
                assert row["envelope_id"] is None
                assert not row["envelope_cutover"]
                assert not row["reauthorization_required"]
            rls = await database.fetchrow(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE oid = 'encrypted_envelopes'::regclass
                """
            )
            assert rls and rls["relrowsecurity"] and rls["relforcerowsecurity"]
        finally:
            await database.close()

        _require_migration(database_name, H1_06_REVISION, direction="downgrade")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT to_regclass('public.encrypted_envelopes') IS NULL"
            )
            assert await database.fetchval(
                "SELECT encrypted_payload FROM gmail_credentials WHERE user_id = $1",
                user_id,
            ) == "legacy-ciphertext"
        finally:
            await database.close()

        _require_migration(database_name, H1_07_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            workspace_id = await database.fetchval(
                "SELECT workspace_id FROM gmail_credentials WHERE user_id = $1",
                user_id,
            )
            await database.execute(
                """
                INSERT INTO encrypted_envelopes (
                    workspace_id, id, connection_id, record_type, record_id,
                    algorithm, ciphertext, nonce, wrapped_dek, kms_key_resource,
                    kms_key_version, checksum
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
        finally:
            await database.close()
        refused = _migration(
            database_name,
            H1_06_REVISION,
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
async def test_h1_07_encryption_rotation_failure_audit_and_rls() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H1_07_REVISION)
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
            await database.execute(f"DROP ROLE IF EXISTS {RLS_ROLE}")
            await database.execute(
                f"CREATE ROLE {RLS_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {RLS_ROLE}")
            await database.execute(
                f"GRANT SELECT ON encrypted_envelopes TO {RLS_ROLE}"
            )
        finally:
            await database.close()

        context = _execution_context(
            organization_id,
            workspace_id,
            cell_id,
            owner_id,
        )
        key_provider = MockManagedKeyProvider(
            {OLD_KEY: b"a" * 32, NEW_KEY: b"b" * 32}
        )
        execution = ExecutionContextService()
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        plaintext = b"\x00" * 48

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = EnvelopeEncryptionService(
                    session,
                    context,
                    key_provider,
                )
                envelope = await service.encrypt(
                    plaintext,
                    connection_id=uuid4(),
                    record_type="google_oauth_credential",
                    record_id=uuid4(),
                    key_reference=OLD_KEY,
                    legacy_source="gmail_credentials",
                    legacy_ciphertext=b"\x01" * 48,
                    now=datetime(2026, 7, 30, tzinfo=UTC),
                )
                envelope_id = envelope.id
                assert await service.decrypt(envelope) == plaintext
                assert plaintext not in envelope.ciphertext
                original_ciphertext = envelope.ciphertext
                original_wrapped_dek = envelope.wrapped_dek

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = EnvelopeEncryptionService(
                    session,
                    context,
                    key_provider,
                )
                request_id = uuid4()
                rotated = await service.rewrap(
                    envelope_id=envelope_id,
                    new_key_reference=NEW_KEY,
                    rotation_request_id=request_id,
                )
                assert rotated.ciphertext == original_ciphertext
                assert rotated.wrapped_dek != original_wrapped_dek
                generation = rotated.generation
                replayed = await service.rewrap(
                    envelope_id=envelope_id,
                    new_key_reference=NEW_KEY,
                    rotation_request_id=request_id,
                )
                assert replayed.generation == generation
                assert await service.decrypt(replayed) == plaintext

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = EnvelopeEncryptionService(
                    session,
                    context,
                    key_provider,
                )
                replaced = await service.replace_data_key(
                    envelope_id=envelope_id,
                    rotation_request_id=(dek_request_id := uuid4()),
                )
                assert replaced.ciphertext != original_ciphertext
                assert await service.decrypt(replaced) == plaintext
                dek_generation = replaced.generation
                replayed_dek = await service.replace_data_key(
                    envelope_id=envelope_id,
                    rotation_request_id=dek_request_id,
                )
                assert replayed_dek.generation == dek_generation
                verified = await service.verify_legacy_shadow(
                    envelope_id=envelope_id,
                    legacy_plaintext=plaintext,
                    legacy_ciphertext=b"\x01" * 48,
                )
                assert verified.shadow_verified_at is not None

        async with sessions.begin() as session:
            assert await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.action == "encryption.shadow_verified",
                )
            )
            assert await session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.workspace_id == workspace_id,
                    OutboxEvent.event_type == "encryption.kek_rewrapped",
                )
            )

        database = await asyncpg.connect(_database_url(database_name))
        try:
            async with database.transaction():
                await database.execute(f"SET LOCAL ROLE {RLS_ROLE}")
                assert await database.fetchval(
                    "SELECT count(*) FROM encrypted_envelopes"
                ) == 0
                await database.execute(
                    "SELECT set_config('atlas.workspace_id', $1, TRUE)",
                    str(workspace_id),
                )
                assert await database.fetchval(
                    "SELECT count(*) FROM encrypted_envelopes"
                ) == 1
                await database.execute(
                    "SELECT set_config('atlas.workspace_id', $1, TRUE)",
                    str(second_workspace_id),
                )
                assert await database.fetchval(
                    "SELECT count(*) FROM encrypted_envelopes"
                ) == 0
        finally:
            await database.close()

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = EnvelopeEncryptionService(
                    session,
                    context,
                    key_provider,
                )
                envelope = await service._repository.get(
                    workspace_id=workspace_id,
                    envelope_id=envelope_id,
                    for_update=True,
                )
                assert envelope is not None
                original_record_type = envelope.record_type
                envelope.record_type = "tampered_type"
                with pytest.raises(EncryptionError, match="authentication"):
                    await service.decrypt(envelope)
                envelope.record_type = original_record_type
                original_key_version = envelope.kms_key_version
                envelope.kms_key_version = "unknown-version"
                with pytest.raises(EncryptionError, match="authentication"):
                    await service.decrypt(envelope)
                envelope.kms_key_version = original_key_version
                original_encrypted_payload = envelope.ciphertext
                envelope.ciphertext = b"\xff" + envelope.ciphertext[1:]
                with pytest.raises(EncryptionError, match="authentication"):
                    await service.decrypt(envelope)
                envelope.ciphertext = original_encrypted_payload

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = EnvelopeEncryptionService(
                    session,
                    context,
                    key_provider,
                )
                disabled = await service.encrypt(
                    b"\x02" * 48,
                    connection_id=uuid4(),
                    record_type="google_oauth_credential",
                    record_id=uuid4(),
                    key_reference=NEW_KEY,
                )
                await service.emergency_disable(
                    envelope_id=disabled.id,
                    incident_reference="incident-h1-07",
                )
                with pytest.raises(EncryptionError, match="unavailable"):
                    await service.decrypt(disabled)

        key_provider.available = False
        async with sessions() as session:
            async with execution.transaction(session, context):
                service = EnvelopeEncryptionService(
                    session,
                    context,
                    key_provider,
                )
                with pytest.raises(EncryptionError, match="failed closed"):
                    await service.rewrap(
                        envelope_id=envelope_id,
                        new_key_reference=OLD_KEY,
                        rotation_request_id=uuid4(),
                    )
        async with sessions.begin() as session:
            quarantined = await session.get(
                EncryptedEnvelope,
                (workspace_id, envelope_id),
            )
            assert quarantined is not None
            assert quarantined.status == "quarantined"
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.execute(f"DROP ROLE IF EXISTS {RLS_ROLE}")
        await admin.close()
