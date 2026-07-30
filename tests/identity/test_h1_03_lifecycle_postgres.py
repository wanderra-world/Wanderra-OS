"""PostgreSQL lifecycle, concurrency, RLS, and rollback evidence for H1-03."""

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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.identity.lifecycle import (
    IdentityLifecycleError,
    IdentityLifecycleService,
    InvalidLifecycleTokenError,
    InvalidSessionError,
    StrongAuthenticationRequiredError,
)
from app.identity.lifecycle_models import (
    IdentityLifecycleToken,
    IdentitySession,
    SecurityNotification,
)
from app.tenancy.models import AuditEvent, OutboxEvent

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATABASE_URL = os.getenv("H1_TEST_DATABASE_URL") or os.getenv(
    "H0_TEST_DATABASE_URL"
)
H1_03_REVISION = "0008_h1_identity_lifecycle"
H1_02_REVISION = "0007_h1_canonical_identity"


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
    database_name = f"h1_03_{uuid4().hex}"
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


async def _seed_identity(database_name: str) -> tuple[UUID, UUID, UUID]:
    user_id = uuid4()
    link_id = uuid4()
    database = await asyncpg.connect(_database_url(database_name))
    try:
        async with database.transaction():
            await database.execute(
                """
                INSERT INTO users (
                    id, email, email_verified, email_verified_at,
                    email_verification_source, display_name
                )
                VALUES ($1, $2, TRUE, now(), 'h1-03-test', 'H1-03 User')
                """,
                user_id,
                f"{user_id}@example.test",
            )
            workspace_id = await database.fetchval(
                "SELECT workspace_id FROM workspaces ORDER BY created_at LIMIT 1"
            )
            if workspace_id is None:
                cell_id = uuid4()
                organization_id = uuid4()
                workspace_id = uuid4()
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
                    VALUES ($1, 'business', 'H1-03 Test')
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
                    user_id,
                )
                await database.execute(
                    """
                    INSERT INTO workspaces (
                        workspace_id, organization_id, cell_id, name, slug
                    )
                    VALUES ($1, $2, $3, 'H1-03 Test', $4)
                    """,
                    workspace_id,
                    organization_id,
                    cell_id,
                    f"h1-03-{workspace_id}",
                )
            await database.execute(
                """
                INSERT INTO external_identity_links (
                    id, user_id, issuer, subject, email, email_verified,
                    email_verified_at, email_verification_source
                )
                VALUES ($1, $2, 'https://issuer.example', $3, $4, TRUE, now(), 'oidc')
                """,
                link_id,
                user_id,
                str(user_id),
                f"{user_id}@example.test",
            )
        return UUID(str(workspace_id)), user_id, link_id
    finally:
        await database.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_03_migration_rls_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H1_03_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_03_REVISION
            for table_name in (
                "identity_sessions",
                "identity_lifecycle_tokens",
                "security_notifications",
            ):
                row = await database.fetchrow(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE oid = to_regclass($1)
                    """,
                    f"public.{table_name}",
                )
                assert row and row["relrowsecurity"] and row["relforcerowsecurity"]
                assert await database.fetchval(
                    "SELECT count(*) FROM pg_policies WHERE tablename = $1",
                    table_name,
                ) == 1

            workspace_id, user_id, _ = await _seed_identity(database_name)
            await database.execute(
                """
                INSERT INTO identity_sessions (
                    workspace_id, id, user_id, token_hash, device_id,
                    authentication_strength, authenticated_at, last_seen_at, expires_at
                )
                VALUES ($1, $2, $3, repeat('a', 64), 'device', 'password',
                        now(), now(), now() + interval '1 hour')
                """,
                workspace_id,
                uuid4(),
                user_id,
            )
        finally:
            await database.close()

        refused = _migration(database_name, H1_02_REVISION, direction="downgrade")
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_03_REVISION
            await database.execute("DELETE FROM identity_sessions")
        finally:
            await database.close()
        _require_migration(database_name, H1_02_REVISION, direction="downgrade")
        _require_migration(database_name, H1_03_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_03_sessions_tokens_recovery_linking_and_concurrency() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H1_03_REVISION)
        workspace_id, user_id, link_id = await _seed_identity(database_name)
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)

        async with sessions.begin() as database_session:
            service = IdentityLifecycleService(database_session)
            issued = await service.issue_session(
                workspace_id=workspace_id,
                user_id=user_id,
                device_id="browser-a",
                authentication_strength="password",
                expires_at=now + timedelta(hours=1),
                now=now,
            )
        assert issued.raw_secret not in str(issued.record_id)

        async with sessions.begin() as database_session:
            service = IdentityLifecycleService(database_session)
            authenticated = await service.authenticate_session(
                workspace_id=workspace_id,
                raw_secret=issued.raw_secret,
                now=now + timedelta(minutes=1),
            )
            assert authenticated.id == issued.record_id
            rotated = await service.rotate_session(
                workspace_id=workspace_id,
                raw_secret=issued.raw_secret,
                expires_at=now + timedelta(hours=2),
                now=now + timedelta(minutes=2),
            )
        async with sessions.begin() as database_session:
            service = IdentityLifecycleService(database_session)
            with pytest.raises(InvalidSessionError):
                await service.authenticate_session(
                    workspace_id=workspace_id,
                    raw_secret=issued.raw_secret,
                    now=now + timedelta(minutes=3),
                )
            await service.revoke_session(
                workspace_id=workspace_id,
                session_id=rotated.record_id,
                reason="user_request",
                now=now + timedelta(minutes=3),
            )
        async with sessions.begin() as database_session:
            with pytest.raises(InvalidSessionError):
                await IdentityLifecycleService(database_session).authenticate_session(
                    workspace_id=workspace_id,
                    raw_secret=rotated.raw_secret,
                    now=now + timedelta(minutes=4),
                )

        async with sessions.begin() as database_session:
            service = IdentityLifecycleService(database_session)
            invitation = await service.issue_lifecycle_token(
                workspace_id=workspace_id,
                purpose="invitation",
                expires_at=now + timedelta(hours=2),
                scope={"authority_version": "v1", "target": "metadata-only"},
                now=now,
            )
            with pytest.raises(InvalidLifecycleTokenError):
                await service.consume_lifecycle_token(
                    workspace_id=workspace_id,
                    raw_secret=invitation.raw_secret,
                    expected_purpose="recovery",
                    now=now,
                )
            expired = await service.issue_lifecycle_token(
                workspace_id=workspace_id,
                purpose="invitation",
                expires_at=now + timedelta(minutes=1),
                scope={"authority_version": "v1"},
                now=now,
            )
            revoked = await service.issue_lifecycle_token(
                workspace_id=workspace_id,
                purpose="invitation",
                expires_at=now + timedelta(hours=1),
                scope={"authority_version": "v1"},
                now=now,
            )
            await service.revoke_lifecycle_token(
                workspace_id=workspace_id,
                token_id=revoked.record_id,
                actor_user_id=user_id,
                now=now + timedelta(seconds=1),
            )
            for denied_secret, denied_at in (
                (expired.raw_secret, now + timedelta(minutes=2)),
                (revoked.raw_secret, now + timedelta(minutes=1)),
            ):
                with pytest.raises(InvalidLifecycleTokenError):
                    await service.consume_lifecycle_token(
                        workspace_id=workspace_id,
                        raw_secret=denied_secret,
                        expected_purpose="invitation",
                        current_authority_version="v1",
                        now=denied_at,
                    )

        async def consume_once() -> str:
            try:
                async with sessions.begin() as database_session:
                    await IdentityLifecycleService(
                        database_session
                    ).consume_lifecycle_token(
                        workspace_id=workspace_id,
                        raw_secret=invitation.raw_secret,
                        expected_purpose="invitation",
                        current_authority_version="v1",
                        now=now + timedelta(minutes=1),
                    )
                return "consumed"
            except InvalidLifecycleTokenError:
                return "denied"

        assert sorted(await asyncio.gather(consume_once(), consume_once())) == [
            "consumed",
            "denied",
        ]

        async with sessions.begin() as database_session:
            service = IdentityLifecycleService(database_session)
            active = await service.issue_session(
                workspace_id=workspace_id,
                user_id=user_id,
                device_id="browser-b",
                authentication_strength="mfa",
                mfa_authenticated_at=now,
                expires_at=now + timedelta(hours=1),
                now=now,
            )
            recovery = await service.issue_lifecycle_token(
                workspace_id=workspace_id,
                user_id=user_id,
                purpose="recovery",
                expires_at=now + timedelta(hours=1),
                scope={"reason": "account_recovery"},
                now=now,
            )
            second_recovery = await service.issue_lifecycle_token(
                workspace_id=workspace_id,
                user_id=user_id,
                purpose="recovery",
                expires_at=now + timedelta(hours=1),
                scope={"reason": "account_recovery"},
                now=now,
            )
            await service.begin_identity_link_review(
                workspace_id=workspace_id,
                external_identity_id=link_id,
                session_id=active.record_id,
                proof_reference="proof:both-identities",
                review_expires_at=now + timedelta(hours=24),
                now=now + timedelta(minutes=1),
            )

        async with sessions.begin() as database_session:
            weak = await IdentityLifecycleService(database_session).issue_session(
                workspace_id=workspace_id,
                user_id=user_id,
                device_id="browser-c",
                authentication_strength="password",
                expires_at=now + timedelta(hours=1),
                now=now,
            )
            with pytest.raises(StrongAuthenticationRequiredError):
                await IdentityLifecycleService(
                    database_session
                ).begin_identity_link_review(
                    workspace_id=workspace_id,
                    external_identity_id=link_id,
                    session_id=weak.record_id,
                    proof_reference="proof",
                    review_expires_at=now + timedelta(hours=1),
                    now=now,
                )

        async with sessions.begin() as database_session:
            await IdentityLifecycleService(database_session).recover_account(
                workspace_id=workspace_id,
                raw_secret=recovery.raw_secret,
                now=now + timedelta(minutes=5),
            )

        async with sessions.begin() as database_session:
            assert await database_session.scalar(
                select(func.count())
                .select_from(IdentitySession)
                .where(
                    IdentitySession.workspace_id == workspace_id,
                    IdentitySession.user_id == user_id,
                    IdentitySession.revoked_at.is_(None),
                )
            ) == 0
            second = await database_session.get(
                IdentityLifecycleToken,
                (workspace_id, second_recovery.record_id),
            )
            assert second is not None and second.revoked_at is not None
            assert await database_session.scalar(
                select(func.count()).select_from(SecurityNotification)
            ) == 1
            assert await database_session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "identity.account_recovered")
            ) == 1
            assert await database_session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "identity.account_recovered")
            ) == 1
            persisted_hashes = (
                await database_session.scalars(
                    select(IdentityLifecycleToken.token_hash)
                )
            ).all()
            assert recovery.raw_secret not in persisted_hashes

        async with sessions.begin() as database_session:
            with pytest.raises(IdentityLifecycleError):
                await IdentityLifecycleService(database_session).issue_lifecycle_token(
                    workspace_id=workspace_id,
                    purpose="invitation",
                    expires_at=now + timedelta(hours=73),
                    scope={"authority_version": "v1"},
                    now=now,
                )
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
