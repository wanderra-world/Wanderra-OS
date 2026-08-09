"""PostgreSQL/RLS evidence for ADR-035 external identity session issuance."""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.identity.lifecycle import IdentityLifecycleService, InvalidSessionError
from app.identity.lifecycle_models import IdentitySession
from app.identity.operator_auth import OperatorAuthenticationService, VerifiedExternalIdentity
from app.tenancy.models import AuditEvent
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
    _seed_business_workspace,
)

BASELINE = "0032_h3_platform_hardening"


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_google_subject_maps_to_existing_user_before_workspace_session() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, BASELINE)
        _, workspace_id, other_workspace_id, owner_id, _ = await _seed_business_workspace(
            database_name
        )
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                """
                INSERT INTO external_identity_links (
                    id, user_id, issuer, subject, email, email_verified,
                    email_verified_at, email_verification_source, status
                )
                VALUES (
                    gen_random_uuid(), $1, 'https://accounts.google.com',
                    'adr-035-subject', 'different-display-email@example.test',
                    TRUE, now(), 'google_oidc', 'active'
                )
                """,
                owner_id,
            )
        finally:
            await database.close()
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)
        claims = VerifiedExternalIdentity(
            issuer="https://accounts.google.com",
            subject="adr-035-subject",
            email="not-used-for-mapping@example.test",
            email_verified=True,
        )

        async with sessions() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('atlas.workspace_id', :workspace_id, TRUE)"),
                    {"workspace_id": str(workspace_id)},
                )
                grant = await OperatorAuthenticationService.for_session(session).authenticate(
                    claims=claims,
                    workspace_id=workspace_id,
                    device_id="postgres-browser",
                    now=now,
                )
                assert grant.user_id == owner_id
                assert grant.workspace_id == workspace_id
                assert await session.scalar(
                    select(func.count())
                    .select_from(IdentitySession)
                    .where(IdentitySession.workspace_id == workspace_id)
                ) == 1
                assert await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.workspace_id == workspace_id,
                        AuditEvent.action == "identity.operator_authenticated",
                    )
                ) == 1

            async with session.begin():
                await session.execute(
                    text("SELECT set_config('atlas.workspace_id', :workspace_id, TRUE)"),
                    {"workspace_id": str(other_workspace_id)},
                )
                with pytest.raises(InvalidSessionError):
                    await IdentityLifecycleService(session).authenticate_session(
                        workspace_id=other_workspace_id,
                        raw_secret=grant.raw_session,
                    )
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
