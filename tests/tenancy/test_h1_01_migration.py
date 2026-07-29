"""PostgreSQL migration, backfill, RLS, and rollback verification for H1-01."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATABASE_URL = os.getenv("H1_TEST_DATABASE_URL") or os.getenv(
    "H0_TEST_DATABASE_URL"
)
H1_TABLES = {
    "audit_events",
    "cells",
    "organization_memberships",
    "organizations",
    "outbox_events",
    "workspaces",
}


def _database_url(database_name: str, *, async_sqlalchemy: bool = False) -> str:
    assert SOURCE_DATABASE_URL is not None
    parsed = urlsplit(SOURCE_DATABASE_URL.replace("+asyncpg", ""))
    scheme = "postgresql+asyncpg" if async_sqlalchemy else "postgresql"
    return urlunsplit(
        (scheme, parsed.netloc, f"/{database_name}", parsed.query, parsed.fragment)
    )


def _run_migration(
    database_name: str,
    revision: str,
    *,
    direction: str = "upgrade",
) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = _database_url(
        database_name, async_sqlalchemy=True
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", direction, revision],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


async def _drop_database(connection: asyncpg.Connection, database_name: str) -> None:
    await connection.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = $1 AND pid <> pg_backend_pid()
        """,
        database_name,
    )
    await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_01_upgrade_backfill_isolation_invariants_and_rollback() -> None:
    parsed = urlsplit(SOURCE_DATABASE_URL.replace("+asyncpg", ""))
    source_database = parsed.path.lstrip("/")
    admin_database = "postgres" if source_database != "postgres" else source_database
    database_name = f"h1_01_{uuid4().hex}"
    runtime_role = f"h1_runtime_{uuid4().hex[:16]}"
    admin = await asyncpg.connect(_database_url(admin_database))

    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        _run_migration(database_name, "0005_add_drive_integration")

        database = await asyncpg.connect(_database_url(database_name))
        user_a = uuid4()
        user_b = uuid4()
        try:
            await database.executemany(
                """
                INSERT INTO users (id, email, display_name)
                VALUES ($1, $2, $3)
                """,
                (
                    (user_a, "owner-a@example.test", "Owner A"),
                    (user_b, "owner-b@example.test", "Owner B"),
                ),
            )
        finally:
            await database.close()

        _run_migration(database_name, "0006_h1_org_workspaces")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == "0006_h1_org_workspaces"
            assert set(
                await database.fetch(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'public'
                      AND tablename = ANY($1::text[])
                    """,
                    list(H1_TABLES),
                )
            ) == {(table_name,) for table_name in H1_TABLES}

            assert await database.fetchval("SELECT count(*) FROM cells") == 1
            assert await database.fetchval("SELECT count(*) FROM organizations") == 2
            assert (
                await database.fetchval("SELECT count(*) FROM organization_memberships")
                == 2
            )
            assert await database.fetchval("SELECT count(*) FROM workspaces") == 2
            assert await database.fetchval("SELECT count(*) FROM audit_events") == 2
            assert await database.fetchval("SELECT count(*) FROM outbox_events") == 2
            assert (
                await database.fetchval(
                    """
                    SELECT count(*)
                    FROM organization_memberships
                    WHERE role = 'owner' AND status = 'active'
                    """
                )
                == 2
            )

            workspace_ids = [
                UUID(str(value))
                for value in await database.fetch(
                    "SELECT workspace_id FROM workspaces ORDER BY workspace_id"
                )
                for value in value.values()
            ]
            rls_flags = await database.fetch(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE relname = ANY($1::text[])
                ORDER BY relname
                """,
                ["workspaces", "audit_events", "outbox_events"],
            )
            assert [(row[1], row[2]) for row in rls_flags] == [
                (True, True),
                (True, True),
                (True, True),
            ]

            await database.execute(
                f"CREATE ROLE {runtime_role} NOLOGIN NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            )
            await database.execute(
                f"GRANT USAGE ON SCHEMA public TO {runtime_role}"
            )
            await database.execute(
                f"GRANT SELECT ON workspaces, audit_events, outbox_events "
                f"TO {runtime_role}"
            )

            async with database.transaction():
                await database.execute(f"SET LOCAL ROLE {runtime_role}")
                assert await database.fetchval("SELECT count(*) FROM workspaces") == 0
                await database.execute(
                    "SELECT set_config('atlas.workspace_id', $1, TRUE)",
                    str(workspace_ids[0]),
                )
                assert await database.fetchval("SELECT count(*) FROM workspaces") == 1
                assert await database.fetchval("SELECT count(*) FROM audit_events") == 1
                assert await database.fetchval("SELECT count(*) FROM outbox_events") == 1

            organization_id = await database.fetchval(
                """
                SELECT organization_id
                FROM organization_memberships
                WHERE user_id = $1
                """,
                user_a,
            )
            async with database.transaction():
                await database.execute(
                    """
                    DELETE FROM organization_memberships
                    WHERE organization_id = $1 AND user_id = $2
                    """,
                    organization_id,
                    user_a,
                )
                with pytest.raises(
                    asyncpg.RaiseError,
                    match="organization must retain at least one active owner",
                ):
                    await database.execute("SET CONSTRAINTS ALL IMMEDIATE")

            with pytest.raises(
                asyncpg.RaiseError,
                match="workspace transfer is prohibited in Phase 2",
            ):
                await database.execute(
                    """
                    UPDATE workspaces
                    SET organization_id = $1
                    WHERE workspace_id = $2
                    """,
                    uuid4(),
                    workspace_ids[0],
                )

            with pytest.raises(asyncpg.RaiseError, match="audit events are immutable"):
                await database.execute(
                    """
                    UPDATE audit_events
                    SET outcome = 'changed'
                    WHERE workspace_id = $1
                    """,
                    workspace_ids[0],
                )
        finally:
            await database.close()

        _run_migration(
            database_name,
            "0005_add_drive_integration",
            direction="downgrade",
        )
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval("SELECT count(*) FROM users") == 2
            remaining_h1_tables = await database.fetchval(
                """
                SELECT count(*)
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename = ANY($1::text[])
                """,
                list(H1_TABLES),
            )
            assert remaining_h1_tables == 0
        finally:
            await database.close()
    finally:
        await _drop_database(admin, database_name)
        await admin.execute(f"DROP ROLE IF EXISTS {runtime_role}")
        await admin.close()
