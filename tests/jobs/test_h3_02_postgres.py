"""PostgreSQL acceptance tests for H3-02 durable execution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.execution_context import ExecutionContextService
from app.jobs import (
    FailureCategory,
    IdempotencyConflict,
    JobDefinitionSpec,
    JobEnqueue,
    JobError,
    JobStatus,
    LeaseConflict,
    MisfirePolicy,
    ScheduleKind,
    ScheduleSpec,
)
from app.jobs.models import JobAttempt, JobDeadLetter, JobInstance
from app.jobs.service import JobService
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

H3_02_REVISION = "0023_h3_durable_execution"
H3_01_HEAD = "0022_h3_resource_graph"
H3_02_TABLES = (
    "job_definitions",
    "job_instances",
    "job_attempts",
    "job_dead_letters",
    "job_schedules",
    "job_operator_controls",
)
NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class AllowAuthorizer:
    async def authorize(self, _context, _permission_key: str) -> bool:
        return True


def _service(session, context) -> JobService:
    return JobService(session, context, authorizer=AllowAuthorizer())


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_02_additive_migration_forced_rls_and_empty_rollback() -> None:
    admin, database_name = await _create_database()
    try:
        _require_migration(database_name, H3_02_REVISION)
        _require_migration(database_name, H3_02_REVISION)
        database = await asyncpg.connect(_database_url(database_name))
        try:
            assert (
                await database.fetchval("SELECT version_num FROM alembic_version") == H3_02_REVISION
            )
            rows = await database.fetch(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE relname = ANY($1::text[])
                """,
                list(H3_02_TABLES),
            )
            assert {row["relname"] for row in rows} == set(H3_02_TABLES)
            assert all(row["relrowsecurity"] for row in rows)
            assert all(row["relforcerowsecurity"] for row in rows)
        finally:
            await database.close()
        _require_migration(database_name, H3_01_HEAD, direction="downgrade")
        _require_migration(database_name, H3_02_REVISION)
    finally:
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_02_idempotent_lifecycle_recovery_dead_letter_replay_and_audit() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_02_REVISION)
        (
            organization_id,
            workspace_id,
            other_workspace_id,
            owner_id,
            _,
        ) = await _seed_business_workspace(database_name)
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        other_context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=other_workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        definition_id = uuid4()
        job_id = uuid4()
        async with sessions() as session:
            async with execution.transaction(session, context):
                service = _service(session, context)
                await service.register_definition(
                    JobDefinitionSpec(
                        definition_id=definition_id,
                        key="synthetic",
                        version=1,
                        handler_key="synthetic.run",
                    ),
                    now=NOW,
                )
                command = JobEnqueue(
                    job_id=job_id,
                    definition_id=definition_id,
                    idempotency_key="synthetic-1",
                    command_type="synthetic.run",
                    payload={"value": 1},
                    available_at=NOW,
                    deadline=NOW + timedelta(minutes=10),
                )
                first = await service.enqueue(command, now=NOW)
                duplicate = await service.enqueue(command, now=NOW)
                assert duplicate.id == first.id
                with pytest.raises(IdempotencyConflict):
                    await service.enqueue(
                        JobEnqueue(
                            job_id=uuid4(),
                            definition_id=definition_id,
                            idempotency_key="synthetic-1",
                            command_type="synthetic.run",
                            payload={"value": 2},
                            available_at=NOW,
                            deadline=NOW + timedelta(minutes=10),
                        ),
                        now=NOW,
                    )

                lease = await service.claim_next(worker_id="worker-a", now=NOW)
                assert lease is not None and lease.job_id == job_id and lease.attempt_number == 1
                with pytest.raises(LeaseConflict):
                    await service.heartbeat(job_id, worker_id="worker-b", now=NOW)
                await service.heartbeat(job_id, worker_id="worker-a", now=NOW)
                await service.fail(
                    job_id,
                    worker_id="worker-a",
                    category=FailureCategory.TRANSIENT,
                    error_code="temporary",
                    now=NOW,
                )
                retry_lease = await service.claim_next(
                    worker_id="worker-b", now=NOW + timedelta(seconds=1)
                )
                assert retry_lease is not None and retry_lease.attempt_number == 2
                await service.succeed(
                    job_id,
                    worker_id="worker-b",
                    result_digest="0" * 64,
                    now=NOW + timedelta(seconds=2),
                )

                cancelled = await service.enqueue(
                    JobEnqueue(
                        job_id=uuid4(),
                        definition_id=definition_id,
                        idempotency_key="cancel-me",
                        command_type="synthetic.run",
                        payload={},
                        available_at=NOW,
                        deadline=NOW + timedelta(minutes=10),
                    ),
                    now=NOW,
                )
                await service.cancel(cancelled.id, reason="operator request", now=NOW)
                assert cancelled.status == JobStatus.CANCELLED.value

                poison = await service.enqueue(
                    JobEnqueue(
                        job_id=uuid4(),
                        definition_id=definition_id,
                        idempotency_key="poison",
                        command_type="synthetic.run",
                        payload={},
                        available_at=NOW,
                        deadline=NOW + timedelta(minutes=10),
                    ),
                    now=NOW,
                )
                poison_lease = await service.claim_next(worker_id="worker-c", now=NOW)
                assert poison_lease is not None and poison_lease.job_id == poison.id
                await service.fail(
                    poison.id,
                    worker_id="worker-c",
                    category=FailureCategory.POISON,
                    error_code="invalid_envelope",
                    now=NOW,
                )
                assert poison.status == JobStatus.DEAD_LETTERED.value
                replay = await service.replay(
                    poison.id,
                    new_job_id=uuid4(),
                    idempotency_key="poison-replay-1",
                    reason="handler corrected",
                    now=NOW + timedelta(seconds=3),
                )
                assert replay.replay_of_job_id == poison.id

            async with execution.transaction(session, context):
                assert await session.scalar(select(func.count()).select_from(JobInstance)) == 4
                assert await session.scalar(select(func.count()).select_from(JobAttempt)) == 3
                assert await session.scalar(select(func.count()).select_from(JobDeadLetter)) == 1
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.target_type.in_(("job_definition", "job")))
                    )
                    >= 12
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.aggregate_type.in_(("job_definition", "job")))
                    )
                    >= 12
                )

            async with execution.transaction(session, other_context):
                with pytest.raises(JobError, match="job does not exist"):
                    await _service(session, other_context).cancel(
                        job_id,
                        reason="cross-workspace attack",
                        now=NOW,
                    )

        rls_role = f"h3_02_runtime_{uuid4().hex}"
        database = await asyncpg.connect(_database_url(database_name))
        try:
            cell_id = await database.fetchval(
                "SELECT cell_id FROM workspaces WHERE workspace_id = $1", workspace_id
            )
            await database.execute(f"CREATE ROLE {rls_role} NOLOGIN NOSUPERUSER NOBYPASSRLS")
            await database.execute(f"GRANT USAGE ON SCHEMA public TO {rls_role}")
            await database.execute(f"GRANT SELECT ON {', '.join(H3_02_TABLES)} TO {rls_role}")
            await database.execute(f"SET ROLE {rls_role}")
            await database.execute(
                "SELECT set_config('atlas.workspace_id', $1, false)",
                str(other_workspace_id),
            )
            await database.execute(
                "SELECT set_config('atlas.organization_id', $1, false)",
                str(organization_id),
            )
            await database.execute("SELECT set_config('atlas.cell_id', $1, false)", str(cell_id))
            assert await database.fetchval("SELECT count(*) FROM job_instances") == 0
            await database.execute(
                "SELECT set_config('atlas.workspace_id', $1, false)", str(workspace_id)
            )
            assert await database.fetchval("SELECT count(*) FROM job_instances") == 4
            await database.execute("RESET ROLE")
            await database.execute(f"DROP OWNED BY {rls_role}")
            await database.execute(f"DROP ROLE {rls_role}")
        finally:
            await database.close()

        downgrade = _migration(database_name, H3_01_HEAD, direction="downgrade")
        assert downgrade.returncode != 0
        assert "reviewed forward fix" in downgrade.stderr
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_02_concurrent_claim_uses_one_live_lease() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_02_REVISION)
        organization_id, workspace_id, _, owner_id, _ = await _seed_business_workspace(
            database_name
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        definition_id = uuid4()
        async with sessions() as session:
            async with execution.transaction(session, context):
                service = _service(session, context)
                await service.register_definition(
                    JobDefinitionSpec(
                        definition_id=definition_id,
                        key="concurrent",
                        version=1,
                        handler_key="synthetic.concurrent",
                    ),
                    now=NOW,
                )
                await service.enqueue(
                    JobEnqueue(
                        job_id=uuid4(),
                        definition_id=definition_id,
                        idempotency_key="only-once",
                        command_type="synthetic.concurrent",
                        payload={},
                        available_at=NOW,
                        deadline=NOW + timedelta(minutes=5),
                    ),
                    now=NOW,
                )

        first_ready = asyncio.Event()
        release_first = asyncio.Event()

        async def first_claim():
            async with sessions() as session:
                async with execution.transaction(session, context):
                    lease = await _service(session, context).claim_next(
                        worker_id="worker-1", now=NOW
                    )
                    first_ready.set()
                    await release_first.wait()
                    return lease

        async def second_claim():
            await first_ready.wait()
            async with sessions() as session:
                async with execution.transaction(session, context):
                    lease = await _service(session, context).claim_next(
                        worker_id="worker-2", now=NOW
                    )
                    release_first.set()
                    return lease

        first, second = await asyncio.gather(first_claim(), second_claim())
        assert first is not None
        assert second is None
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_02_crash_recovery_pause_cancellation_and_schedule_replay_safety() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_02_REVISION)
        organization_id, workspace_id, _, owner_id, _ = await _seed_business_workspace(
            database_name
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        definition_id = uuid4()
        async with sessions() as session:
            async with execution.transaction(session, context):
                service = _service(session, context)
                await service.register_definition(
                    JobDefinitionSpec(
                        definition_id=definition_id,
                        key="recovery",
                        version=1,
                        handler_key="synthetic.recovery",
                    ),
                    now=NOW,
                )
                crashed = await service.enqueue(
                    JobEnqueue(
                        job_id=uuid4(),
                        definition_id=definition_id,
                        idempotency_key="crash",
                        command_type="synthetic.recovery",
                        payload={},
                        available_at=NOW,
                        deadline=NOW + timedelta(minutes=5),
                    ),
                    now=NOW,
                )
                assert await service.claim_next(worker_id="crashed-worker", now=NOW)
                assert (
                    await service.claim_next(
                        worker_id="recovery-worker", now=NOW + timedelta(seconds=31)
                    )
                    is None
                )
                recovered = await service.claim_next(
                    worker_id="recovery-worker", now=NOW + timedelta(seconds=32)
                )
                assert recovered is not None
                assert recovered.job_id == crashed.id
                assert recovered.attempt_number == 2
                await service.succeed(
                    crashed.id,
                    worker_id="recovery-worker",
                    result_digest="1" * 64,
                    now=NOW + timedelta(seconds=33),
                )

                paused_job = await service.enqueue(
                    JobEnqueue(
                        job_id=uuid4(),
                        definition_id=definition_id,
                        idempotency_key="paused",
                        command_type="synthetic.recovery",
                        payload={},
                        available_at=NOW,
                        deadline=NOW + timedelta(minutes=5),
                    ),
                    now=NOW,
                )
                await service.set_paused(
                    scope_type="workspace",
                    scope_reference=str(workspace_id),
                    paused=True,
                    reason="operator drill",
                    expected_version=0,
                    now=NOW,
                )
                assert await service.claim_next(worker_id="worker", now=NOW) is None
                await service.set_paused(
                    scope_type="workspace",
                    scope_reference=str(workspace_id),
                    paused=False,
                    reason="operator resume",
                    expected_version=1,
                    now=NOW + timedelta(seconds=1),
                )
                assert await service.claim_next(worker_id="worker", now=NOW) is not None
                await service.cancel(paused_job.id, reason="stop running work", now=NOW)
                with pytest.raises(JobError, match="cancellation observed"):
                    await service.heartbeat(paused_job.id, worker_id="worker", now=NOW)
                assert paused_job.status == JobStatus.CANCELLED.value

                schedule_id = uuid4()
                await service.register_schedule(
                    ScheduleSpec(
                        schedule_id=schedule_id,
                        definition_id=definition_id,
                        kind=ScheduleKind.ONCE,
                        first_due_at=NOW,
                        misfire_policy=MisfirePolicy.FIRE_ONCE,
                    ),
                    command_type="synthetic.recovery",
                    payload={"source": "schedule"},
                    idempotency_prefix="once",
                    job_deadline_seconds=300,
                    now=NOW,
                )
                await service.set_schedule_paused(
                    schedule_id,
                    paused=True,
                    reason="schedule drill",
                    expected_version=1,
                    now=NOW,
                )
                assert await service.dispatch_due_schedules(now=NOW) == ()
                with pytest.raises(JobError, match="version precondition"):
                    await service.set_schedule_paused(
                        schedule_id,
                        paused=False,
                        reason="stale resume",
                        expected_version=1,
                        now=NOW,
                    )
                await service.set_schedule_paused(
                    schedule_id,
                    paused=False,
                    reason="schedule resume",
                    expected_version=2,
                    now=NOW,
                )
                first_dispatch = await service.dispatch_due_schedules(now=NOW)
                second_dispatch = await service.dispatch_due_schedules(now=NOW)
                assert len(first_dispatch) == 1
                assert second_dispatch == ()

            async with execution.transaction(session, context):
                attempts = await session.scalars(
                    select(JobAttempt)
                    .where(JobAttempt.job_id == crashed.id)
                    .order_by(JobAttempt.attempt_number)
                )
                values = tuple(attempts)
                assert [attempt.status for attempt in values] == ["abandoned", "succeeded"]
                assert values[0].error_code == "lease_expired"
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()


@pytest.mark.skipif(
    SOURCE_DATABASE_URL is None,
    reason="H1_TEST_DATABASE_URL or H0_TEST_DATABASE_URL is required",
)
async def test_h3_02_concurrent_enqueue_and_rate_quota_are_deterministic() -> None:
    admin, database_name = await _create_database()
    engine = None
    try:
        _require_migration(database_name, H3_02_REVISION)
        organization_id, workspace_id, _, owner_id, _ = await _seed_business_workspace(
            database_name
        )
        context = await _context_for_owner(
            database_name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(database_name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        execution = ExecutionContextService()
        definition_id = uuid4()
        async with sessions() as session:
            async with execution.transaction(session, context):
                await _service(session, context).register_definition(
                    JobDefinitionSpec(
                        definition_id=definition_id,
                        key="quota",
                        version=1,
                        handler_key="synthetic.quota",
                    ),
                    now=NOW,
                )

        def command(job_id):
            return JobEnqueue(
                job_id=job_id,
                definition_id=definition_id,
                idempotency_key="same-key",
                command_type="synthetic.quota",
                payload={"same": True},
                available_at=NOW,
                deadline=NOW + timedelta(minutes=5),
            )

        async def concurrent_enqueue(job_id):
            async with sessions() as session:
                async with execution.transaction(session, context):
                    return await _service(session, context).enqueue(command(job_id), now=NOW)

        first_id, second_id = uuid4(), uuid4()
        first, second = await asyncio.gather(
            concurrent_enqueue(first_id), concurrent_enqueue(second_id)
        )
        assert first.id == second.id
        assert first.id in {first_id, second_id}

        async with sessions() as session:
            async with execution.transaction(session, context):
                service = _service(session, context)
                for number in range(1, 120):
                    await service.enqueue(
                        JobEnqueue(
                            job_id=uuid4(),
                            definition_id=definition_id,
                            idempotency_key=f"quota-{number}",
                            command_type="synthetic.quota",
                            payload={"number": number},
                            available_at=NOW,
                            deadline=NOW + timedelta(minutes=5),
                        ),
                        now=NOW,
                    )
                with pytest.raises(JobError, match="rate quota"):
                    await service.enqueue(
                        JobEnqueue(
                            job_id=uuid4(),
                            definition_id=definition_id,
                            idempotency_key="quota-overflow",
                            command_type="synthetic.quota",
                            payload={},
                            available_at=NOW,
                            deadline=NOW + timedelta(minutes=5),
                        ),
                        now=NOW,
                    )
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, database_name)
        await admin.close()
