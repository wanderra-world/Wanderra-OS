from __future__ import annotations

import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.email_capability import EmailOperation, EmailRoute
from app.email_capability.models import EmailShadowComparison
from app.email_capability.repository import EmailRoutingRepository
from app.email_capability.service import EmailRouteControlService
from app.execution_context import ExecutionContextService
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
    _seed_business_workspace,
)
from tests.provider_mirrors.test_h2_04_postgres import _seed_connection

H2_06_REVISION = "0018_h2_email_capability"
H2_05_REVISION = "0017_h2_provider_mirrors"


class AllowRouteChanges:
    async def require(self, permission: str) -> None:
        assert permission == "manage_workspace"


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_06_additive_migration_forced_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H2_06_REVISION)
        _require_migration(database_name, H2_06_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H2_06_REVISION
            for table in (
                "email_capability_routes",
                "email_shadow_comparisons",
            ):
                row = await database.fetchrow(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class WHERE oid = $1::regclass
                    """,
                    table,
                )
                assert row and row["relrowsecurity"] and row["relforcerowsecurity"]
        finally:
            await database.close()
        _require_migration(database_name, H2_05_REVISION, direction="downgrade")
        _require_migration(database_name, H2_06_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


def test_h2_06_migration_has_guarded_non_empty_rollback() -> None:
    source = (
        Path(__file__).parents[2]
        / "alembic/versions/0018_add_email_capability_routing.py"
    ).read_text()
    assert "cannot downgrade H2-06 with routing evidence" in source
    assert "FORCE ROW LEVEL SECURITY" in source


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_06_routing_audit_outbox_shadow_and_workspace_boundary() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_06_REVISION)
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
        connection_id = await _seed_connection(
            sessions, execution, context
        )

        async with sessions() as session:
            async with execution.transaction(session, context):
                repository = EmailRoutingRepository(
                    session, context, connection_id=connection_id
                )
                assert await repository.route() is EmailRoute.LEGACY
                await EmailRouteControlService(
                    session,
                    context,
                    connection_id=connection_id,
                    authorization=AllowRouteChanges(),
                ).set_route(EmailRoute.SHADOW)
                assert await repository.route() is EmailRoute.SHADOW
                await repository.record_comparison(EmailOperation.PROFILE, True)
                assert await session.scalar(
                    select(func.count())
                    .select_from(EmailShadowComparison)
                    .where(EmailShadowComparison.workspace_id == workspace_id)
                ) == 1
                assert await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "email.route_changed")
                ) == 1
                assert await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.event_type == "email.route.changed")
                ) == 1
                with pytest.raises(RuntimeError, match="cross-workspace"):
                    repository.require_workspace(uuid.uuid4())
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
