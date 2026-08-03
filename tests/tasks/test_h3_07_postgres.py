"""PostgreSQL, RLS, lifecycle, concurrency, and rollback evidence for H3-07."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.execution_context import ExecutionContextService
from app.resource_graph import ResourceCreate, ResourceGraphService, ResourceKind
from app.tasks import TaskCreate, TaskService, TaskStatus
from app.tasks.contracts import TaskConcurrencyError, TaskError
from app.tasks.models import Task, TaskCompletionEvidence, TaskReminder
from app.tenancy.models import AuditEvent, OutboxEvent
from tests.connections.test_h2_01_postgres import _context_for_owner
from tests.documents.test_h3_03_postgres import AllowAuthorizer
from tests.memberships.test_h1_04_postgres import (
    SOURCE_DATABASE_URL,
    _create_database,
    _database_url,
    _drop_database,
    _migration,
    _require_migration,
    _seed_business_workspace,
)

REVISION = "0028_h3_task_manager"
PREVIOUS = "0027_h3_search_context"
TABLES = (
    "tasks",
    "task_participants",
    "task_dependencies",
    "task_comments",
    "task_completion_evidence",
    "task_external_references",
    "task_reminders",
)


@pytest.mark.skipif(SOURCE_DATABASE_URL is None, reason="PostgreSQL URL is required")
async def test_h3_07_forced_rls_and_empty_rollback() -> None:
    admin, name = await _create_database()
    try:
        _require_migration(name, REVISION)
        database = await asyncpg.connect(_database_url(name))
        try:
            rows = await database.fetch(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY($1::text[])",
                list(TABLES),
            )
            assert {row["relname"] for row in rows} == set(TABLES)
            assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in rows)
        finally:
            await database.close()
        _require_migration(name, PREVIOUS, direction="downgrade")
        _require_migration(name, REVISION)
    finally:
        await _drop_database(admin, name)
        await admin.close()


@pytest.mark.skipif(SOURCE_DATABASE_URL is None, reason="PostgreSQL URL is required")
async def test_h3_07_lifecycle_evidence_isolation_audit_and_guarded_rollback() -> None:
    admin, name = await _create_database()
    engine = None
    try:
        _require_migration(name, REVISION)
        (
            organization_id,
            workspace_id,
            other_workspace_id,
            owner_id,
            _,
        ) = await _seed_business_workspace(name)
        context = await _context_for_owner(
            name,
            organization_id=organization_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        other_context = await _context_for_owner(
            name,
            organization_id=organization_id,
            workspace_id=other_workspace_id,
            owner_id=owner_id,
        )
        engine = create_async_engine(_database_url(name, async_sqlalchemy=True))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        task_id, resource_id = uuid4(), uuid4()
        due = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
        async with sessions() as session:
            async with ExecutionContextService().transaction(session, context):
                await ResourceGraphService(session, context, authorizer=AllowAuthorizer()).create(
                    ResourceCreate(
                        resource_id=resource_id,
                        projection_id=uuid4(),
                        kind=ResourceKind.TASK,
                    )
                )
                service = TaskService(session, context, authorizer=AllowAuthorizer())
                task = await service.create(
                    TaskCreate(
                        task_id=task_id,
                        resource_id=resource_id,
                        title="Complete H3-07",
                        priority="high",
                        classification="internal",
                        policy_version=1,
                        due_at=due,
                        timezone="Europe/Stockholm",
                        completion_evidence_required=True,
                    ),
                    now=datetime(2026, 8, 2, tzinfo=UTC),
                )
                reminder = await service.schedule_reminder(task.id, uuid4(), expected_version=1)
                with pytest.raises(TaskConcurrencyError):
                    await service.add_comment(task.id, uuid4(), "stale", expected_version=1)
                await service.add_completion_evidence(
                    task.id, uuid4(), "Verified by tests", expected_version=2
                )
                completed = await service.transition(
                    task.id, TaskStatus.COMPLETED, expected_version=3
                )
                assert completed.status == "completed"
                assert reminder.identity_key
                with pytest.raises(TaskError, match="transition"):
                    await service.transition(task.id, TaskStatus.OPEN, expected_version=4)
            async with ExecutionContextService().transaction(session, context):
                assert await session.scalar(select(func.count()).select_from(Task)) == 1
                assert (
                    await session.scalar(select(func.count()).select_from(TaskCompletionEvidence))
                    == 1
                )
                assert (
                    await session.scalar(
                        select(TaskReminder.status).where(TaskReminder.task_id == task_id)
                    )
                    == "cancelled"
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.target_type == "task")
                    )
                    == 4
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.aggregate_type == "task")
                    )
                    == 4
                )
            async with ExecutionContextService().transaction(session, other_context):
                with pytest.raises(TaskError, match="does not exist"):
                    await TaskService(session, other_context, authorizer=AllowAuthorizer()).get(
                        task_id
                    )
        downgrade = _migration(name, PREVIOUS, direction="downgrade")
        assert downgrade.returncode != 0
        assert "reviewed forward fix" in downgrade.stderr
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(admin, name)
        await admin.close()
