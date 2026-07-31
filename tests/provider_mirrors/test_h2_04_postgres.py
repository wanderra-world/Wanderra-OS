"""PostgreSQL acceptance tests for H2-04 provider mirrors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.connections import ConnectionCreate, ConnectionService
from app.execution_context import ExecutionContext, ExecutionContextService
from app.provider_mirrors import (
    AuthorityPolicy,
    ComparisonDecision,
    MirrorCreate,
    MirrorState,
    ProviderMirrorError,
    ProviderMirrorReplayError,
    ProviderMirrorService,
    ProviderObservation,
)
from app.provider_mirrors.models import (
    ProviderExternalReference,
    ProviderMirrorComparison,
    ProviderMirrorConflict,
)
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _migration,
    _require_migration,
    _seed_business_workspace,
)

H2_04_REVISION = "0017_h2_provider_mirrors"
H2_03_REVISION = "0016_h2_oauth_transactions"
NOW = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
HASH_1 = "1" * 64
HASH_2 = "2" * 64
HASH_3 = "3" * 64


class AllowAuthorizer:
    async def authorize(
        self, context: ExecutionContext, permission_key: str
    ) -> bool:
        return permission_key == "manage_workspace"


def _observation(
    *,
    version: str = "v1",
    normalized_hash: str = HASH_1,
    deleted: bool = False,
) -> ProviderObservation:
    return ProviderObservation(
        provider_version=version,
        etag=f'"{version}"',
        provider_updated_at=NOW,
        normalized_hash=normalized_hash,
        deleted=deleted,
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
                    display_name="H2-04 mirror connection",
                    granted_scopes=(),
                )
            )
    return connection_id


def _service(session, context: ExecutionContext) -> ProviderMirrorService:
    return ProviderMirrorService(
        session,
        context,
        authorizer=AllowAuthorizer(),
    )


def _create(
    connection_id: UUID,
    *,
    authority: AuthorityPolicy = AuthorityPolicy.PROVIDER_AUTHORITATIVE,
) -> MirrorCreate:
    return MirrorCreate(
        mirror_id=uuid4(),
        external_reference_id=uuid4(),
        connection_id=connection_id,
        resource_type="storage.file",
        external_id=f"external-{uuid4()}",
        authority=authority,
        field_authority={"name": authority},
        observation=_observation(),
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_04_additive_migration_forced_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H2_04_REVISION)
        _require_migration(database_name, H2_04_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H2_04_REVISION
            for table in (
                "provider_mirrors",
                "provider_external_references",
                "provider_mirror_conflicts",
                "provider_mirror_comparisons",
            ):
                row = await database.fetchrow(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class WHERE oid = $1::regclass
                    """,
                    table,
                )
                assert row and row["relrowsecurity"] and row["relforcerowsecurity"]
        finally:
            await database.close()
        _require_migration(database_name, H2_03_REVISION, direction="downgrade")
        _require_migration(database_name, H2_04_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_04_observation_replay_reference_and_tombstone() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_04_REVISION)
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
        command = _create(connection_id)

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = _service(session, context)
                created = await service.observe_new(
                    command,
                    idempotency_key="create-observation",
                    now=NOW,
                )
                replayed = await service.observe_new(
                    command,
                    idempotency_key="create-observation",
                    now=NOW,
                )
                assert replayed.id == created.id
                await service.link_canonical(
                    mirror_id=created.id,
                    reference_type="future.file",
                    reference_id=uuid4(),
                    approval_reference="approved-command-1",
                    now=NOW,
                )

            async with execution.transaction(session, context):
                updated = await _service(session, context).observe(
                    mirror_id=created.id,
                    observation=_observation(
                        version="v2", normalized_hash=HASH_2
                    ),
                    idempotency_key="inbound-v2",
                    now=NOW + timedelta(minutes=1),
                )
                assert updated.provider_version == "v2"
                assert updated.sync_state == MirrorState.SYNCED.value

            async with execution.transaction(session, context):
                tombstone = await _service(session, context).observe(
                    mirror_id=created.id,
                    observation=_observation(
                        version="v3", normalized_hash="", deleted=True
                    ),
                    idempotency_key="provider-delete",
                    now=NOW + timedelta(minutes=2),
                )
                assert tombstone.sync_state == MirrorState.TOMBSTONED.value

            reference = await session.get(
                ProviderExternalReference,
                (workspace_id, command.external_reference_id),
            )
            assert reference is not None
            assert reference.canonical_reference_id is not None
            assert await session.scalar(
                select(func.count()).select_from(ProviderMirrorComparison)
            ) == 3
            assert await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("provider_mirror.%"))
            ) == 4
            assert await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type.like("provider_mirror.%"))
            ) == 4
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h2_04_conflict_outbound_decision_resolution_and_guarded_rollback() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_04_REVISION)
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
        command = _create(
            connection_id, authority=AuthorityPolicy.ATLAS_AUTHORITATIVE
        )

        async with sessions() as session:
            async with execution.transaction(session, context):
                created = await _service(session, context).observe_new(
                    command, idempotency_key="create", now=NOW
                )
            async with execution.transaction(session, context):
                conflicted = await _service(session, context).observe(
                    mirror_id=created.id,
                    observation=_observation(
                        version="v2", normalized_hash=HASH_2
                    ),
                    idempotency_key="conflict",
                    now=NOW,
                )
                assert conflicted.sync_state == MirrorState.CONFLICT.value
                conflict = await session.scalar(
                    select(ProviderMirrorConflict).where(
                        ProviderMirrorConflict.mirror_id == created.id,
                        ProviderMirrorConflict.status == "open",
                    )
                )
                assert conflict is not None

            async with execution.transaction(session, context):
                decision = await _service(session, context).decide_outbound(
                    mirror_id=created.id,
                    expected_provider_version="stale",
                    proposed_hash=HASH_3,
                    idempotency_key="outbound-stale",
                    now=NOW,
                )
                assert (
                    decision.decision
                    == ComparisonDecision.REFRESH_REQUIRED.value
                )

            async with execution.transaction(session, context):
                resolved = await _service(session, context).resolve_conflict(
                    conflict_id=conflict.id,
                    resolution_hash=HASH_3,
                    resolution="keep_atlas",
                    idempotency_key="resolve-one",
                    now=NOW,
                )
                assert resolved.status == "resolved"

            async with execution.transaction(session, context):
                with pytest.raises(ProviderMirrorReplayError):
                    await _service(session, context).resolve_conflict(
                        conflict_id=conflict.id,
                        resolution_hash=HASH_2,
                        resolution="accept_provider",
                        idempotency_key="resolve-one",
                        now=NOW,
                    )

        refused = _migration(
            database_name, H2_03_REVISION, direction="downgrade"
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
async def test_h2_04_duplicate_identity_and_cross_workspace_attacks_fail() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H2_04_REVISION)
        (
            organization_id,
            first_workspace_id,
            second_workspace_id,
            owner_id,
            _,
        ) = await _seed_business_workspace(
            database_name
        )
        first_context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=first_workspace_id,
            owner_id=owner_id,
        )
        second_context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=second_workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        first_connection = await _seed_connection(
            sessions, execution, first_context
        )
        await _seed_connection(sessions, execution, second_context)
        command = _create(first_connection)

        async with sessions() as session:
            async with execution.transaction(session, first_context):
                mirror = await _service(session, first_context).observe_new(
                    command, idempotency_key="first", now=NOW
                )
                mirror_id = mirror.id
            with pytest.raises(IntegrityError):
                async with execution.transaction(session, first_context):
                    duplicate = MirrorCreate(
                        mirror_id=uuid4(),
                        external_reference_id=uuid4(),
                        connection_id=command.connection_id,
                        resource_type=command.resource_type,
                        external_id=command.external_id,
                        authority=command.authority,
                        field_authority=command.field_authority,
                        observation=command.observation,
                    )
                    await _service(session, first_context).observe_new(
                        duplicate, idempotency_key="duplicate", now=NOW
                    )
            async with execution.transaction(session, second_context):
                with pytest.raises(ProviderMirrorError, match="unavailable"):
                    await _service(session, second_context).observe(
                            mirror_id=mirror_id,
                        observation=_observation(
                            version="v2", normalized_hash=HASH_2
                        ),
                        idempotency_key="cross-workspace",
                        now=NOW,
                    )
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
