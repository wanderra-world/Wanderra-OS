"""PostgreSQL acceptance tests for the H2-03 OAuth transaction boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.connections import ConnectionCreate, ConnectionService
from app.encryption import KeyReference
from app.execution_context import ExecutionContext, ExecutionContextService
from app.oauth_transactions import (
    OAuthBindingError,
    OAuthCallback,
    OAuthCredentialGrant,
    OAuthPurpose,
    OAuthReplayError,
    OAuthScopeError,
    OAuthSecurityPolicy,
    OAuthTransactionCreate,
)
from app.oauth_transactions.models import OAuthTransaction
from app.oauth_transactions.service import OAuthTransactionService
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.encryption.support import MockManagedKeyProvider
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _migration,
    _require_migration,
    _seed_business_workspace,
)

H2_03_REVISION = "0016_h2_oauth_transactions"
H2_02_REVISION = "0015_h2_credentials"
KEY = KeyReference("h2-03-test-key", "1")
REDIRECT = "https://atlas.example/api/v1/oauth/callback"
ISSUER = "https://issuer.example"


class AllowAuthorizer:
    async def authorize(
        self, context: ExecutionContext, permission_key: str
    ) -> bool:
        return permission_key == "manage_workspace"


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def exchange(
        self,
        *,
        provider_key: str,
        authorization_code: str,
        pkce_verifier: bytes,
        redirect_uri: str,
    ) -> OAuthCredentialGrant:
        self.calls += 1
        assert provider_key == "google_workspace"
        assert authorization_code == "one-time-code"
        assert pkce_verifier == b"private-pkce-verifier"
        assert redirect_uri == REDIRECT
        return OAuthCredentialGrant(
            payload=b'{"refresh_token":"private-provider-value"}',
            scopes=("calendar.read", "email.read", "storage.read"),
            provider_account_id="provider-account",
            credential_kind="oauth_grant",
        )


class RecordingSink:
    def __init__(self) -> None:
        self.calls = 0
        self.credential_id = uuid4()

    async def store(
        self,
        *,
        connection_id: UUID,
        provider_key: str,
        grant: OAuthCredentialGrant,
    ) -> UUID:
        self.calls += 1
        assert connection_id
        assert provider_key == "google_workspace"
        assert grant.provider_account_id == "provider-account"
        return self.credential_id


def _policy() -> OAuthSecurityPolicy:
    return OAuthSecurityPolicy(
        allowed_redirect_uris=frozenset({REDIRECT}),
        allowed_issuers=frozenset({ISSUER}),
        allowed_scopes=frozenset(
            {"email.read", "calendar.read", "storage.read"}
        ),
        lifetime=timedelta(minutes=10),
    )


def _create(connection_id: UUID) -> OAuthTransactionCreate:
    return OAuthTransactionCreate(
        transaction_id=uuid4(),
        connection_id=connection_id,
        provider_key="google_workspace",
        purpose=OAuthPurpose.CONNECT,
        redirect_uri=REDIRECT,
        issuer=ISSUER,
        requested_capabilities=("email.read", "calendar.read"),
        requested_scopes=("email.read", "calendar.read"),
        required_scopes=("email.read", "calendar.read"),
        incremental=True,
    )


async def _seed_connection(
    sessions: async_sessionmaker,
    execution: ExecutionContextService,
    context: ExecutionContext,
) -> UUID:
    connection_id = uuid4()
    async with sessions() as session:
        async with execution.transaction(session, context):
            await ConnectionService(session, context).create(
                ConnectionCreate(
                    connection_id=connection_id,
                    provider_key="google_workspace",
                    connection_kind="workspace_suite",
                    provider_account_id=f"account-{connection_id}",
                    display_name="H2-03 OAuth connection",
                    granted_scopes=(),
                )
            )
    return connection_id


def _service(
    session,
    context: ExecutionContext,
    keys: MockManagedKeyProvider,
    dispatcher: RecordingDispatcher,
    sink: RecordingSink,
) -> OAuthTransactionService:
    return OAuthTransactionService(
        session,
        context,
        policy=_policy(),
        key_provider=keys,
        dispatcher=dispatcher,
        credential_sink=sink,
        authorizer=AllowAuthorizer(),
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_03_additive_migration_forced_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H2_03_REVISION)
        _require_migration(database_name, H2_03_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H2_03_REVISION
            row = await database.fetchrow(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE oid = 'oauth_transactions'::regclass
                """
            )
            assert row and row["relrowsecurity"] and row["relforcerowsecurity"]
        finally:
            await database.close()
        _require_migration(database_name, H2_02_REVISION, direction="downgrade")
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT to_regclass('public.oauth_transactions') IS NULL"
            )
            assert await database.fetchval(
                "SELECT to_regclass('public.connection_credentials') IS NOT NULL"
            )
        finally:
            await database.close()
        _require_migration(database_name, H2_03_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_03_start_complete_combined_scope_and_redacted_evidence() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_03_REVISION)
        organization_id, workspace_id, _, owner_id, _ = (
            await _seed_business_workspace(database_name)
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        connection_id = await _seed_connection(sessions, execution, context)
        keys = MockManagedKeyProvider({KEY: b"k" * 32})
        dispatcher = RecordingDispatcher()
        sink = RecordingSink()
        now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = _service(session, context, keys, dispatcher, sink)
                started = await service.start(
                    _create(connection_id),
                    pkce_verifier=b"private-pkce-verifier",
                    key_reference=KEY,
                    idempotency_key="oauth-start-1",
                    now=now,
                )
                replayed_start = await service.start(
                    _create(connection_id),
                    pkce_verifier=b"private-pkce-verifier",
                    key_reference=KEY,
                    idempotency_key="oauth-start-1",
                    now=now,
                )
                assert replayed_start.state == started.state
                assert replayed_start.transaction.id == started.transaction.id

            async with execution.transaction(session, context):
                completed = await _service(
                    session, context, keys, dispatcher, sink
                ).complete(
                    OAuthCallback(
                        state=started.state,
                        code="one-time-code",
                        returned_scopes=(
                            "storage.read",
                            "calendar.read",
                            "email.read",
                        ),
                        issuer=ISSUER,
                        redirect_uri=REDIRECT,
                        received_at=now + timedelta(minutes=1),
                    )
                )
                assert completed.status == "completed"
                assert completed.credential_id == sink.credential_id
                transaction_id = completed.id

            record = await session.get(
                OAuthTransaction, (workspace_id, transaction_id)
            )
            assert record is not None
            assert record.state_digest != started.state
            assert record.returned_scopes == [
                "calendar.read",
                "email.read",
                "storage.read",
            ]
            assert dispatcher.calls == 1
            assert sink.calls == 1
            assert await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("oauth.transaction_%"))
            ) == 2
            assert await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type.like("oauth.transaction_%"))
            ) == 2
            serialized = str(
                (
                    await session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action.like("oauth.transaction_%")
                        )
                    )
                ).all()
            )
            assert "private-pkce" not in serialized
            assert "one-time-code" not in serialized
            assert "private-provider" not in serialized
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_03_replay_expiry_binding_scope_and_concurrency_fail_closed() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_03_REVISION)
        organization_id, workspace_id, _, owner_id, _ = (
            await _seed_business_workspace(database_name)
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        connection_id = await _seed_connection(sessions, execution, context)
        keys = MockManagedKeyProvider({KEY: b"k" * 32})
        dispatcher = RecordingDispatcher()
        sink = RecordingSink()
        now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)

        async def start(key: str):
            async with sessions() as session:
                async with execution.transaction(session, context):
                    return await _service(
                        session, context, keys, dispatcher, sink
                    ).start(
                        _create(connection_id),
                        pkce_verifier=b"private-pkce-verifier",
                        key_reference=KEY,
                        idempotency_key=key,
                        now=now,
                    )

        concurrent = await start("concurrent")
        callback = OAuthCallback(
            state=concurrent.state,
            code="one-time-code",
            returned_scopes=("email.read", "calendar.read"),
            issuer=ISSUER,
            redirect_uri=REDIRECT,
            received_at=now + timedelta(minutes=1),
        )

        async def complete_once():
            async with sessions() as session:
                async with execution.transaction(session, context):
                    return await _service(
                        session, context, keys, dispatcher, sink
                    ).complete(callback)

        outcomes = await asyncio.gather(
            complete_once(), complete_once(), return_exceptions=True
        )
        assert sum(isinstance(item, OAuthTransaction) for item in outcomes) == 1
        assert sum(isinstance(item, OAuthReplayError) for item in outcomes) == 1
        assert dispatcher.calls == 1
        assert sink.calls == 1

        expired = await start("expired")
        mismatched = await start("mismatched")
        scope_denied = await start("scope-denied")
        cases = (
            (
                expired,
                OAuthCallback(
                    state=expired.state,
                    code="one-time-code",
                    returned_scopes=("email.read", "calendar.read"),
                    issuer=ISSUER,
                    redirect_uri=REDIRECT,
                    received_at=now + timedelta(minutes=11),
                ),
                OAuthReplayError,
            ),
            (
                mismatched,
                OAuthCallback(
                    state=mismatched.state,
                    code="one-time-code",
                    returned_scopes=("email.read", "calendar.read"),
                    issuer="https://attacker.example",
                    redirect_uri=REDIRECT,
                    received_at=now + timedelta(minutes=1),
                ),
                OAuthBindingError,
            ),
            (
                scope_denied,
                OAuthCallback(
                    state=scope_denied.state,
                    code="one-time-code",
                    returned_scopes=("email.read",),
                    issuer=ISSUER,
                    redirect_uri=REDIRECT,
                    received_at=now + timedelta(minutes=1),
                ),
                OAuthScopeError,
            ),
        )
        for _, invalid_callback, error_type in cases:
            async with sessions() as session:
                async with execution.transaction(session, context):
                    with pytest.raises(error_type):
                        await _service(
                            session, context, keys, dispatcher, sink
                        ).complete(invalid_callback)

        assert dispatcher.calls == 1
        assert sink.calls == 1

        database = await asyncpg.connect(_database_url(database_name))
        try:
            legacy_table_counts = [
                await database.fetchval(f"SELECT count(*) FROM {table}")
                for table in (
                    "gmail_oauth_states",
                    "calendar_oauth_states",
                    "drive_oauth_states",
                )
            ]
            assert legacy_table_counts == [0, 0, 0]
        finally:
            await database.close()

        refused = _migration(
            database_name, H2_02_REVISION, direction="downgrade"
        )
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_03_cancel_and_provider_denial_are_terminal() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_03_REVISION)
        organization_id, workspace_id, _, owner_id, _ = (
            await _seed_business_workspace(database_name)
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        connection_id = await _seed_connection(sessions, execution, context)
        keys = MockManagedKeyProvider({KEY: b"k" * 32})
        dispatcher = RecordingDispatcher()
        sink = RecordingSink()
        now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
        async with sessions() as session:
            async with execution.transaction(session, context):
                service = _service(session, context, keys, dispatcher, sink)
                cancelled = await service.start(
                    _create(connection_id),
                    pkce_verifier=b"private-pkce-verifier",
                    key_reference=KEY,
                    idempotency_key="cancelled",
                    now=now,
                )
                await service.cancel(cancelled.transaction.id, now=now)
            async with execution.transaction(session, context):
                with pytest.raises(OAuthReplayError):
                    await _service(
                        session, context, keys, dispatcher, sink
                    ).complete(
                        OAuthCallback(
                            state=cancelled.state,
                            code="one-time-code",
                            returned_scopes=("email.read", "calendar.read"),
                            issuer=ISSUER,
                            redirect_uri=REDIRECT,
                            received_at=now,
                        )
                    )

            async with execution.transaction(session, context):
                service = _service(session, context, keys, dispatcher, sink)
                denied = await service.start(
                    _create(connection_id),
                    pkce_verifier=b"private-pkce-verifier",
                    key_reference=KEY,
                    idempotency_key="denied",
                    now=now,
                )
            async with execution.transaction(session, context):
                with pytest.raises(OAuthBindingError, match="provider denied"):
                    await _service(
                        session, context, keys, dispatcher, sink
                    ).complete(
                        OAuthCallback(
                            state=denied.state,
                            code=None,
                            returned_scopes=(),
                            issuer=ISSUER,
                            redirect_uri=REDIRECT,
                            received_at=now,
                            error_code="access_denied",
                            error_description="user cancelled",
                        )
                    )
            record = await session.get(
                OAuthTransaction, (workspace_id, denied.transaction.id)
            )
            assert record is not None
            assert record.status == "failed"
            assert record.failure_code == "provider_denied"
            assert dispatcher.calls == 0
            assert sink.calls == 0
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
