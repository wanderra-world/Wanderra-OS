"""PostgreSQL, RLS, integration, revocation, and rollback evidence for H1-05."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.authorization.contracts import (
    AuthorizationRequest,
    DecisionEffect,
    ReasonCode,
)
from app.authorization.service import AuthorizationService
from app.identity.lifecycle import IdentityLifecycleService
from app.memberships.repository import WorkspaceMembershipRepository
from app.memberships.service import WorkspaceMembershipService
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

H1_05_REVISION = "0010_h1_authorization"
H1_04_REVISION = "0009_h1_workspace_memberships"
RLS_ROLE = "h1_05_tenant_reader"


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_05_migration_catalog_rls_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    first_user_id = uuid4()
    second_user_id = uuid4()
    try:
        _require_migration(database_name, "0005_add_drive_integration")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await _insert_phase_one_user(database, first_user_id)
            await _insert_phase_one_user(database, second_user_id)
        finally:
            await database.close()

        _require_migration(database_name, H1_05_REVISION)
        _require_migration(database_name, H1_05_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_05_REVISION
            assert await database.fetchval("SELECT count(*) FROM permissions") == 5
            assert await database.fetchval(
                "SELECT count(*) FROM role_permissions"
            ) == 23
            assert await database.fetchval(
                """
                SELECT count(*) FROM fixed_membership_roles
                WHERE version = 1 AND active
                """
            ) == 6
            rls = await database.fetchrow(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid = 'workspace_memberships'::regclass
                """
            )
            assert rls and rls["relrowsecurity"] and rls["relforcerowsecurity"]

            first_workspace = await database.fetchval(
                """
                SELECT workspace_id FROM workspace_memberships
                WHERE user_id = $1
                """,
                first_user_id,
            )
            await database.execute(f"DROP ROLE IF EXISTS {RLS_ROLE}")
            await database.execute(
                f"CREATE ROLE {RLS_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {RLS_ROLE}")
            await database.execute(
                f"""
                GRANT SELECT ON workspace_memberships, role_permissions, permissions
                TO {RLS_ROLE}
                """
            )
            async with database.transaction():
                await database.execute(f"SET LOCAL ROLE {RLS_ROLE}")
                assert await database.fetchval(
                    """
                    SELECT count(*)
                    FROM workspace_memberships
                    JOIN role_permissions USING (role_key, role_version)
                    """
                ) == 0
                await database.execute(
                    "SELECT set_config('atlas.workspace_id', $1, TRUE)",
                    str(first_workspace),
                )
                assert await database.fetchval(
                    """
                    SELECT count(DISTINCT workspace_memberships.workspace_id)
                    FROM workspace_memberships
                    JOIN role_permissions USING (role_key, role_version)
                    """
                ) == 1

            await database.execute(
                """
                UPDATE permissions
                SET active = FALSE
                WHERE permission_key = 'read_content' AND version = 1
                """
            )
        finally:
            await database.close()

        refused = _migration(database_name, H1_04_REVISION, direction="downgrade")
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_05_REVISION
            await database.execute(
                """
                UPDATE permissions
                SET active = TRUE
                WHERE permission_key = 'read_content' AND version = 1
                """
            )
        finally:
            await database.close()

        _require_migration(database_name, H1_04_REVISION, direction="downgrade")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT to_regclass('public.permissions') IS NULL"
            )
            assert await database.fetchval(
                "SELECT to_regclass('public.role_permissions') IS NULL"
            )
            assert await database.fetchval(
                "SELECT count(*) FROM workspace_memberships"
            ) == 2
        finally:
            await database.close()
        _require_migration(database_name, H1_05_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.execute(f"DROP ROLE IF EXISTS {RLS_ROLE}")
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_05_authorization_matrix_audit_and_immediate_revocation() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H1_05_REVISION)
        (
            organization_id,
            workspace_id,
            second_workspace_id,
            owner_id,
            member_id,
        ) = await _seed_business_workspace(database_name)
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)

        async with sessions.begin() as session:
            repository = WorkspaceMembershipRepository(session)
            owner = await repository.get_by_user(
                workspace_id=workspace_id,
                user_id=owner_id,
            )
            assert owner is not None
            member = await WorkspaceMembershipService(session).create_active(
                workspace_id=workspace_id,
                organization_id=organization_id,
                user_id=member_id,
                role_key="member",
                actor_user_id=owner_id,
                now=now,
            )
            member_membership_id = member.id
            member_session = await IdentityLifecycleService(session).issue_session(
                workspace_id=workspace_id,
                user_id=member_id,
                device_id="h1-05-member",
                authentication_strength="mfa",
                mfa_authenticated_at=now,
                expires_at=now + timedelta(hours=1),
                now=now,
            )

        def request(
            permission_key: str,
            *,
            actor_id=member_id,
            session_id=member_session.record_id,
            membership_id=member_membership_id,
            requested_workspace_id=workspace_id,
            membership_workspace_id=workspace_id,
        ) -> AuthorizationRequest:
            return AuthorizationRequest(
                actor_id=actor_id,
                session_id=session_id,
                organization_id=organization_id,
                requested_workspace_id=requested_workspace_id,
                membership_workspace_id=membership_workspace_id,
                membership_id=membership_id,
                permission_key=permission_key,
                request_reference=f"h1-05:{permission_key}",
            )

        async with sessions.begin() as session:
            service = AuthorizationService(session)
            allowed = await service.authorize(request("update_content"), now=now)
            denied = await service.authorize(request("delete_content"), now=now)
            unknown = await service.authorize(request("unknown"), now=now)
            mismatch = await service.authorize(
                request(
                    "read_content",
                    requested_workspace_id=second_workspace_id,
                    membership_workspace_id=workspace_id,
                ),
                now=now,
            )
            assert allowed.effect is DecisionEffect.ALLOW
            assert denied.reason is ReasonCode.EXPLICIT_DENY
            assert unknown.reason is ReasonCode.UNKNOWN_PERMISSION
            assert mismatch.reason is ReasonCode.WORKSPACE_MISMATCH

        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                """
                INSERT INTO role_permissions (
                    role_key, role_version, permission_key,
                    permission_version, effect
                )
                VALUES ('member', 1, 'update_content', 1, 'deny')
                """
            )
        finally:
            await database.close()
        async with sessions.begin() as session:
            explicit_override = await AuthorizationService(session).authorize(
                request("update_content"),
                now=now + timedelta(minutes=1),
            )
            assert explicit_override.reason is ReasonCode.EXPLICIT_DENY

        async with sessions.begin() as session:
            await IdentityLifecycleService(session).revoke_session(
                workspace_id=workspace_id,
                session_id=member_session.record_id,
                reason="h1-05-test",
                now=now + timedelta(minutes=2),
            )
        async with sessions.begin() as session:
            revoked = await AuthorizationService(session).authorize(
                request("read_content"),
                now=now + timedelta(minutes=3),
            )
            assert revoked.reason is ReasonCode.INVALID_SESSION

        async with sessions.begin() as session:
            replacement_session = await IdentityLifecycleService(session).issue_session(
                workspace_id=workspace_id,
                user_id=member_id,
                device_id="h1-05-member-replacement",
                authentication_strength="mfa",
                mfa_authenticated_at=now + timedelta(minutes=4),
                expires_at=now + timedelta(hours=1),
                now=now + timedelta(minutes=4),
            )
            await WorkspaceMembershipService(session).set_status(
                workspace_id=workspace_id,
                membership_id=member_membership_id,
                status="suspended",
                actor_user_id=owner_id,
                now=now + timedelta(minutes=4),
            )
        async with sessions.begin() as session:
            inactive = await AuthorizationService(session).authorize(
                request(
                    "read_content",
                    session_id=replacement_session.record_id,
                ),
                now=now + timedelta(minutes=5),
            )
            assert inactive.reason is ReasonCode.INVALID_MEMBERSHIP

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                """
                SELECT count(*) FROM audit_events
                WHERE action = 'authorization.decided'
                """
            ) == 7
            assert await database.fetchval(
                """
                SELECT count(*) FROM outbox_events
                WHERE event_type = 'authorization.decided'
                """
            ) == 7
            details = await database.fetch(
                """
                SELECT details FROM audit_events
                WHERE action = 'authorization.decided'
                """
            )
            assert all("session_id" not in row["details"] for row in details)
            assert all("actor_id" not in row["details"] for row in details)
        finally:
            await database.close()

        refused = _migration(database_name, H1_04_REVISION, direction="downgrade")
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
