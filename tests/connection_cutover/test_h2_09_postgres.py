"""PostgreSQL migration, RLS, and rollback evidence for H2-09."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.capability_routing.contracts import CapabilityRoute
from app.connection_cutover.contracts import (
    BackfillCandidate,
    CutoverThreshold,
    IntegrationCapability,
)
from app.connection_cutover.models import (
    CapabilityCutoverEvidence,
    ConnectionBackfillEvidence,
)
from app.connection_cutover.service import ConnectionBackfillService, ConnectionCutoverService
from app.email_capability.contracts import EmailOperation
from app.email_capability.repository import EmailRoutingRepository
from app.execution_context import ExecutionContextService
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connection_credentials.test_h2_02_postgres import AllowAuthorizer
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.email_capability.test_h2_06_postgres import AllowRouteChanges
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _insert_phase_one_user,
    _require_migration,
    _seed_business_workspace,
)

H2_08_REVISION = "0020_h2_storage_capability"
H2_09_REVISION = "0021_h2_connection_cutover"


def test_h2_09_migration_is_additive_guarded_and_keeps_legacy_credentials() -> None:
    source = (
        Path(__file__).parents[2] / "alembic/versions/0021_add_connection_cutover.py"
    ).read_text()
    assert "mutation_route" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "cannot downgrade H2-09 with backfill or cutover evidence" in source
    for table in ("gmail_credentials", "calendar_credentials", "drive_credentials"):
        assert f'op.drop_table("{table}")' not in source


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_09_populated_phase_one_migration_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    user_id = uuid4()
    role = f"h2_09_reader_{uuid4().hex}"
    try:
        _require_migration(database_name, "0005_add_drive_integration")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await _insert_phase_one_user(database, user_id)
        finally:
            await database.close()

        _require_migration(database_name, H2_09_REVISION)
        _require_migration(database_name, H2_09_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert (
                await database.fetchval("SELECT version_num FROM alembic_version") == H2_09_REVISION
            )
            assert await database.fetchval("SELECT count(*) FROM users WHERE id=$1", user_id) == 1
            assert await database.fetchval(
                """
                SELECT bool_and(relrowsecurity AND relforcerowsecurity)
                FROM pg_class
                WHERE oid IN (
                    'connection_backfill_evidence'::regclass,
                    'capability_cutover_evidence'::regclass
                )
                """
            )
            for table in (
                "email_capability_routes",
                "calendar_capability_routes",
                "storage_capability_routes",
            ):
                assert (
                    await database.fetchval(
                        """
                    SELECT count(*) FROM information_schema.columns
                    WHERE table_name=$1 AND column_name='mutation_route'
                    """,
                        table,
                    )
                    == 1
                )
            await database.execute(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS")
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
            await database.execute(
                "GRANT SELECT ON connection_backfill_evidence, "
                f"capability_cutover_evidence TO {role}"
            )
            await database.execute(f"SET ROLE {role}")
            assert await database.fetchval("SELECT count(*) FROM connection_backfill_evidence") == 0
            await database.execute("RESET ROLE")
            await database.execute(f"DROP OWNED BY {role}")
            await database.execute(f"DROP ROLE {role}")
        finally:
            await database.close()

        _require_migration(database_name, H2_08_REVISION, direction="downgrade")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT to_regclass('public.connection_backfill_evidence') IS NULL"
            )
            assert (
                await database.fetchval(
                    """
                SELECT count(*) FROM information_schema.columns
                WHERE table_name='email_capability_routes' AND column_name='mutation_route'
                """
                )
                == 0
            )
            assert await database.fetchval("SELECT count(*) FROM users WHERE id=$1", user_id) == 1
        finally:
            await database.close()
        _require_migration(database_name, H2_09_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_09_threshold_cutover_mutation_control_and_rollback() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_09_REVISION)
        organization_id, workspace_id, _, owner_id, _ = await _seed_business_workspace(
            database_name
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        records = tuple(
            BackfillCandidate(
                workspace_id=workspace_id,
                organization_id=organization_id,
                cell_id=context.tenant.cell_id,
                user_id=owner_id,
                provider_account_id="h2-09@example.test",
                capability=capability,
                source_record_id=f"{capability.value}:{owner_id}",
                source_checksum=(capability.value[0] * 64),
                credential_eligible=True,
            )
            for capability in IntegrationCapability
        )
        async with sessions() as session:
            async with execution.transaction(session, context):
                backfill = ConnectionBackfillService(session, context, authorizer=AllowAuthorizer())
                plan = await backfill.apply(records)
                replay = await backfill.apply(tuple(reversed(records)))
                assert replay == plan
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ConnectionBackfillEvidence)
                    )
                    == 3
                )
                assert (
                    await session.scalar(select(func.min(ConnectionBackfillEvidence.attempt_count)))
                    == 2
                )
        connection_id = plan.connection_id

        async with sessions() as session:
            async with execution.transaction(session, context):
                routing = EmailRoutingRepository(session, context, connection_id=connection_id)
                await routing.set_route(CapabilityRoute.SHADOW)
                for _ in range(10):
                    await routing.record_comparison(EmailOperation.PROFILE, True)
                service = ConnectionCutoverService(
                    session,
                    context,
                    authorization=AllowRouteChanges(),
                    threshold=CutoverThreshold(10, 0),
                )
                await service.set_route(
                    connection_id,
                    IntegrationCapability.EMAIL,
                    route_kind="read",
                    requested=CapabilityRoute.CANONICAL,
                )
                await service.set_route(
                    connection_id,
                    IntegrationCapability.EMAIL,
                    route_kind="mutation",
                    requested=CapabilityRoute.CANONICAL,
                )
                assert await routing.route() is CapabilityRoute.CANONICAL
                assert await routing.mutation_route() is CapabilityRoute.CANONICAL
                await service.set_route(
                    connection_id,
                    IntegrationCapability.EMAIL,
                    route_kind="read",
                    requested=CapabilityRoute.LEGACY,
                )
                await service.set_route(
                    connection_id,
                    IntegrationCapability.EMAIL,
                    route_kind="mutation",
                    requested=CapabilityRoute.LEGACY,
                )
                assert await routing.route() is CapabilityRoute.LEGACY
                assert await routing.mutation_route() is CapabilityRoute.LEGACY
                assert (
                    await session.scalar(
                        select(func.count()).select_from(CapabilityCutoverEvidence)
                    )
                    == 4
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.action == "connection.route_cutover")
                    )
                    == 4
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.event_type == "connection.route.cutover")
                    )
                    == 4
                )
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
