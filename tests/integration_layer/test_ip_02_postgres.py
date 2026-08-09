"""PostgreSQL/RLS acceptance tests for IP-02 Gmail OAuth custody."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.connection_credentials.models import ConnectionCredential
from app.connection_credentials.repository import ConnectionCredentialRepository
from app.connections import CapabilityGrant, ConnectionCreate, ConnectionService
from app.encryption import KeyReference
from app.execution_context import ExecutionContextService
from app.integrations.gmail.credential_store import (
    GmailCredentialBindingError,
    GmailCredentialSink,
)
from app.integrations.gmail.oauth import GMAIL_READ_SCOPE
from app.oauth_transactions.contracts import OAuthCredentialGrant
from app.tenancy.models import AuditEvent
from tests.connection_credentials.test_h2_02_postgres import AllowAuthorizer
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.encryption.support import MockManagedKeyProvider
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
    _seed_business_workspace,
)

BASELINE = "0032_h3_platform_hardening"
KEY = KeyReference("ip-02-test-key", "1")


def _grant(account: str = "account-a@example.com") -> OAuthCredentialGrant:
    return OAuthCredentialGrant(
        payload=b'{"refresh_token":"not-logged","token":"not-logged"}',
        scopes=(GMAIL_READ_SCOPE,),
        provider_account_id=account,
        credential_kind="oauth_refresh_token",
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_ip_02_encrypts_workspace_grant_and_rls_blocks_other_workspace() -> None:
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
        keys = MockManagedKeyProvider({KEY: b"k" * 32})

        async with sessions() as session:
            async with execution.transaction(session, context):
                await ConnectionService(
                    session, context, authorizer=AllowAuthorizer()
                ).create(
                    ConnectionCreate(
                        connection_id=connection_id,
                        provider_key="google_workspace",
                        connection_kind="workspace_suite",
                        provider_account_id="account-a@example.com",
                        display_name="Workspace A Gmail",
                        capability_grants=(CapabilityGrant("email.read"),),
                    )
                )
                credential_id = await GmailCredentialSink(
                    session,
                    context,
                    key_provider=keys,
                    key_reference=KEY,
                ).store(
                    connection_id=connection_id,
                    provider_key="google_workspace",
                    grant=_grant(),
                )

            async with execution.transaction(session, context):
                credential = await session.get(
                    ConnectionCredential, (workspace_id, credential_id)
                )
                assert credential is not None
                assert credential.status == "active"
                assert credential.scopes == [GMAIL_READ_SCOPE]
                assert await session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.workspace_id == workspace_id,
                        AuditEvent.action == "gmail.oauth_connected",
                    )
                ) == 1

            async with execution.transaction(session, other):
                assert await ConnectionCredentialRepository(
                    session, other
                ).latest_generation(
                    connection_id, "oauth_refresh_token"
                ) is None

            async with execution.transaction(session, context):
                with pytest.raises(GmailCredentialBindingError, match="account"):
                    await GmailCredentialSink(
                        session,
                        context,
                        key_provider=keys,
                        key_reference=KEY,
                    ).store(
                        connection_id=connection_id,
                        provider_key="google_workspace",
                        grant=_grant("account-b@example.com"),
                    )
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
