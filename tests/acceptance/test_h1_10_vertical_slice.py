"""Synthetic-tenant acceptance evidence for Formal H1 Exit."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.authorization import (
    AuthorizationRequest,
    AuthorizationService,
    DecisionEffect,
    ReasonCode,
)
from app.encryption import KeyReference
from app.execution_context import (
    ActorContext,
    ExecutionContext,
    ExecutionContextRequiredError,
    ExecutionContextService,
    RequestContext,
    TenantContext,
)
from app.identity.lifecycle import IdentityLifecycleService, InvalidSessionError
from app.identity.models import ExternalIdentityLink
from app.messaging import CommandEnvelope, CommandService, MessagingError
from app.recovery import (
    BackupSnapshot,
    ClosureState,
    EncryptedBackupService,
    WorkspaceRecoveryService,
)
from app.recovery.repository import RecoveryRepository, manifest_payload
from tests.encryption.support import MockManagedKeyProvider
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _require_migration,
    _seed_business_workspace,
)

H1_HEAD_REVISION = "0013_h1_recovery_closure"
SYNTHETIC_BACKUP_KEY = KeyReference("atlas-h1-exit", "1")


def _context(
    *,
    organization_id: UUID,
    workspace_id: UUID,
    cell_id: UUID,
    actor_id: UUID,
    session_id: UUID,
    membership_id: UUID,
    authorization_decision_id: UUID,
) -> ExecutionContext:
    return ExecutionContext(
        request=RequestContext(
            request_id=f"h1-exit-{uuid4()}",
            correlation_id=f"h1-exit-{uuid4()}",
        ),
        actor=ActorContext(
            actor_id=actor_id,
            session_id=session_id,
            membership_id=membership_id,
            authorization_decision_id=authorization_decision_id,
        ),
        tenant=TenantContext(
            organization_id=organization_id,
            workspace_id=workspace_id,
            cell_id=cell_id,
        ),
    )


def _authorization_request(
    context: ExecutionContext,
    *,
    permission_key: str = "update_content",
    requested_workspace_id: UUID | None = None,
) -> AuthorizationRequest:
    requested = requested_workspace_id or context.tenant.workspace_id
    return AuthorizationRequest(
        actor_id=context.actor.actor_id,
        session_id=context.actor.session_id,
        organization_id=context.tenant.organization_id,
        requested_workspace_id=requested,
        membership_workspace_id=context.tenant.workspace_id,
        membership_id=context.actor.membership_id,
        permission_key=permission_key,
        request_reference=context.request.request_id,
    )


def _command(
    context: ExecutionContext,
    *,
    aggregate_id: UUID,
    idempotency_key: str,
    expected_version: int = 0,
) -> CommandEnvelope:
    return CommandEnvelope(
        workspace_id=context.tenant.workspace_id,
        actor_id=context.actor.actor_id,
        command_type="synthetic.recorded",
        idempotency_key=idempotency_key,
        aggregate_type="synthetic_record",
        aggregate_id=aggregate_id,
        expected_version=expected_version,
        correlation_id=context.request.correlation_id,
        payload={"verification": "h1-exit"},
    )


async def _tenant_context(
    database_name: str,
    sessions: async_sessionmaker,
    *,
    issuer: str,
) -> tuple[ExecutionContext, str]:
    (
        organization_id,
        workspace_id,
        _,
        owner_id,
        _,
    ) = await _seed_business_workspace(database_name)
    database = await asyncpg.connect(_database_url(database_name))
    try:
        cell_id = await database.fetchval(
            "SELECT cell_id FROM workspaces WHERE workspace_id = $1",
            workspace_id,
        )
        membership_id = await database.fetchval(
            """
            SELECT id FROM workspace_memberships
            WHERE workspace_id = $1 AND user_id = $2
            """,
            workspace_id,
            owner_id,
        )
    finally:
        await database.close()

    now = datetime.now(UTC)
    async with sessions.begin() as session:
        session.add(
            ExternalIdentityLink(
                user_id=owner_id,
                issuer=issuer,
                subject=f"subject:{owner_id}",
                email=f"{owner_id}@synthetic.atlas",
                email_verified=False,
                status="active",
            )
        )
        issued = await IdentityLifecycleService(session).issue_session(
            workspace_id=workspace_id,
            user_id=owner_id,
            device_id="h1-exit",
            authentication_strength="mfa",
            mfa_authenticated_at=now,
            expires_at=now + timedelta(hours=1),
            now=now,
        )
    decision_id = uuid4()
    return (
        _context(
            organization_id=organization_id,
            workspace_id=workspace_id,
            cell_id=cell_id,
            actor_id=owner_id,
            session_id=issued.record_id,
            membership_id=membership_id,
            authorization_decision_id=decision_id,
        ),
        issued.raw_secret,
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_10_two_tenant_security_and_lifecycle_vertical_slice() -> None:
    admin, database_name = await _create_database()
    engine = None
    rls_role = f"h1_10_reader_{uuid4().hex}"
    try:
        _require_migration(database_name, H1_HEAD_REVISION)
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        first, first_secret = await _tenant_context(
            database_name,
            sessions,
            issuer="https://identity.synthetic-a.atlas",
        )
        second, _ = await _tenant_context(
            database_name,
            sessions,
            issuer="https://identity.synthetic-b.atlas",
        )

        async with sessions.begin() as session:
            allowed = await AuthorizationService(session).authorize(
                _authorization_request(first)
            )
            denied = await AuthorizationService(session).authorize(
                _authorization_request(
                    first,
                    requested_workspace_id=second.tenant.workspace_id,
                )
            )
            assert allowed.effect is DecisionEffect.ALLOW
            assert denied.effect is DecisionEffect.DENY
            assert denied.reason is ReasonCode.WORKSPACE_MISMATCH

        execution = ExecutionContextService()
        first_aggregate = uuid4()
        second_aggregate = uuid4()
        async with sessions() as session:
            async with execution.transaction(session, first):
                service = CommandService(session, first)
                recorded = await service.record(
                    _command(
                        first,
                        aggregate_id=first_aggregate,
                        idempotency_key="first-command",
                    ),
                    event_type="synthetic.recorded",
                    event_payload={"tenant": "first"},
                )
            async with execution.transaction(session, first):
                replayed = await CommandService(session, first).record(
                    _command(
                        first,
                        aggregate_id=first_aggregate,
                        idempotency_key="first-command",
                    ),
                    event_type="synthetic.recorded",
                    event_payload={"tenant": "first"},
                )
            assert replayed.event_id == recorded.event_id
            assert replayed.replayed

            async with execution.transaction(session, second):
                second_recorded = await CommandService(session, second).record(
                    _command(
                        second,
                        aggregate_id=second_aggregate,
                        idempotency_key="second-command",
                    ),
                    event_type="synthetic.recorded",
                    event_payload={"tenant": "second"},
                )
            assert second_recorded.event_id != recorded.event_id

            async with execution.transaction(session, second):
                with pytest.raises(
                    (ExecutionContextRequiredError, MessagingError)
                ):
                    await CommandService(session, first).record(
                        _command(
                            first,
                            aggregate_id=uuid4(),
                            idempotency_key="cross-tenant-command",
                        ),
                        event_type="synthetic.recorded",
                        event_payload={"tenant": "wrong"},
                    )

        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                f"CREATE ROLE {rls_role} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {rls_role}")
            await database.execute(
                f"GRANT SELECT ON aggregate_versions TO {rls_role}"
            )
            async with database.transaction():
                await database.execute(f"SET LOCAL ROLE {rls_role}")
                await database.execute(
                    "SELECT set_config('atlas.workspace_id', $1, TRUE)",
                    str(first.tenant.workspace_id),
                )
                visible = await database.fetch(
                    "SELECT workspace_id FROM aggregate_versions"
                )
                assert [row["workspace_id"] for row in visible] == [
                    first.tenant.workspace_id
                ]
        finally:
            await database.close()

        now = datetime.now(UTC)
        async with sessions.begin() as session:
            await IdentityLifecycleService(session).revoke_session(
                workspace_id=first.tenant.workspace_id,
                session_id=first.actor.session_id,
                reason="h1-exit-revocation",
                now=now,
            )
        async with sessions.begin() as session:
            revoked = await AuthorizationService(session).authorize(
                _authorization_request(first),
                now=now + timedelta(seconds=1),
            )
            assert revoked.effect is DecisionEffect.DENY
            assert revoked.reason is ReasonCode.INVALID_SESSION
            with pytest.raises(InvalidSessionError):
                await IdentityLifecycleService(session).authenticate_session(
                    workspace_id=first.tenant.workspace_id,
                    raw_secret=first_secret,
                    now=now + timedelta(seconds=1),
                )

        snapshot_time = datetime.now(UTC)
        async with sessions() as session:
            async with execution.transaction(session, second):
                repository = RecoveryRepository(session, second)
                before = await repository.manifest(now=snapshot_time)
                exported = await WorkspaceRecoveryService(
                    session, second
                ).create_export(
                    idempotency_key="h1-exit-export",
                    authorization_decision_id=(
                        second.actor.authorization_decision_id
                    ),
                    now=snapshot_time,
                )
                assert exported.table_counts == before.table_counts

        payload = json.dumps(
            manifest_payload(before),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        backup_service = EncryptedBackupService(
            MockManagedKeyProvider({SYNTHETIC_BACKUP_KEY: b"x" * 32})
        )
        artifact = await backup_service.create(
            BackupSnapshot(
                payload=payload,
                source_snapshot_at=snapshot_time,
                manifest=before,
            ),
            key_reference=SYNTHETIC_BACKUP_KEY,
            now=snapshot_time + timedelta(minutes=1),
        )

        async def verify_restore(restored_payload: bytes):
            assert restored_payload == payload
            return before

        restore = await backup_service.restore(
            artifact,
            isolated_target="h1-exit-isolated",
            restore=verify_restore,
            started_at=snapshot_time + timedelta(minutes=1),
            now=snapshot_time + timedelta(minutes=2),
        )
        assert restore.counts_verified and restore.digests_verified
        assert restore.rpo_met and restore.rto_met

        async with sessions() as session:
            async with execution.transaction(session, second):
                closure = await WorkspaceRecoveryService(
                    session, second
                ).close(
                    idempotency_key="h1-exit-closure",
                    reason="synthetic tenant acceptance",
                    authorization_decision_id=(
                        second.actor.authorization_decision_id
                    ),
                    now=snapshot_time + timedelta(minutes=3),
                )
            assert closure.state is ClosureState.CLOSED

        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT status FROM workspaces WHERE workspace_id = $1",
                second.tenant.workspace_id,
            ) == "closed"
            assert await database.fetchval(
                """
                SELECT count(*) FROM identity_sessions
                WHERE workspace_id = $1
                """,
                second.tenant.workspace_id,
            ) == 0
            assert await database.fetchval(
                """
                SELECT count(*) FROM workspace_memberships
                WHERE workspace_id = $1 AND status <> 'revoked'
                """,
                second.tenant.workspace_id,
            ) == 0
            assert await database.fetchval(
                "SELECT verify_audit_chain($1)",
                second.tenant.workspace_id,
            )
            assert await database.fetchval(
                """
                SELECT count(*) FROM outbox_events
                WHERE workspace_id = $1 AND event_type = 'workspace.closed'
                """,
                second.tenant.workspace_id,
            ) == 1
            assert await database.fetchval(
                """
                SELECT count(*) FROM aggregate_versions
                WHERE workspace_id = $1
                """,
                first.tenant.workspace_id,
            ) == 1
        finally:
            await database.close()
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.execute(f"DROP ROLE IF EXISTS {rls_role}")
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_10_schema_is_unchanged_and_head_is_repeatable() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H1_HEAD_REVISION)
        _require_migration(database_name, H1_HEAD_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_HEAD_REVISION
            assert await database.fetchval(
                """
                SELECT bool_and(relrowsecurity AND relforcerowsecurity)
                FROM pg_class
                WHERE relname IN (
                    'workspaces',
                    'workspace_memberships',
                    'identity_sessions',
                    'encrypted_envelopes',
                    'aggregate_versions',
                    'workspace_closures'
                )
                """
            )
        finally:
            await database.close()
    finally:
        await _drop_database(admin, database_name)
        await admin.close()
