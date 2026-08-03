"""PostgreSQL, RLS, migration, and rollback evidence for H3-09."""

import asyncpg
import pytest

from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _drop_database,
    _migration,
    _require_migration,
    _seed_business_workspace,
)

REVISION = "0030_h3_notification_center"
PREVIOUS = "0029_h3_workflow_approval"
TABLES = (
    "notification_templates",
    "notification_template_versions",
    "notification_preferences",
    "notification_intents",
    "notification_digests",
    "notification_attempts",
    "notification_receipts",
    "notification_inbox_entries",
)


def _database_url(name: str) -> str:
    assert SOURCE_DATABASE_URL is not None
    return SOURCE_DATABASE_URL.rsplit("/", 1)[0] + "/" + name


@pytest.mark.skipif(SOURCE_DATABASE_URL is None, reason="PostgreSQL URL is required")
async def test_h3_09_forced_rls_and_empty_rollback() -> None:
    admin, name = await _create_database()
    try:
        _require_migration(name, REVISION)
        database = await asyncpg.connect(_database_url(name))
        try:
            rows = await database.fetch(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY($1::text[])",
                list(TABLES),
            )
            assert {row["relname"] for row in rows} == set(TABLES)
            assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)
        finally:
            await database.close()
        _require_migration(name, PREVIOUS, direction="downgrade")
        _require_migration(name, REVISION)
    finally:
        await _drop_database(admin, name)
        await admin.close()


@pytest.mark.skipif(SOURCE_DATABASE_URL is None, reason="PostgreSQL URL is required")
async def test_h3_09_populated_rollback_fails_closed() -> None:
    admin, name = await _create_database()
    try:
        _require_migration(name, REVISION)
        org, workspace, _, user, _ = await _seed_business_workspace(name)
        database = await asyncpg.connect(_database_url(name))
        try:
            cell = await database.fetchval(
                "SELECT cell_id FROM workspaces WHERE workspace_id=$1", workspace
            )
            await database.execute(
                "INSERT INTO notification_templates "
                "(organization_id,workspace_id,cell_id,id,template_key,created_by_user_id) "
                "VALUES ($1,$2,$3,gen_random_uuid(),'test',$4)",
                org,
                workspace,
                cell,
                user,
            )
        finally:
            await database.close()
        result = _migration(name, PREVIOUS, direction="downgrade")
        assert result.returncode != 0
        assert "reviewed forward fix" in result.stderr
    finally:
        await _drop_database(admin, name)
        await admin.close()
