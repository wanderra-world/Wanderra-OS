"""PostgreSQL, migration, RLS, and replay evidence for H2-02."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.connection_credentials import (
    CredentialMigrationError,
    PhaseOneCredentialSnapshot,
    ShadowMigrationCommand,
)
from app.connection_credentials.models import (
    ConnectionCredential,
    CredentialMigrationInventory,
)
from app.connection_credentials.phase_one import PhaseOneShadowLinker
from app.connection_credentials.service import ConnectionCredentialService
from app.connections import ConnectionCreate, ConnectionService
from app.encryption import KeyReference
from app.execution_context import ExecutionContext, ExecutionContextService
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
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

H2_02_REVISION = "0015_h2_credentials"
H2_01_REVISION = "0014_h2_connections"
KEY = KeyReference("h2-02-test-key", "1")


class AllowAuthorizer:
    async def authorize(
        self, context: ExecutionContext, permission_key: str
    ) -> bool:
        return permission_key in {"manage_workspace", "read_content"}


async def _seed_connection(
    sessions: async_sessionmaker,
    execution: ExecutionContextService,
    context: ExecutionContext,
) -> UUID:
    connection_id = uuid4()
    async with sessions() as session:
        async with execution.transaction(session, context):
            await ConnectionService(session, context).create(
                ConnectionCreate(
                    connection_id=connection_id,
                    provider_key="google_workspace",
                    connection_kind="workspace_suite",
                    provider_account_id=f"account-{connection_id}",
                    display_name="H2-02 shadow source",
                    granted_scopes=("scope.read", "scope.write"),
                )
            )
    return connection_id


def _command(
    connection_id: UUID,
    source_record_id: str,
    *,
    ciphertext: bytes = b"legacy-authenticated-ciphertext",
) -> ShadowMigrationCommand:
    return ShadowMigrationCommand(
        connection_id=connection_id,
        provider_key="google_workspace",
        credential_kind="oauth_grant",
        snapshot=PhaseOneCredentialSnapshot(
            source_system="gmail_credentials",
            source_record_id=source_record_id,
            legacy_ciphertext=ciphertext,
            plaintext=b'{"refresh_token":"private","scopes":["scope.read"]}',
            scopes=("scope.read",),
        ),
        required_scopes=("scope.read",),
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_02_additive_migration_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H2_02_REVISION)
        _require_migration(database_name, H2_02_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H2_02_REVISION
            assert await database.fetchval(
                """
                SELECT bool_and(relrowsecurity AND relforcerowsecurity)
                FROM pg_class
                WHERE oid IN (
                    'connection_credentials'::regclass,
                    'credential_migration_inventory'::regclass
                )
                """
            )
        finally:
            await database.close()

        _require_migration(database_name, H2_01_REVISION, direction="downgrade")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT to_regclass('public.connection_credentials') IS NULL"
            )
            assert await database.fetchval(
                "SELECT to_regclass('public.credential_migration_inventory') IS NULL"
            )
            assert await database.fetchval(
                "SELECT to_regclass('public.connections') IS NOT NULL"
            )
        finally:
            await database.close()
        _require_migration(database_name, H2_02_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_02_shadow_equivalence_replay_rotation_disable_and_rls() -> None:
    admin, database_name = await _create_database()
    engine = None
    runtime_role = f"h2_02_reader_{uuid4().hex}"
    try:
        _require_migration(database_name, H2_02_REVISION)
        organization_id, workspace_id, second_workspace_id, owner_id, _ = (
            await _seed_business_workspace(database_name)
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        connection_id = await _seed_connection(sessions, execution, context)
        legacy_payload = "legacy-authoritative-value"
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                """
                INSERT INTO gmail_credentials (
                    user_id, encrypted_payload, workspace_id
                ) VALUES ($1, $2, $3)
                """,
                owner_id,
                legacy_payload,
                workspace_id,
            )
        finally:
            await database.close()
        keys = MockManagedKeyProvider({KEY: b"k" * 32})
        command = _command(connection_id, str(owner_id))

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = ConnectionCredentialService(
                    session,
                    context,
                    key_provider=keys,
                    authorizer=AllowAuthorizer(),
                    legacy_linker=PhaseOneShadowLinker(session),
                )
                first = await service.shadow_migrate(command, key_reference=KEY)
                replay = await service.shadow_migrate(command, key_reference=KEY)
                assert replay.id == first.id
                assert (await service.inventory_summary()).verified_count == 1
                replacement = await service.rotate(
                    credential_id=first.id,
                    replacement_plaintext=b'{"refresh_token":"replacement"}',
                    key_reference=KEY,
                    scopes=("scope.read",),
                )
                assert replacement.generation == 2
                await service.emergency_disable(
                    credential_id=replacement.id,
                    incident_reference="incident-2026-07-31",
                )
                credential_id = first.id

            assert await session.scalar(
                select(func.count()).select_from(ConnectionCredential)
            ) == 2
            assert await session.scalar(
                select(func.count()).select_from(CredentialMigrationInventory)
            ) == 1
            assert await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("connection.shadow_%"))
            ) == 3
            assert await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type.like("connection.shadow_%"))
            ) == 3

        database = await asyncpg.connect(_database_url(database_name))
        try:
            legacy = await database.fetchrow(
                """
                SELECT encrypted_payload, envelope_id, envelope_cutover,
                       envelope_verified_at
                FROM gmail_credentials WHERE user_id = $1
                """,
                owner_id,
            )
            assert legacy["encrypted_payload"] == legacy_payload
            assert legacy["envelope_id"] is not None
            assert not legacy["envelope_cutover"]
            assert legacy["envelope_verified_at"] is not None
            with pytest.raises(asyncpg.RaiseError, match="identity is immutable"):
                await database.execute(
                    """
                    UPDATE connection_credentials
                    SET provider_key = 'substituted'
                    WHERE workspace_id = $1 AND id = $2
                    """,
                    workspace_id,
                    credential_id,
                )

            await database.execute(
                f"CREATE ROLE {runtime_role} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {runtime_role}")
            await database.execute(
                f"GRANT SELECT ON connection_credentials, "
                f"credential_migration_inventory TO {runtime_role}"
            )
            async with database.transaction():
                await database.execute(f"SET LOCAL ROLE {runtime_role}")
                await database.execute(
                    "SELECT set_config('atlas.workspace_id', $1, TRUE)",
                    str(second_workspace_id),
                )
                assert await database.fetchval(
                    "SELECT count(*) FROM connection_credentials"
                ) == 0
        finally:
            await database.close()

        refused = _migration(
            database_name, H2_01_REVISION, direction="downgrade"
        )
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.execute(f"DROP ROLE IF EXISTS {runtime_role}")
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_02_concurrent_replay_and_fail_closed_legacy_fallback() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_02_REVISION)
        organization_id, workspace_id, _, owner_id, _ = (
            await _seed_business_workspace(database_name)
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        connection_id = await _seed_connection(sessions, execution, context)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                """
                INSERT INTO gmail_credentials (
                    user_id, encrypted_payload, workspace_id
                ) VALUES ($1, 'legacy-still-valid', $2)
                """,
                owner_id,
                workspace_id,
            )
        finally:
            await database.close()
        keys = MockManagedKeyProvider({KEY: b"k" * 32})
        command = _command(connection_id, str(owner_id))

        async def migrate_once() -> UUID:
            async with sessions() as session:
                async with execution.transaction(session, context):
                    result = await ConnectionCredentialService(
                        session,
                        context,
                        key_provider=keys,
                        authorizer=AllowAuthorizer(),
                        legacy_linker=PhaseOneShadowLinker(session),
                    ).shadow_migrate(command, key_reference=KEY)
                    return result.id

        results = await asyncio.gather(migrate_once(), migrate_once())
        assert results[0] == results[1]

        scope_gap = ShadowMigrationCommand(
            connection_id=connection_id,
            provider_key="google_workspace",
            credential_kind="oauth_grant",
            snapshot=PhaseOneCredentialSnapshot(
                source_system="calendar_credentials",
                source_record_id=str(owner_id),
                legacy_ciphertext=b"calendar-legacy-ciphertext",
                plaintext=b'{"refresh_token":"private"}',
                scopes=("scope.read",),
            ),
            required_scopes=("scope.write",),
        )
        async with sessions() as session:
            async with execution.transaction(session, context):
                with pytest.raises(
                    CredentialMigrationError, match="additional authorization"
                ):
                    await ConnectionCredentialService(
                        session,
                        context,
                        key_provider=keys,
                        authorizer=AllowAuthorizer(),
                    ).shadow_migrate(scope_gap, key_reference=KEY)

        async with sessions() as session:
            assert await session.scalar(
                select(func.count()).select_from(ConnectionCredential)
            ) == 1
            assert await session.scalar(
                select(func.count()).select_from(CredentialMigrationInventory)
            ) == 2
            assert await session.scalar(
                select(func.count())
                .select_from(CredentialMigrationInventory)
                .where(
                    CredentialMigrationInventory.status
                    == "reauthorization_required"
                )
            ) == 1

        database = await asyncpg.connect(_database_url(database_name))
        try:
            legacy_before = await database.fetchval(
                "SELECT encrypted_payload FROM gmail_credentials WHERE user_id = $1",
                owner_id,
            )
        finally:
            await database.close()
        keys.available = False
        failed = _command(
            connection_id,
            str(uuid4()),
            ciphertext=b"second-legacy-ciphertext",
        )
        async with sessions() as session:
            async with execution.transaction(session, context):
                with pytest.raises(CredentialMigrationError, match="failed"):
                    await ConnectionCredentialService(
                        session,
                        context,
                        key_provider=keys,
                        authorizer=AllowAuthorizer(),
                    ).shadow_migrate(failed, key_reference=KEY)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT encrypted_payload FROM gmail_credentials WHERE user_id = $1",
                owner_id,
            ) == legacy_before
        finally:
            await database.close()
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
