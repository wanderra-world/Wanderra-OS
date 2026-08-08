from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.connection_credentials import PhaseOneCredentialSnapshot, ShadowMigrationCommand
from app.connection_credentials.service import ConnectionCredentialService
from app.connections import CapabilityGrant, ConnectionCreate, ConnectionService, ConnectionStatus
from app.encryption import KeyReference
from app.execution_context import ExecutionContextService
from app.integration_layer import (
    IntegrationResolutionRequest,
    IntegrationResolver,
    IntegrationStateError,
)
from app.provider_capabilities.common import CapabilityDescriptor, CapabilityRegistry
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

IP_01_BASELINE = "0032_h3_platform_hardening"
KEY = KeyReference("ip-01-test-key", "1")


def _registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        "google_workspace",
        (CapabilityDescriptor("email.read", 1, ("list", "get")),),
    )
    return registry


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_ip_01_resolves_one_workspace_and_records_immutable_audit() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, IP_01_BASELINE)
        organization_id, workspace_id, second_workspace_id, owner_id, _ = (
            await _seed_business_workspace(database_name)
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        second_context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=second_workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        connection_id = uuid4()
        keys = MockManagedKeyProvider({KEY: b"k" * 32})

        async with sessions() as session:
            async with execution.transaction(session, context):
                connections = ConnectionService(
                    session,
                    context,
                    authorizer=AllowAuthorizer(),
                )
                await connections.create(
                    ConnectionCreate(
                        connection_id=connection_id,
                        provider_key="google_workspace",
                        connection_kind="workspace_suite",
                        provider_account_id="provider-account-1",
                        display_name="IP-01 account",
                        granted_scopes=("scope.email",),
                        capability_grants=(CapabilityGrant("email.read"),),
                    )
                )
                await connections.transition(
                    connection_id=connection_id,
                    expected_version=1,
                    target=ConnectionStatus.ACTIVE,
                )
                await ConnectionCredentialService(
                    session,
                    context,
                    key_provider=keys,
                    authorizer=AllowAuthorizer(),
                ).shadow_migrate(
                    ShadowMigrationCommand(
                        connection_id=connection_id,
                        provider_key="google_workspace",
                        credential_kind="oauth_grant",
                        snapshot=PhaseOneCredentialSnapshot(
                            source_system="synthetic_fixture",
                            source_record_id=str(uuid4()),
                            legacy_ciphertext=b"authenticated-fixture",
                            plaintext=b'{"grant":"redacted"}',
                            scopes=("scope.email",),
                        ),
                        required_scopes=("scope.email",),
                    ),
                    key_reference=KEY,
                )

            request = IntegrationResolutionRequest(
                connection_id=connection_id,
                capability_key="email.read",
                capability_version=1,
                operation="list",
                permission_key="read_content",
                credential_kind="oauth_grant",
                required_scopes=("scope.email",),
            )
            async with execution.transaction(session, context):
                result = await IntegrationResolver.for_session(
                    session,
                    context,
                    capability_registry=_registry(),
                    authorizer=AllowAuthorizer(),
                ).resolve(request)
                assert result.workspace_id == workspace_id
                assert result.organization_id == organization_id
                assert result.connection_id == connection_id
                assert result.provider_account_id == "provider-account-1"

            async with execution.transaction(session, second_context):
                with pytest.raises(IntegrationStateError, match="unavailable"):
                    await IntegrationResolver.for_session(
                        session,
                        second_context,
                        capability_registry=_registry(),
                        authorizer=AllowAuthorizer(),
                    ).resolve(request)

            assert await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.action == "integration.resolved",
                    AuditEvent.target_id == connection_id,
                )
            ) == 1
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
