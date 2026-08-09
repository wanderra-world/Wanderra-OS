"""PostgreSQL/RLS acceptance tests for the IP-03 lifecycle projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.connections import CapabilityGrant, ConnectionCreate, ConnectionService
from app.execution_context import ExecutionContextService
from app.identity.lifecycle import IdentityLifecycleService
from app.integrations.gmail.operator import (
    GmailConnectionState,
    GmailConnectionStatusService,
    GmailOperatorContextFactory,
    GmailOperatorError,
)
from app.tenancy.models import AuditEvent
from tests.connection_credentials.test_h2_02_postgres import AllowAuthorizer
from tests.connections.test_h2_01_postgres import _context_for_owner
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
async def test_ip_03_status_is_workspace_bound_and_audited_without_secrets() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, BASELINE)
        organization_id, workspace_id, other_workspace_id, owner_id, _ = (
            await _seed_business_workspace(database_name)
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        other = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=other_workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        connection_id = uuid4()

        async with sessions() as session:
            async with execution.transaction(session, context):
                issued = await IdentityLifecycleService(session).issue_session(
                    workspace_id=workspace_id,
                    user_id=owner_id,
                    device_id="ip-03-operator",
                    authentication_strength="mfa",
                    mfa_authenticated_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
                authenticated = await GmailOperatorContextFactory(session).authenticate(
                    workspace_id=workspace_id,
                    raw_session=issued.raw_secret,
                    request_id="ip-03-request",
                    correlation_id="ip-03-correlation",
                )
                assert authenticated.actor.actor_id == owner_id
                assert authenticated.tenant.workspace_id == workspace_id
                connection = await ConnectionService(
                    session, context, authorizer=AllowAuthorizer()
                ).create(
                    ConnectionCreate(
                        connection_id=connection_id,
                        provider_key="google_workspace",
                        connection_kind="workspace_suite",
                        provider_account_id="operator@example.com",
                        display_name="Operator Gmail",
                        capability_grants=(CapabilityGrant("email.read"),),
                    )
                )
                view = await GmailConnectionStatusService(session, context).get(
                    connection
                )
                assert view.state is GmailConnectionState.INITIATED
                assert view.workspace_id == workspace_id
                assert await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.workspace_id == workspace_id,
                        AuditEvent.action == "gmail.connection_state_read",
                    )
                ) == 1

            async with execution.transaction(session, other):
                with pytest.raises(GmailOperatorError, match="invalid"):
                    await GmailOperatorContextFactory(session).authenticate(
                        workspace_id=other_workspace_id,
                        raw_session=issued.raw_secret,
                        request_id="ip-03-cross-workspace",
                        correlation_id="ip-03-cross-workspace",
                    )
                with pytest.raises(GmailOperatorError, match="unavailable"):
                    await GmailConnectionStatusService(session, other).get(connection)
                assert await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.workspace_id == other_workspace_id)
                ) == 0
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
