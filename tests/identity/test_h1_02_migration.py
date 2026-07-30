"""PostgreSQL compatibility, atomicity, and rollback evidence for H1-02."""

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
H1_02_REVISION = "0007_h1_canonical_identity"
H1_01_REVISION = "0006_h1_org_workspaces"


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
    environment["DATABASE_URL"] = _database_url(
        database_name,
        async_sqlalchemy=True,
    )
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


async def _create_test_database() -> tuple[asyncpg.Connection, str]:
    assert SOURCE_DATABASE_URL is not None
    parsed = urlsplit(SOURCE_DATABASE_URL.replace("+asyncpg", ""))
    source_database = parsed.path.lstrip("/")
    admin_database = "postgres" if source_database != "postgres" else source_database
    database_name = f"h1_02_{uuid4().hex}"
    admin = await asyncpg.connect(_database_url(admin_database))
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    return admin, database_name


async def _insert_phase_one_dependencies(
    database: asyncpg.Connection,
    user_id: UUID,
    suffix: str,
) -> None:
    project_id = uuid4()
    conversation_id = uuid4()
    await database.execute(
        """
        INSERT INTO users (id, email, display_name)
        VALUES ($1, $2, $3)
        """,
        user_id,
        f"{suffix}@example.test",
        f"User {suffix}",
    )
    await database.execute(
        """
        INSERT INTO projects (id, user_id, name)
        VALUES ($1, $2, $3)
        """,
        project_id,
        user_id,
        f"Project {suffix}",
    )
    await database.execute(
        """
        INSERT INTO conversations (id, user_id, project_id, title)
        VALUES ($1, $2, $3, $4)
        """,
        conversation_id,
        user_id,
        project_id,
        f"Conversation {suffix}",
    )
    await database.execute(
        """
        INSERT INTO gmail_credentials (user_id, encrypted_payload)
        VALUES ($1, $2)
        """,
        user_id,
        f"gmail-{suffix}",
    )
    await database.execute(
        """
        INSERT INTO calendar_credentials (user_id, encrypted_payload)
        VALUES ($1, $2)
        """,
        user_id,
        f"calendar-{suffix}",
    )
    await database.execute(
        """
        INSERT INTO drive_credentials (user_id, encrypted_payload)
        VALUES ($1, $2)
        """,
        user_id,
        f"drive-{suffix}",
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_02_empty_database_upgrade_is_repeatable_and_reversible() -> None:
    admin, database_name = await _create_test_database()
    try:
        _require_migration(database_name, H1_02_REVISION)
        _require_migration(database_name, H1_02_REVISION)

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_02_REVISION
            assert await database.fetchval("SELECT count(*) FROM users") == 0
            assert (
                await database.fetchval(
                    "SELECT count(*) FROM external_identity_links"
                )
                == 0
            )
        finally:
            await database.close()

        _require_migration(
            database_name,
            H1_01_REVISION,
            direction="downgrade",
        )
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                """
                SELECT to_regclass('public.external_identity_links') IS NULL
                """
            )
        finally:
            await database.close()
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_02_preserves_phase_one_ids_and_foreign_keys() -> None:
    admin, database_name = await _create_test_database()
    user_before_h1_01 = uuid4()
    user_after_h1_01 = uuid4()
    try:
        _require_migration(database_name, "0005_add_drive_integration")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await _insert_phase_one_dependencies(
                database,
                user_before_h1_01,
                "before",
            )
        finally:
            await database.close()

        _require_migration(database_name, H1_01_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await _insert_phase_one_dependencies(
                database,
                user_after_h1_01,
                "after",
            )
        finally:
            await database.close()

        _require_migration(database_name, H1_02_REVISION)
        _require_migration(database_name, H1_02_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_02_REVISION
            assert {
                UUID(str(row["id"]))
                for row in await database.fetch("SELECT id FROM users")
            } == {user_before_h1_01, user_after_h1_01}
            for table_name in (
                "calendar_credentials",
                "conversations",
                "drive_credentials",
                "gmail_credentials",
                "projects",
            ):
                assert await database.fetchval(
                    f"SELECT count(*) FROM {table_name}"
                ) == 2

            assert await database.fetchval("SELECT count(*) FROM workspaces") == 2
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM audit_events
                WHERE action = 'identity.migrated'
                  AND details ->> 'migration' = '0007_h1_canonical_identity'
                """
            ) == 2
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM outbox_events
                WHERE event_type = 'atlas.identity.migrated'
                  AND payload ->> 'migration' = '0007_h1_canonical_identity'
                """
            ) == 2

            duplicate_email = "shared-verified@example.test"
            await database.execute(
                """
                UPDATE users
                SET email = $1,
                    email_verified = TRUE,
                    email_verified_at = now(),
                    email_verification_source = 'migration-test'
                """,
                duplicate_email,
            )
            await database.execute(
                """
                INSERT INTO external_identity_links (
                    id,
                    user_id,
                    issuer,
                    subject,
                    email,
                    email_verified,
                    email_verified_at,
                    email_verification_source
                )
                VALUES
                    (
                        $1, $2, 'https://issuer-a.example', 'subject-a',
                        $3, TRUE, now(), 'oidc-claim'
                    ),
                    (
                        $4, $5, 'https://issuer-b.example', 'subject-b',
                        $3, TRUE, now(), 'oidc-claim'
                    )
                """,
                uuid4(),
                user_before_h1_01,
                duplicate_email,
                uuid4(),
                user_after_h1_01,
            )
            assert (
                await database.fetchval(
                    "SELECT count(*) FROM users WHERE email = $1",
                    duplicate_email,
                )
                == 2
            )

            with pytest.raises(asyncpg.UniqueViolationError):
                await database.execute(
                    """
                    INSERT INTO external_identity_links (
                        id, user_id, issuer, subject
                    )
                    VALUES ($1, $2, 'https://issuer-a.example', 'subject-a')
                    """,
                    uuid4(),
                    user_after_h1_01,
                )
            with pytest.raises(asyncpg.CheckViolationError):
                await database.execute(
                    """
                    INSERT INTO external_identity_links (
                        id,
                        user_id,
                        issuer,
                        subject,
                        email,
                        email_verified
                    )
                    VALUES ($1, $2, 'https://issuer-c.example', 'subject-c', $3, TRUE)
                    """,
                    uuid4(),
                    user_after_h1_01,
                    duplicate_email,
                )
        finally:
            await database.close()

        refused_downgrade = _migration(
            database_name,
            H1_01_REVISION,
            direction="downgrade",
        )
        assert refused_downgrade.returncode != 0
        assert "reviewed forward fix" in refused_downgrade.stderr

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_02_REVISION
            assert await database.fetchval(
                "SELECT count(*) FROM external_identity_links"
            ) == 2
            await database.execute("DELETE FROM external_identity_links")
            await database.execute(
                "UPDATE users SET email = id::text || '@rollback.example'"
            )
        finally:
            await database.close()

        _require_migration(
            database_name,
            H1_01_REVISION,
            direction="downgrade",
        )
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval("SELECT count(*) FROM users") == 2
            for table_name in (
                "calendar_credentials",
                "conversations",
                "drive_credentials",
                "gmail_credentials",
                "projects",
            ):
                assert await database.fetchval(
                    f"SELECT count(*) FROM {table_name}"
                ) == 2
            assert await database.fetchval(
                """
                SELECT to_regclass('public.external_identity_links') IS NULL
                """
            )
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM audit_events
                WHERE action = 'identity.migrated'
                """
            ) == 0
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM outbox_events
                WHERE event_type = 'atlas.identity.migrated'
                """
            ) == 0
        finally:
            await database.close()
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_02_upgrade_failure_rolls_back_schema_audit_and_outbox() -> None:
    admin, database_name = await _create_test_database()
    user_id = uuid4()
    try:
        _require_migration(database_name, "0005_add_drive_integration")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await _insert_phase_one_dependencies(database, user_id, "atomic")
        finally:
            await database.close()
        _require_migration(database_name, H1_01_REVISION)

        database = await asyncpg.connect(_database_url(database_name))
        try:
            workspace_id = await database.fetchval(
                "SELECT workspace_id FROM workspaces"
            )
            conflicting_event_id = await database.fetchval(
                "SELECT md5('atlas:outbox:identity-migrated:' || $1)::uuid",
                str(user_id),
            )
            await database.execute(
                """
                INSERT INTO outbox_events (
                    workspace_id,
                    id,
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    aggregate_sequence,
                    payload
                )
                VALUES ($1, $2, 'conflict', 'test', $3, 1, '{}'::jsonb)
                """,
                workspace_id,
                conflicting_event_id,
                uuid4(),
            )
        finally:
            await database.close()

        failed_upgrade = _migration(database_name, H1_02_REVISION)
        assert failed_upgrade.returncode != 0

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_01_REVISION
            assert await database.fetchval(
                """
                SELECT to_regclass('public.external_identity_links') IS NULL
                """
            )
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM audit_events
                WHERE action = 'identity.migrated'
                """
            ) == 0
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name IN (
                      'email_verified',
                      'status',
                      'updated_at',
                      'version'
                  )
                """
            ) == 0
            await database.execute(
                """
                DELETE FROM outbox_events
                WHERE event_type = 'conflict'
                """
            )
        finally:
            await database.close()

        _require_migration(database_name, H1_02_REVISION)
        _require_migration(database_name, H1_02_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_02_REVISION
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM audit_events
                WHERE action = 'identity.migrated'
                """
            ) == 1
            assert await database.fetchval(
                """
                SELECT count(*)
                FROM outbox_events
                WHERE event_type = 'atlas.identity.migrated'
                """
            ) == 1
        finally:
            await database.close()
    finally:
        await _drop_database(admin, database_name)
        await admin.close()
