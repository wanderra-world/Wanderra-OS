"""PostgreSQL acceptance evidence for the H2-01 connection foundation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.connections import (
    CapabilityGrant,
    ConnectionAuthorizationError,
    ConnectionConcurrencyError,
    ConnectionCreate,
    ConnectionRegistryError,
    ConnectionRepository,
    ConnectionService,
    ConnectionStatus,
)
from app.execution_context import (
    ActorContext,
    ExecutionContext,
    ExecutionContextRequiredError,
    ExecutionContextService,
    RequestContext,
    TenantContext,
)
from app.tenancy.models import AuditEvent, OutboxEvent
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

H2_01_REVISION = "0014_h2_connections"
H1_FINAL_REVISION = "0013_h1_recovery_closure"


async def _context_for_owner(
    database_name: str,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    owner_id: UUID,
) -> ExecutionContext:
    session_id = uuid4()
    database = await asyncpg.connect(_database_url(database_name))
    try:
        membership_id = await database.fetchval(
            """
            SELECT id FROM workspace_memberships
            WHERE workspace_id = $1
              AND user_id = $2
              AND status = 'active'
            """,
            workspace_id,
            owner_id,
        )
        cell_id = await database.fetchval(
            "SELECT cell_id FROM workspaces WHERE workspace_id = $1",
            workspace_id,
        )
        now = datetime.now(UTC)
        await database.execute(
            """
            INSERT INTO identity_sessions (
                workspace_id, id, user_id, token_hash, device_id,
                authentication_strength, authenticated_at, last_seen_at, expires_at
            )
            VALUES ($1, $2, $3, $4, 'h2-01-test', 'mfa', $5, $5, $6)
            """,
            workspace_id,
            session_id,
            owner_id,
            uuid4().hex + uuid4().hex,
            now,
            now + timedelta(hours=1),
        )
    finally:
        await database.close()
    return ExecutionContext(
        request=RequestContext(
            request_id=f"h2-01-{uuid4()}",
            correlation_id=f"h2-01-{uuid4()}",
        ),
        actor=ActorContext(
            actor_id=owner_id,
            session_id=session_id,
            membership_id=membership_id,
            authorization_decision_id=uuid4(),
        ),
        tenant=TenantContext(
            organization_id=organization_id,
            workspace_id=workspace_id,
            cell_id=cell_id,
        ),
    )


def _create_command(
    *,
    connection_id: UUID | None = None,
    provider_account_id: str = "provider-account-1",
) -> ConnectionCreate:
    return ConnectionCreate(
        connection_id=connection_id or uuid4(),
        provider_key="google_workspace",
        connection_kind="workspace_suite",
        provider_account_id=provider_account_id,
        display_name="Atlas Test Workspace",
        granted_scopes=("scope.calendar", "scope.email"),
        capability_grants=(
            CapabilityGrant("email.read"),
            CapabilityGrant("calendar.read"),
        ),
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_01_migration_populated_phase_one_rls_and_rollback() -> None:
    admin, database_name = await _create_database()
    phase_one_user_id = uuid4()
    rls_role = f"h2_01_reader_{uuid4().hex}"
    try:
        _require_migration(database_name, "0005_add_drive_integration")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await _insert_phase_one_user(database, phase_one_user_id)
        finally:
            await database.close()

        _require_migration(database_name, H2_01_REVISION)
        _require_migration(database_name, H2_01_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H2_01_REVISION
            assert await database.fetchval(
                "SELECT count(*) FROM users WHERE id = $1",
                phase_one_user_id,
            ) == 1
            assert await database.fetchval(
                "SELECT count(*) FROM provider_registry"
            ) == 1
            assert await database.fetchval(
                "SELECT count(*) FROM connection_kinds"
            ) == 1
            assert await database.fetchval(
                "SELECT count(*) FROM provider_capabilities"
            ) == 6
            assert await database.fetchval(
                """
                SELECT bool_and(relrowsecurity AND relforcerowsecurity)
                FROM pg_class
                WHERE oid IN (
                    'connections'::regclass,
                    'connection_capability_grants'::regclass
                )
                """
            )
            workspace_ids = await database.fetch(
                "SELECT workspace_id FROM workspaces ORDER BY workspace_id"
            )
            assert len(workspace_ids) == 1
            workspace_id = workspace_ids[0]["workspace_id"]
            await database.execute(
                f"CREATE ROLE {rls_role} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {rls_role}")
            await database.execute(
                f"GRANT SELECT ON connections, connection_capability_grants TO {rls_role}"
            )
            await database.execute(f"SET ROLE {rls_role}")
            assert await database.fetchval("SELECT count(*) FROM connections") == 0
            await database.execute(
                "SELECT set_config('atlas.workspace_id', $1, false)",
                str(workspace_id),
            )
            assert await database.fetchval("SELECT count(*) FROM connections") == 0
            await database.execute("RESET ROLE")
            await database.execute(f"DROP OWNED BY {rls_role}")
            await database.execute(f"DROP ROLE {rls_role}")
        finally:
            await database.close()

        _require_migration(database_name, H1_FINAL_REVISION, direction="downgrade")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT to_regclass('public.connections') IS NULL"
            )
            assert await database.fetchval(
                "SELECT to_regclass('public.provider_registry') IS NULL"
            )
            assert await database.fetchval(
                "SELECT count(*) FROM users WHERE id = $1",
                phase_one_user_id,
            ) == 1
        finally:
            await database.close()
        _require_migration(database_name, H2_01_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_01_authorized_lifecycle_capabilities_and_atomic_evidence() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_01_REVISION)
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
        context_service = ExecutionContextService()
        command = _create_command()

        async with sessions() as session:
            async with context_service.transaction(session, context):
                service = ConnectionService(session, context)
                connection = await service.create(command)
                assert connection.status == ConnectionStatus.PENDING.value
                assert (await service.get(connection_id=connection.id)).id == connection.id
                assert [item.id for item in await service.list_for_workspace()] == [
                    connection.id
                ]
                assert await service.effective_capabilities(
                    connection_id=connection.id
                ) == ()

            async with context_service.transaction(session, context):
                service = ConnectionService(session, context)
                connection = await service.transition(
                    connection_id=command.connection_id,
                    expected_version=1,
                    target=ConnectionStatus.ACTIVE,
                )
                assert connection.version == 2
                assert await service.effective_capabilities(
                    connection_id=connection.id
                ) == ("calendar.read", "email.read")

            async with context_service.transaction(session, context):
                service = ConnectionService(session, context)
                await service.revoke_capability(
                    connection_id=command.connection_id,
                    expected_version=2,
                    grant=CapabilityGrant("email.read"),
                )
                assert await service.effective_capabilities(
                    connection_id=command.connection_id
                ) == ("calendar.read",)

            async with context_service.transaction(session, context):
                service = ConnectionService(session, context)
                await service.transition(
                    connection_id=command.connection_id,
                    expected_version=3,
                    target=ConnectionStatus.REVOKED,
                )
                assert await service.effective_capabilities(
                    connection_id=command.connection_id
                ) == ()

            async with context_service.transaction(session, context):
                service = ConnectionService(session, context)
                await service.transition(
                    connection_id=command.connection_id,
                    expected_version=4,
                    target=ConnectionStatus.CLOSED,
                )
                assert await service.effective_capabilities(
                    connection_id=command.connection_id
                ) == ()

            connection_audits = await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("connection.%"))
            )
            connection_events = await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type.like("connection.%"))
            )
            assert connection_audits == 5
            assert connection_events == 5
            assert await session.scalar(
                text("SELECT verify_audit_chain(:workspace_id)"),
                {"workspace_id": workspace_id},
            )

        database = await asyncpg.connect(_database_url(database_name))
        try:
            with pytest.raises(asyncpg.RaiseError, match="transition is invalid"):
                await database.execute(
                    """
                    UPDATE connections
                    SET status = 'active',
                        version = version + 1,
                        revoked_at = NULL,
                        closed_at = NULL
                    WHERE workspace_id = $1 AND id = $2
                    """,
                    workspace_id,
                    command.connection_id,
                )
        finally:
            await database.close()

        refused = _migration(
            database_name,
            H1_FINAL_REVISION,
            direction="downgrade",
        )
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_01_cross_workspace_application_and_postgres_isolation() -> None:
    admin, database_name = await _create_database()
    engine = None
    runtime_role = f"h2_01_runtime_{uuid4().hex}"
    try:
        _require_migration(database_name, H2_01_REVISION)
        (
            organization_id,
            workspace_id,
            second_workspace_id,
            owner_id,
            _,
        ) = await _seed_business_workspace(database_name)
        first_context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        second_context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=second_workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        context_service = ExecutionContextService()
        first_command = _create_command(provider_account_id="same-account")
        second_command = _create_command(provider_account_id="same-account")

        async with sessions() as session:
            async with context_service.transaction(session, first_context):
                first = await ConnectionService(session, first_context).create(
                    first_command
                )
                repository = ConnectionRepository(session, first_context)
                with pytest.raises(
                    ExecutionContextRequiredError,
                    match="cross-workspace",
                ):
                    await repository.get(
                        workspace_id=second_workspace_id,
                        connection_id=first.id,
                    )
        async with sessions() as session:
            with pytest.raises(IntegrityError) as duplicate:
                async with context_service.transaction(session, first_context):
                    await ConnectionService(session, first_context).create(
                        _create_command(provider_account_id="same-account")
                    )
            assert "uq_connections_workspace_provider_kind_account" in str(
                duplicate.value
            )
        async with sessions() as session:
            async with context_service.transaction(session, second_context):
                second = await ConnectionService(session, second_context).create(
                    second_command
                )
                assert second.provider_account_id == first.provider_account_id

        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                f"CREATE ROLE {runtime_role} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(
                f"GRANT USAGE ON SCHEMA public TO {runtime_role}"
            )
            await database.execute(
                f"GRANT SELECT, INSERT, UPDATE ON connections TO {runtime_role}"
            )
            await database.execute(
                f"GRANT SELECT, INSERT, UPDATE ON connection_capability_grants "
                f"TO {runtime_role}"
            )
            async with database.transaction():
                await database.execute(f"SET LOCAL ROLE {runtime_role}")
                await database.execute(
                    "SELECT set_config('atlas.workspace_id', $1, TRUE)",
                    str(workspace_id),
                )
                assert await database.fetchval(
                    "SELECT count(*) FROM connections"
                ) == 1
                assert not await database.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM connections WHERE workspace_id = $1
                    )
                    """,
                    second_workspace_id,
                )
                assert (
                    await database.execute(
                        """
                        UPDATE connections
                        SET display_name = 'Cross workspace', version = version + 1
                        WHERE workspace_id = $1
                        """,
                        second_workspace_id,
                    )
                    == "UPDATE 0"
                )
        finally:
            await database.close()
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
async def test_h2_01_authorization_concurrency_and_transaction_rollback() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_01_REVISION)
        organization_id, workspace_id, _, owner_id, member_id = (
            await _seed_business_workspace(database_name)
        )
        owner_context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        database = await asyncpg.connect(_database_url(database_name))
        try:
            member_membership_id = uuid4()
            now = datetime.now(UTC)
            member_session_id = uuid4()
            await database.execute(
                """
                INSERT INTO workspace_memberships (
                    workspace_id, id, organization_id, user_id, role_key,
                    role_version, status, version, activated_at, origin
                )
                VALUES ($1, $2, $3, $4, 'viewer', 1, 'active', 1, $5, 'direct')
                """,
                workspace_id,
                member_membership_id,
                organization_id,
                member_id,
                now,
            )
            await database.execute(
                """
                INSERT INTO identity_sessions (
                    workspace_id, id, user_id, token_hash, device_id,
                    authentication_strength, authenticated_at, last_seen_at, expires_at
                )
                VALUES ($1, $2, $3, $4, 'h2-01-viewer', 'mfa', $5, $5, $6)
                """,
                workspace_id,
                member_session_id,
                member_id,
                uuid4().hex + uuid4().hex,
                now,
                now + timedelta(hours=1),
            )
            cell_id = await database.fetchval(
                "SELECT cell_id FROM workspaces WHERE workspace_id = $1",
                workspace_id,
            )
        finally:
            await database.close()
        viewer_context = ExecutionContext(
            request=RequestContext("viewer-request", "viewer-correlation"),
            actor=ActorContext(
                actor_id=member_id,
                session_id=member_session_id,
                membership_id=member_membership_id,
                authorization_decision_id=uuid4(),
            ),
            tenant=TenantContext(organization_id, workspace_id, cell_id),
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        context_service = ExecutionContextService()

        for invalid_command in (
            ConnectionCreate(
                connection_id=uuid4(),
                provider_key="unknown_provider",
                connection_kind="workspace_suite",
                provider_account_id="unknown-provider",
                display_name="Unknown",
            ),
            ConnectionCreate(
                connection_id=uuid4(),
                provider_key="google_workspace",
                connection_kind="unknown_kind",
                provider_account_id="unknown-kind",
                display_name="Unknown",
            ),
            ConnectionCreate(
                connection_id=uuid4(),
                provider_key="google_workspace",
                connection_kind="workspace_suite",
                provider_account_id="unknown-capability",
                display_name="Unknown",
                capability_grants=(CapabilityGrant("unknown.capability"),),
            ),
        ):
            async with sessions() as session:
                with pytest.raises(ConnectionRegistryError):
                    async with context_service.transaction(session, owner_context):
                        await ConnectionService(session, owner_context).create(
                            invalid_command
                        )

        async with sessions() as session:
            with pytest.raises(ConnectionAuthorizationError):
                async with context_service.transaction(session, viewer_context):
                    await ConnectionService(session, viewer_context).create(
                        _create_command(provider_account_id="viewer-account")
                    )

        async with sessions() as session:
            assert await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("connection.%"))
            ) == 0

        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                """
                UPDATE workspace_memberships
                SET role_key = 'workspace_admin', version = version + 1
                WHERE workspace_id = $1 AND id = $2
                """,
                workspace_id,
                member_membership_id,
            )
        finally:
            await database.close()
        async with sessions() as session:
            async with context_service.transaction(session, viewer_context):
                admin_connection = await ConnectionService(
                    session,
                    viewer_context,
                ).create(_create_command(provider_account_id="admin-account"))
                assert admin_connection.status == ConnectionStatus.PENDING.value

        async with sessions() as session:
            with pytest.raises(RuntimeError, match="force rollback"):
                async with context_service.transaction(session, owner_context):
                    await ConnectionService(session, owner_context).create(
                        _create_command(provider_account_id="rollback-account")
                    )
                    raise RuntimeError("force rollback")

        async with sessions() as session:
            assert await session.scalar(
                text(
                    """
                    SELECT count(*) FROM connections
                    WHERE provider_account_id = 'rollback-account'
                    """
                )
            ) == 0

        command = _create_command(provider_account_id="concurrent-account")
        async with sessions() as session:
            async with context_service.transaction(session, owner_context):
                await ConnectionService(session, owner_context).create(command)

        async def activate() -> str:
            async with sessions() as session:
                try:
                    async with context_service.transaction(session, owner_context):
                        await ConnectionService(session, owner_context).transition(
                            connection_id=command.connection_id,
                            expected_version=1,
                            target=ConnectionStatus.ACTIVE,
                        )
                    return "accepted"
                except ConnectionConcurrencyError:
                    return "stale"

        assert sorted(await asyncio.gather(activate(), activate())) == [
            "accepted",
            "stale",
        ]
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
