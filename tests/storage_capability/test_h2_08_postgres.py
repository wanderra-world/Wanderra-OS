from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest

from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
)

H2_08 = "0020_h2_storage_capability"
H2_07 = "0019_h2_calendar_capability"


@pytest.mark.skipif(SOURCE_DATABASE_URL is None, reason="PostgreSQL URL required")
async def test_h2_08_migration_forced_rls_and_empty_rollback() -> None:
    admin, name = await _create_database()
    try:
        _require_migration(name, H2_08)
        _require_migration(name, H2_08)
        database = await asyncpg.connect(_database_url(name))
        try:
            assert await database.fetchval("SELECT version_num FROM alembic_version") == H2_08
            for table in (
                "storage_capability_routes",
                "storage_shadow_comparisons",
            ):
                row = await database.fetchrow(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE oid=$1::regclass",
                    table,
                )
                assert row["relrowsecurity"] and row["relforcerowsecurity"]
        finally:
            await database.close()
        _require_migration(name, H2_07, direction="downgrade")
        _require_migration(name, H2_08)
    finally:
        await _drop_database(admin, name)
        await admin.close()


def test_h2_08_guarded_rollback() -> None:
    source = (
        Path(__file__).parents[2] / "alembic/versions/0020_add_storage_capability_routing.py"
    ).read_text()
    assert "cannot downgrade H2-08 with routing evidence" in source
