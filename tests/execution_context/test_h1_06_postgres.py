"""PostgreSQL propagation, RLS, role, replay, and rollback evidence for H1-06."""

from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.execution_context import (
    ActorContext,
    ContextBoundRepository,
    ExecutionContext,
    ExecutionContextError,
    ExecutionContextService,
    RequestContext,
    TenantContext,
)
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _migration,
    _require_migration,
    _seed_business_workspace,
)

H1_06_BASE_REVISION = "0010_h1_authorization"
H1_05_PARENT_REVISION = "0009_h1_workspace_memberships"
RUNTIME_ROLE = "h1_06_runtime"
WORKER_ROLE = "h1_06_worker"


class MembershipProbe(ContextBoundRepository):
    async def count(self, workspace_id: UUID) -> int:
        self.require_workspace(workspace_id)
        return int(
            await self.session.scalar(
                text(
                    """
                    SELECT count(*) FROM workspace_memberships
                    WHERE workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": workspace_id},
            )
            or 0
        )


def _context(
    *,
    organization_id: UUID,
    workspace_id: UUID,
    cell_id: UUID,
    actor_id: UUID,
) -> ExecutionContext:
    return ExecutionContext(
        request=RequestContext(
            request_id="h1-06-request",
            correlation_id="h1-06-correlation",
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
async def test_h1_06_transaction_propagation_rls_replay_and_pool_reset() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H1_06_BASE_REVISION)
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
            await database.execute(f"DROP ROLE IF EXISTS {RUNTIME_ROLE}")
            await database.execute(
                f"CREATE ROLE {RUNTIME_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(
                f"GRANT USAGE ON SCHEMA public TO {RUNTIME_ROLE}"
            )
            await database.execute(
                f"GRANT SELECT ON workspace_memberships TO {RUNTIME_ROLE}"
            )
        finally:
            await database.close()

        context = _context(
            organization_id=organization_id,
            workspace_id=workspace_id,
            cell_id=cell_id,
            actor_id=owner_id,
        )
        service = ExecutionContextService()
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True),
            pool_size=1,
            max_overflow=0,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        for _ in range(2):
            async with sessions() as session:
                async with service.transaction(session, context):
                    await session.execute(text(f"SET LOCAL ROLE {RUNTIME_ROLE}"))
                    probe = MembershipProbe(session, context)
                    assert await probe.count(workspace_id) == 1
                    settings = (
                        await session.execute(
                            text(
                                """
                                SELECT
                                  current_setting('atlas.workspace_id', TRUE),
                                  current_setting('atlas.actor_id', TRUE),
                                  current_setting('atlas.correlation_id', TRUE),
                                  current_setting(
                                    'atlas.authorization_decision_id', TRUE
                                  )
                                """
                            )
                        )
                    ).one()
                    assert settings == (
                        str(workspace_id),
                        str(owner_id),
                        "h1-06-correlation",
                        str(context.actor.authorization_decision_id),
                    )
                assert "atlas.execution_context" not in session.info

        async with sessions.begin() as session:
            leaked = await session.scalar(
                text(
                    """
                    SELECT NULLIF(
                      current_setting('atlas.workspace_id', TRUE), ''
                    )
                    """
                )
            )
            assert leaked is None

        mismatched = ExecutionContext(
            request=context.request,
            actor=context.actor,
            tenant=TenantContext(
                organization_id=uuid4(),
                workspace_id=second_workspace_id,
                cell_id=cell_id,
            ),
        )
        async with sessions() as session:
            with pytest.raises(ExecutionContextError, match="does not match"):
                async with service.transaction(session, mismatched):
                    pass
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.execute(f"DROP ROLE IF EXISTS {RUNTIME_ROLE}")
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_06_runtime_roles_and_schema_free_rollback_rehearsal() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H1_06_BASE_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            for role in (RUNTIME_ROLE, WORKER_ROLE):
                await database.execute(f"DROP ROLE IF EXISTS {role}")
                await database.execute(
                    f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOBYPASSRLS"
                )
                attributes = await database.fetchrow(
                    """
                    SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
                    FROM pg_roles WHERE rolname = $1
                    """,
                    role,
                )
                assert dict(attributes) == {
                    "rolsuper": False,
                    "rolcreatedb": False,
                    "rolcreaterole": False,
                    "rolbypassrls": False,
                }
                owned_tables = await database.fetchval(
                    """
                    SELECT count(*)
                    FROM pg_class
                    WHERE relkind IN ('r', 'p')
                      AND relowner = (SELECT oid FROM pg_roles WHERE rolname = $1)
                    """,
                    role,
                )
                assert owned_tables == 0
        finally:
            await database.close()

        downgrade = _migration(
            database_name,
            H1_05_PARENT_REVISION,
            direction="downgrade",
        )
        assert downgrade.returncode == 0, downgrade.stderr
        _require_migration(database_name, H1_06_BASE_REVISION)
    finally:
        await _drop_database(admin, database_name)
        for role in (RUNTIME_ROLE, WORKER_ROLE):
            await admin.execute(f"DROP ROLE IF EXISTS {role}")
        await admin.close()
