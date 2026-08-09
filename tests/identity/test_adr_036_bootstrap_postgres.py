"""PostgreSQL evidence for exactly-once ADR-036 identity bootstrap."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import asyncpg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.identity.bootstrap import (
    FIXED_BOOTSTRAP_USER_ID,
    FIXED_BOOTSTRAP_WORKSPACE_ID,
    BootstrapApproval,
    BootstrapIdentity,
    BootstrapIdentityError,
    BootstrapIdentityLinkService,
)
from app.identity.models import ExternalIdentityLink
from app.tenancy.models import AuditEvent
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
)

BASELINE = "0032_h3_platform_hardening"


async def _seed_fixed_target(database_name: str) -> None:
    database = await asyncpg.connect(_database_url(database_name))
    try:
        transaction = database.transaction()
        await transaction.start()
        cell_id = uuid.uuid4()
        organization_id = uuid.uuid4()
        await database.execute(
            "INSERT INTO cells (id, key, region) VALUES ($1, $2, 'test')",
            cell_id,
            f"adr-036-{cell_id}",
        )
        await database.execute(
            """
            INSERT INTO users (id, email, status)
            VALUES ($1, 'display-only@example.test', 'active')
            """,
            FIXED_BOOTSTRAP_USER_ID,
        )
        await database.execute(
            """
            INSERT INTO organizations (id, organization_type, name)
            VALUES ($1, 'business', 'ADR-036 Test')
            """,
            organization_id,
        )
        await database.execute(
            """
            INSERT INTO organization_memberships (organization_id, user_id, role, status)
            VALUES ($1, $2, 'owner', 'active')
            """,
            organization_id,
            FIXED_BOOTSTRAP_USER_ID,
        )
        await database.execute(
            """
            INSERT INTO workspaces (
                workspace_id, organization_id, cell_id, name, slug, status
            ) VALUES ($1, $2, $3, 'ADR-036 Test', 'adr-036-test', 'active')
            """,
            FIXED_BOOTSTRAP_WORKSPACE_ID,
            organization_id,
            cell_id,
        )
        await database.execute(
            """
            INSERT INTO workspace_memberships (
                workspace_id, id, organization_id, user_id, role_key, role_version,
                status, activated_at, origin
            ) VALUES ($1, $2, $3, $4, 'workspace_owner', 1, 'active', now(), 'direct')
            """,
            FIXED_BOOTSTRAP_WORKSPACE_ID,
            uuid.uuid4(),
            organization_id,
            FIXED_BOOTSTRAP_USER_ID,
        )
        await transaction.commit()
    finally:
        await database.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_bootstrap_is_atomic_audited_and_nonrepeatable() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, BASELINE)
        await _seed_fixed_target(database_name)
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        identity = BootstrapIdentity(
            issuer="https://accounts.google.com",
            subject="verified-google-subject",
            audience="client.apps.googleusercontent.com",
            verified_at=datetime.now(UTC),
        )
        wrong = BootstrapApproval(
            reference="ADR-036-TEST",
            user_id=FIXED_BOOTSTRAP_USER_ID,
            workspace_id=FIXED_BOOTSTRAP_WORKSPACE_ID,
            issuer=identity.issuer,
            subject="wrong-subject",
        )
        correct = BootstrapApproval(
            reference="ADR-036-TEST",
            user_id=FIXED_BOOTSTRAP_USER_ID,
            workspace_id=FIXED_BOOTSTRAP_WORKSPACE_ID,
            issuer=identity.issuer,
            subject=identity.subject,
        )

        async with sessions() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('atlas.workspace_id', :workspace_id, TRUE)"),
                    {"workspace_id": str(FIXED_BOOTSTRAP_WORKSPACE_ID)},
                )
                with pytest.raises(BootstrapIdentityError):
                    await BootstrapIdentityLinkService(session).commit(
                        identity=identity,
                        approval=wrong,
                    )
                assert await session.scalar(
                    select(func.count()).select_from(ExternalIdentityLink)
                ) == 0

        async with sessions() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('atlas.workspace_id', :workspace_id, TRUE)"),
                    {"workspace_id": str(FIXED_BOOTSTRAP_WORKSPACE_ID)},
                )
                result = await BootstrapIdentityLinkService(session).commit(
                    identity=identity,
                    approval=correct,
                )
                audit = await session.get(
                    AuditEvent,
                    (FIXED_BOOTSTRAP_WORKSPACE_ID, result.audit_event_id),
                )
                assert audit is not None
                assert audit.details["subject_fingerprint"] == identity.subject_fingerprint
                assert identity.subject not in str(audit.details)

        async with sessions() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('atlas.workspace_id', :workspace_id, TRUE)"),
                    {"workspace_id": str(FIXED_BOOTSTRAP_WORKSPACE_ID)},
                )
                with pytest.raises(BootstrapIdentityError, match="already disabled"):
                    await BootstrapIdentityLinkService(session).commit(
                        identity=identity,
                        approval=correct,
                    )

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT verify_audit_chain($1)", FIXED_BOOTSTRAP_WORKSPACE_ID
            )
            with pytest.raises(asyncpg.RaiseError, match="immutable"):
                await database.execute(
                    """
                    UPDATE audit_events SET outcome = 'changed'
                    WHERE workspace_id = $1
                    """,
                    FIXED_BOOTSTRAP_WORKSPACE_ID,
                )
        finally:
            await database.close()
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
