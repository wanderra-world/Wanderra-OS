"""PostgreSQL acceptance evidence for H1-08 audit and messaging."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.execution_context import (
    ActorContext,
    ExecutionContext,
    ExecutionContextService,
    RequestContext,
    TenantContext,
)
from app.messaging import (
    CommandEnvelope,
    CommandService,
    ConcurrencyConflict,
    ConsumerResult,
    EventConsumerService,
    EventEnvelope,
    IdempotencyConflict,
    ReplayDenied,
)
from app.messaging.models import EventQuarantine, InboxEvent
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _migration,
    _require_migration,
    _seed_business_workspace,
)

H1_08_REVISION = "0012_h1_audit_messaging"
H1_07_REVISION = "0011_h1_envelopes"


def execution_context(
    organization_id: UUID,
    workspace_id: UUID,
    cell_id: UUID,
    actor_id: UUID,
) -> ExecutionContext:
    return ExecutionContext(
        request=RequestContext(
            request_id=f"request-{uuid4()}",
            correlation_id=f"correlation-{uuid4()}",
        ),
        actor=ActorContext(
            actor_id=actor_id,
            session_id=uuid4(),
            membership_id=uuid4(),
            authorization_decision_id=uuid4(),
        ),
        tenant=TenantContext(
            organization_id=organization_id,
            workspace_id=workspace_id,
            cell_id=cell_id,
        ),
    )


def command(
    context: ExecutionContext,
    aggregate_id: UUID,
    *,
    key: str,
    expected_version: int,
    name: str = "Atlas",
) -> CommandEnvelope:
    return CommandEnvelope(
        workspace_id=context.tenant.workspace_id,
        actor_id=context.actor.actor_id,
        command_type="project.renamed",
        idempotency_key=key,
        aggregate_type="project",
        aggregate_id=aggregate_id,
        expected_version=expected_version,
        correlation_id=context.request.correlation_id,
        payload={"name": name},
    )


def event(
    context: ExecutionContext,
    aggregate_id: UUID,
    sequence: int,
    *,
    schema_major: int = 1,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        event_type="project.renamed",
        schema_major=schema_major,
        schema_minor=0,
        workspace_id=context.tenant.workspace_id,
        aggregate_type="project",
        aggregate_id=aggregate_id,
        aggregate_sequence=sequence,
        actor_id=context.actor.actor_id,
        correlation_id=context.request.correlation_id,
        occurred_at=datetime.now(UTC),
        classification="internal",
        payload={"name": f"Atlas {sequence}"},
    )


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_08_migration_rls_immutability_tamper_and_rollback() -> None:
    admin, database_name = await _create_database()
    rls_role = f"h1_08_reader_{uuid4().hex}"
    try:
        _require_migration(database_name, H1_07_REVISION)
        (
            organization_id,
            workspace_id,
            second_workspace_id,
            owner_id,
            _,
        ) = await _seed_business_workspace(database_name)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                """
                INSERT INTO audit_events (
                    workspace_id, id, actor_type, actor_id, action,
                    target_type, target_id, outcome, details
                )
                VALUES ($1, $2, 'user', $3, 'legacy.action',
                        'project', $4, 'success', '{}')
                """,
                workspace_id,
                uuid4(),
                owner_id,
                uuid4(),
            )
        finally:
            await database.close()

        _require_migration(database_name, H1_08_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert await database.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == H1_08_REVISION
            assert await database.fetchval(
                """
                SELECT bool_and(relrowsecurity AND relforcerowsecurity)
                FROM pg_class
                WHERE oid IN (
                    'audit_chain_heads'::regclass,
                    'command_idempotency'::regclass,
                    'aggregate_versions'::regclass,
                    'inbox_events'::regclass,
                    'consumer_sequences'::regclass,
                    'event_quarantine'::regclass
                )
                """
            )
            assert await database.fetchval(
                "SELECT verify_audit_chain($1)", workspace_id
            )
            audit_id = await database.fetchval(
                "SELECT id FROM audit_events WHERE workspace_id = $1",
                workspace_id,
            )
            with pytest.raises(asyncpg.RaiseError, match="immutable"):
                await database.execute(
                    """
                    UPDATE audit_events SET outcome = 'failure'
                    WHERE workspace_id = $1 AND id = $2
                    """,
                    workspace_id,
                    audit_id,
                )
            with pytest.raises(asyncpg.RaiseError, match="immutable"):
                await database.execute(
                    "DELETE FROM audit_events WHERE workspace_id = $1 AND id = $2",
                    workspace_id,
                    audit_id,
                )
            await database.execute(
                "ALTER TABLE audit_events DISABLE TRIGGER audit_events_are_immutable"
            )
            await database.execute(
                """
                UPDATE audit_events SET details = '{"tampered": true}'
                WHERE workspace_id = $1 AND id = $2
                """,
                workspace_id,
                audit_id,
            )
            await database.execute(
                "ALTER TABLE audit_events ENABLE TRIGGER audit_events_are_immutable"
            )
            assert not await database.fetchval(
                "SELECT verify_audit_chain($1)", workspace_id
            )
            await database.execute(
                """
                INSERT INTO aggregate_versions (
                    workspace_id, aggregate_type, aggregate_id, version
                )
                VALUES ($1, 'project', $2, 1), ($3, 'project', $4, 1)
                """,
                workspace_id,
                uuid4(),
                second_workspace_id,
                uuid4(),
            )
            await database.execute(
                f"CREATE ROLE {rls_role} NOLOGIN NOSUPERUSER NOBYPASSRLS"
            )
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {rls_role}")
            await database.execute(
                f"GRANT SELECT ON aggregate_versions TO {rls_role}"
            )
            await database.execute(f"SET ROLE {rls_role}")
            await database.execute(
                "SELECT set_config('atlas.workspace_id', $1, false)",
                str(workspace_id),
            )
            assert await database.fetchval(
                "SELECT count(*) FROM aggregate_versions"
            ) == 1
            assert not await database.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM aggregate_versions WHERE workspace_id = $1
                )
                """,
                second_workspace_id,
            )
            await database.execute("RESET ROLE")
            await database.execute(f"DROP OWNED BY {rls_role}")
            await database.execute(f"DROP ROLE {rls_role}")
            await database.execute("DELETE FROM aggregate_versions")
        finally:
            await database.close()

        rollback = _migration(
            database_name,
            H1_07_REVISION,
            direction="downgrade",
        )
        assert rollback.returncode == 0, rollback.stderr
        _require_migration(database_name, H1_08_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            await database.execute(
                """
                INSERT INTO command_idempotency (
                    workspace_id, actor_id, command_type, idempotency_key,
                    request_digest, correlation_id
                )
                VALUES ($1, $2, 'project.rename', 'rollback-guard',
                        repeat('0', 64), 'correlation')
                """,
                workspace_id,
                owner_id,
            )
        finally:
            await database.close()
        refused = _migration(
            database_name,
            H1_07_REVISION,
            direction="downgrade",
        )
        assert refused.returncode != 0
        assert "reviewed forward fix" in refused.stderr
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_08_atomic_command_idempotency_and_concurrency() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H1_08_REVISION)
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
        finally:
            await database.close()
        context = execution_context(
            organization_id, workspace_id, cell_id, owner_id
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        context_service = ExecutionContextService()
        aggregate_id = uuid4()

        async with sessions() as session:
            async with context_service.transaction(session, context):
                service = CommandService(session, context)
                first = await service.record(
                    command(
                        context,
                        aggregate_id,
                        key="rename-1",
                        expected_version=0,
                    ),
                    event_type="project.renamed",
                    event_payload={"name": "Atlas"},
                )
            async with context_service.transaction(session, context):
                replay = await CommandService(session, context).record(
                    command(
                        context,
                        aggregate_id,
                        key="rename-1",
                        expected_version=0,
                    ),
                    event_type="project.renamed",
                    event_payload={"name": "Atlas"},
                )
                assert replay.replayed
                assert replay.event_id == first.event_id
            async with context_service.transaction(session, context):
                with pytest.raises(IdempotencyConflict):
                    await CommandService(session, context).record(
                        command(
                            context,
                            aggregate_id,
                            key="rename-1",
                            expected_version=0,
                            name="Changed",
                        ),
                        event_type="project.renamed",
                        event_payload={"name": "Changed"},
                    )
            async with context_service.transaction(session, context):
                with pytest.raises(ConcurrencyConflict):
                    await CommandService(session, context).record(
                        command(
                            context,
                            aggregate_id,
                            key="rename-stale",
                            expected_version=0,
                        ),
                        event_type="project.renamed",
                        event_payload={"name": "Atlas"},
                    )
            audit_count = await session.scalar(
                select(func.count()).select_from(AuditEvent)
            )
            outbox_count = await session.scalar(
                select(func.count()).select_from(OutboxEvent)
            )
            assert audit_count == 1
            assert outbox_count == 1

        second_aggregate = uuid4()

        async def competing(key: str) -> str:
            async with sessions() as session:
                try:
                    async with context_service.transaction(session, context):
                        await CommandService(session, context).record(
                            command(
                                context,
                                second_aggregate,
                                key=key,
                                expected_version=0,
                            ),
                            event_type="project.renamed",
                            event_payload={"name": key},
                        )
                    return "accepted"
                except ConcurrencyConflict:
                    return "stale"

        assert sorted(
            await asyncio.gather(competing("race-a"), competing("race-b"))
        ) == ["accepted", "stale"]

        async with sessions() as session:
            with pytest.raises(RuntimeError, match="injected"):
                async with context_service.transaction(session, context):
                    await CommandService(session, context).record(
                        command(
                            context,
                            uuid4(),
                            key="rolled-back",
                            expected_version=0,
                        ),
                        event_type="project.renamed",
                        event_payload={"name": "rollback"},
                    )
                    raise RuntimeError("injected")
            assert await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.idempotency_key == "rolled-back")
            ) == 0
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h1_08_consumer_gap_schema_poison_and_authorized_replay() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H1_08_REVISION)
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
        finally:
            await database.close()
        context = execution_context(
            organization_id, workspace_id, cell_id, owner_id
        )
        engine = create_async_engine(
            _database_url(database_name, async_sqlalchemy=True)
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        context_service = ExecutionContextService()
        aggregate_id = uuid4()
        first = event(context, aggregate_id, 1)
        gap = event(context, aggregate_id, 3)

        async with sessions() as session:
            async with context_service.transaction(session, context):
                service = EventConsumerService(
                    session,
                    context,
                    supported_schemas={"project.renamed": 1},
                )
                assert await service.consume(
                    first, consumer_id="projection"
                ) == ConsumerResult.PROCESSED
                assert await service.consume(
                    first, consumer_id="projection"
                ) == ConsumerResult.DUPLICATE
                assert await service.consume(
                    gap, consumer_id="projection"
                ) == ConsumerResult.GAP
                quarantine = await session.scalar(
                    select(EventQuarantine).where(
                        EventQuarantine.event_id == gap.event_id
                    )
                )
                assert quarantine is not None
                assert await service.replay(
                    quarantine_id=quarantine.id,
                    authorization_decision_id=context.actor.authorization_decision_id,
                    dry_run=True,
                ) == ConsumerResult.DRY_RUN
                with pytest.raises(ReplayDenied):
                    await service.replay(
                        quarantine_id=quarantine.id,
                        authorization_decision_id=uuid4(),
                        dry_run=False,
                    )
                assert await service.consume(
                    event(context, aggregate_id, 2),
                    consumer_id="projection",
                ) == ConsumerResult.PROCESSED
                assert await service.replay(
                    quarantine_id=quarantine.id,
                    authorization_decision_id=context.actor.authorization_decision_id,
                    dry_run=False,
                ) == ConsumerResult.PROCESSED
                assert await service.consume(
                    event(context, uuid4(), 1, schema_major=2),
                    consumer_id="projection",
                ) == ConsumerResult.QUARANTINED

                async def poison() -> None:
                    raise RuntimeError("poison")

                assert await service.consume(
                    event(context, uuid4(), 1),
                    consumer_id="projection",
                    apply=poison,
                ) == ConsumerResult.QUARANTINED
            assert await session.scalar(
                select(func.count())
                .select_from(InboxEvent)
                .where(InboxEvent.status == "quarantined")
            ) == 2
            assert await session.scalar(
                text("SELECT verify_audit_chain(:workspace_id)"),
                {"workspace_id": workspace_id},
            )
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
