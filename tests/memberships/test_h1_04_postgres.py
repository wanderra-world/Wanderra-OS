"""PostgreSQL, RLS, lifecycle, concurrency, and rollback evidence for H1-04."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.identity.lifecycle import InvalidLifecycleTokenError
from app.memberships.contracts import MembershipLifecycleError
from app.memberships.repository import WorkspaceMembershipRepository
from app.memberships.service import WorkspaceMembershipService

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATABASE_URL = os.getenv("H1_TEST_DATABASE_URL") or os.getenv(
    "H0_TEST_DATABASE_URL"
)
H1_04_REVISION = "0009_h1_workspace_memberships"
H1_03_REVISION = "0008_h1_identity_lifecycle"


def _database_url(database_name: str, *, async_sqlalchemy: bool = False) -> str:
    assert SOURCE_DATABASE_URL is not None
    parsed = urlsplit(SOURCE_DATABASE_URL.replace("+asyncpg", ""))
    scheme = "postgresql+asyncpg" if async_sqlalchemy else "postgresql"
    return urlunsplit(
        (scheme, parsed.netloc, f"/{database_name}", parsed.query, parsed.fragment)
    )


def _migration(
    database_name: str,
    revision: str,
    *,
    direction: str = "upgrade",
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = _database_url(database_name, async_sqlalchemy=True)
    return subprocess.run(
        [sys.executable, "-m", "alembic", direction, revision],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def _require_migration(
    database_name: str,
    revision: str,
    *,
    direction: str = "upgrade",
) -> None:
    result = _migration(database_name, revision, direction=direction)
    assert result.returncode == 0, result.stderr


async def _create_database() -> tuple[asyncpg.Connection, str]:
    assert SOURCE_DATABASE_URL is not None
    parsed = urlsplit(SOURCE_DATABASE_URL.replace("+asyncpg", ""))
    source_database = parsed.path.lstrip("/")
    admin_database = "postgres" if source_database != "postgres" else source_database
    database_name = f"h1_04_{uuid4().hex}"
    admin = await asyncpg.connect(_database_url(admin_database))
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    return admin, database_name


async def _drop_database(admin: asyncpg.Connection, database_name: str) -> None:
    await admin.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = $1 AND pid <> pg_backend_pid()
        """,
        database_name,
    )
    await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')


async def _insert_phase_one_user(
    database: asyncpg.Connection,
    user_id: UUID,
) -> None:
    await database.execute(
        "INSERT INTO users (id, email) VALUES ($1, $2)",
        user_id,
        f"{user_id}@example.test",
    )


async def _seed_business_workspace(
    database_name: str,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    organization_id = uuid4()
    workspace_id = uuid4()
    second_workspace_id = uuid4()
    owner_id = uuid4()
    member_id = uuid4()
    database = await asyncpg.connect(_database_url(database_name))
    try:
        async with database.transaction():
            for user_id in (owner_id, member_id):
                await database.execute(
                    """
                    INSERT INTO users (id, email, display_name)
                    VALUES ($1, $2, 'H1-04 User')
                    """,
                    user_id,
                    f"{user_id}@example.test",
                )
            cell_id = await database.fetchval(
                "SELECT id FROM cells ORDER BY created_at LIMIT 1"
            )
            if cell_id is None:
                cell_id = uuid4()
                await database.execute(
                    """
                    INSERT INTO cells (id, key, region)
                    VALUES ($1, $2, 'test')
                    """,
                    cell_id,
                    f"test-{cell_id}",
                )
            await database.execute(
                """
                INSERT INTO organizations (id, organization_type, name)
                VALUES ($1, 'business', 'H1-04 Business')
                """,
                organization_id,
            )
            await database.execute(
                """
                INSERT INTO organization_memberships (
                    organization_id, user_id, role, status
                )
                VALUES ($1, $2, 'owner', 'active')
                """,
                organization_id,
                owner_id,
            )
            for current_workspace_id, suffix in (
                (workspace_id, "primary"),
                (second_workspace_id, "secondary"),
            ):
                await database.execute(
                    """
                    INSERT INTO workspaces (
                        workspace_id, organization_id, cell_id, name, slug
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    current_workspace_id,
                    organization_id,
                    cell_id,
                    f"H1-04 {suffix}",
                    f"h1-04-{suffix}-{current_workspace_id}",
                )
                await database.execute(
                    """
                    INSERT INTO workspace_memberships (
                        workspace_id, id, organization_id, user_id, role_key,
                        role_version, status, version, activated_at, origin
                    )
                    VALUES (
                        $1, $2, $3, $4, 'workspace_owner',
                        1, 'active', 1, now(), 'direct'
                    )
                    """,
                    current_workspace_id,
                    uuid4(),
                    organization_id,
                    owner_id,
                )
        return (
            organization_id,
            workspace_id,
            second_workspace_id,
            owner_id,
            member_id,
        )
    finally:
        await database.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_04_migration_backfill_rls_invariants_and_rollback() -> None:
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
        _require_migration(database_name, H1_04_REVISION)
        _require_migration(database_name, H1_04_REVISION)

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_04_REVISION
            assert await database.fetchval(
                "SELECT count(*) FROM fixed_membership_roles"
            ) == 6
            assert await database.fetchval(
                "SELECT count(*) FROM workspace_memberships"
            ) == 2
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM workspace_memberships
                WHERE role_key = 'workspace_owner'
                  AND role_version = 1
                  AND status = 'active'
                  AND origin = 'migration'
                """
            ) == 2
            rls = await database.fetchrow(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid = 'workspace_memberships'::regclass
                """
            )
            assert rls and rls["relrowsecurity"] and rls["relforcerowsecurity"]

            with pytest.raises(asyncpg.RaiseError, match="active workspace owner"):
                async with database.transaction():
                    await database.execute(
                        """
                        UPDATE workspace_memberships
                        SET role_key = 'workspace_admin'
                        WHERE user_id = $1
                        """,
                        first_user_id,
                    )

            first_workspace = await database.fetchval(
                """
                SELECT workspace_id
                FROM workspace_memberships
                WHERE user_id = $1
                """,
                first_user_id,
            )
            second_organization = await database.fetchval(
                """
                SELECT organization_id
                FROM workspace_memberships
                WHERE user_id = $1
                """,
                second_user_id,
            )
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await database.execute(
                    """
                    UPDATE workspace_memberships
                    SET organization_id = $1
                    WHERE workspace_id = $2
                    """,
                    second_organization,
                    first_workspace,
                )

            await database.execute("DROP ROLE IF EXISTS h1_04_tenant_reader")
            await database.execute(
                "CREATE ROLE h1_04_tenant_reader NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(
                "GRANT USAGE ON SCHEMA public TO h1_04_tenant_reader"
            )
            await database.execute(
                """
                GRANT SELECT ON workspaces, workspace_memberships
                TO h1_04_tenant_reader
                """
            )
            async with database.transaction():
                await database.execute("SET LOCAL ROLE h1_04_tenant_reader")
                assert await database.fetchval(
                    "SELECT count(*) FROM workspace_memberships"
                ) == 0
                await database.execute(
                    "SELECT set_config('atlas.workspace_id', $1, TRUE)",
                    str(first_workspace),
                )
                assert await database.fetchval(
                    "SELECT count(*) FROM workspace_memberships"
                ) == 1
        finally:
            await database.close()

        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                """
                UPDATE workspace_memberships
                SET origin = 'direct'
                WHERE user_id = $1
                """,
                first_user_id,
            )
        finally:
            await database.close()
        refused = _migration(database_name, H1_03_REVISION, direction="downgrade")
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_04_REVISION
            await database.execute(
                "UPDATE workspace_memberships SET origin = 'migration'"
            )
        finally:
            await database.close()
        _require_migration(database_name, H1_03_REVISION, direction="downgrade")

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT to_regclass('public.workspace_memberships') IS NULL"
            )
            assert await database.fetchval(
                "SELECT to_regclass('public.fixed_membership_roles') IS NULL"
            )
            assert await database.fetchval(
                """
                SELECT count(*) FROM audit_events
                WHERE action = 'membership.migrated'
                """
            ) == 0
        finally:
            await database.close()
        _require_migration(database_name, H1_04_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_04_repository_invitation_lifecycle_and_concurrency() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H1_04_REVISION)
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
            invitation = await WorkspaceMembershipService(session).invite(
                workspace_id=workspace_id,
                organization_id=organization_id,
                user_id=member_id,
                role_key="member",
                invited_by_user_id=owner_id,
                expires_at=now + timedelta(hours=2),
                now=now,
            )

        async def accept_once() -> str:
            try:
                async with sessions.begin() as session:
                    await WorkspaceMembershipService(session).accept_invitation(
                        workspace_id=workspace_id,
                        raw_secret=invitation.raw_secret,
                        user_id=member_id,
                        now=now + timedelta(minutes=1),
                    )
                return "accepted"
            except (InvalidLifecycleTokenError, MembershipLifecycleError):
                return "denied"

        assert sorted(await asyncio.gather(accept_once(), accept_once())) == [
            "accepted",
            "denied",
        ]

        async with sessions.begin() as session:
            repository = WorkspaceMembershipRepository(session)
            memberships = await repository.list_for_workspace(
                workspace_id=workspace_id
            )
            assert len(memberships) == 2
            member = await repository.get_by_user(
                workspace_id=workspace_id,
                user_id=member_id,
            )
            assert member is not None
            assert member.status == "active"
            assert member.role_key == "member"
            member_membership_id = member.id

        async with sessions.begin() as session:
            service = WorkspaceMembershipService(session)
            changed = await service.change_role(
                workspace_id=workspace_id,
                membership_id=member_membership_id,
                role_key="workspace_admin",
                actor_user_id=owner_id,
            )
            assert changed.role_key == "workspace_admin"
            await service.set_status(
                workspace_id=workspace_id,
                membership_id=member_membership_id,
                status="suspended",
                actor_user_id=owner_id,
            )
        async with sessions.begin() as session:
            await WorkspaceMembershipService(session).set_status(
                workspace_id=workspace_id,
                membership_id=member_membership_id,
                status="active",
                actor_user_id=owner_id,
            )

        third_owner_id = uuid4()
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                "INSERT INTO users (id, email) VALUES ($1, $2)",
                third_owner_id,
                f"{third_owner_id}@example.test",
            )
        finally:
            await database.close()
        async with sessions.begin() as session:
            second_owner = await WorkspaceMembershipService(session).create_active(
                workspace_id=workspace_id,
                organization_id=organization_id,
                user_id=third_owner_id,
                role_key="workspace_owner",
                actor_user_id=owner_id,
                now=now,
            )
            original_owner = await WorkspaceMembershipRepository(session).get_by_user(
                workspace_id=workspace_id,
                user_id=owner_id,
            )
            assert original_owner is not None
            original_owner_id = original_owner.id

        async def revoke_owner(membership_id: UUID) -> str:
            try:
                async with sessions.begin() as session:
                    await WorkspaceMembershipService(session).set_status(
                        workspace_id=workspace_id,
                        membership_id=membership_id,
                        status="revoked",
                        actor_user_id=owner_id,
                        reason="concurrency-test",
                        now=now + timedelta(minutes=2),
                    )
                return "revoked"
            except MembershipLifecycleError:
                return "denied"

        assert sorted(
            await asyncio.gather(
                revoke_owner(original_owner_id),
                revoke_owner(second_owner.id),
            )
        ) == ["denied", "revoked"]

        async with sessions.begin() as session:
            active_owners = [
                membership
                for membership in await WorkspaceMembershipRepository(
                    session
                ).list_for_workspace(workspace_id=workspace_id)
                if membership.status == "active"
                and membership.role_key == "workspace_owner"
            ]
            assert len(active_owners) == 1
            assert (
                await WorkspaceMembershipRepository(session).get_by_user(
                    workspace_id=second_workspace_id,
                    user_id=member_id,
                )
                is None
            )

        database = await asyncpg.connect(_database_url(database_name))
        try:
            admin_id = uuid4()
            await database.execute(
                "INSERT INTO users (id, email) VALUES ($1, $2)",
                admin_id,
                f"{admin_id}@example.test",
            )
            await database.execute(
                """
                INSERT INTO organization_memberships (
                    organization_id, user_id, role, status
                )
                VALUES ($1, $2, 'admin', 'active')
                """,
                organization_id,
                admin_id,
            )
            assert await database.fetchval(
                """
                SELECT count(*) FROM workspace_memberships
                WHERE workspace_id = $1 AND user_id = $2
                """,
                workspace_id,
                admin_id,
            ) == 0
        finally:
            await database.close()
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
