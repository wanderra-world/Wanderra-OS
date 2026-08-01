"""Execution-context-bound persistence for H3-02 durable execution."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import String, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.jobs.models import (
    JobAttempt,
    JobDeadLetter,
    JobDefinition,
    JobInstance,
    JobOperatorControl,
    JobSchedule,
)


class JobRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, value: object) -> object:
        self.require_workspace(getattr(value, "workspace_id"))
        self.session.add(value)
        await self.session.flush()
        return value

    async def definition(
        self, definition_id: uuid.UUID, *, for_update: bool = False
    ) -> JobDefinition | None:
        statement = select(JobDefinition).where(
            JobDefinition.workspace_id == self.context.tenant.workspace_id,
            JobDefinition.id == definition_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def job(self, job_id: uuid.UUID, *, for_update: bool = False) -> JobInstance | None:
        statement = select(JobInstance).where(
            JobInstance.workspace_id == self.context.tenant.workspace_id,
            JobInstance.id == job_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def job_by_idempotency(
        self, definition_id: uuid.UUID, idempotency_key: str, *, for_update: bool = False
    ) -> JobInstance | None:
        statement = select(JobInstance).where(
            JobInstance.workspace_id == self.context.tenant.workspace_id,
            JobInstance.definition_id == definition_id,
            JobInstance.idempotency_key == idempotency_key,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def lock_enqueue_boundary(self, definition_id: uuid.UUID, idempotency_key: str) -> None:
        """Serialize one tenant/key and its workspace quota decision."""
        key = f"{self.context.tenant.workspace_id}:{definition_id}:{idempotency_key}"
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"job-quota:{self.context.tenant.workspace_id}"},
        )

    async def backlog_count(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(JobInstance)
                .where(
                    JobInstance.workspace_id == self.context.tenant.workspace_id,
                    JobInstance.status.in_(("queued", "running", "retry_wait")),
                )
            )
            or 0
        )

    async def recent_enqueue_count(self, now: datetime) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(JobInstance)
                .where(
                    JobInstance.workspace_id == self.context.tenant.workspace_id,
                    JobInstance.created_at > now - timedelta(minutes=1),
                )
            )
            or 0
        )

    async def workspace_paused(self) -> bool:
        return (
            await self.session.scalar(
                select(JobOperatorControl.id).where(
                    JobOperatorControl.workspace_id == self.context.tenant.workspace_id,
                    JobOperatorControl.scope_type == "workspace",
                    JobOperatorControl.scope_reference == str(self.context.tenant.workspace_id),
                    JobOperatorControl.paused.is_(True),
                )
            )
            is not None
        )

    async def definition_paused(self, definition_id: uuid.UUID) -> bool:
        return (
            await self.session.scalar(
                select(JobOperatorControl.id).where(
                    JobOperatorControl.workspace_id == self.context.tenant.workspace_id,
                    JobOperatorControl.scope_type == "definition",
                    JobOperatorControl.scope_reference == str(definition_id),
                    JobOperatorControl.paused.is_(True),
                )
            )
            is not None
        )

    async def claim_candidate(self, now: datetime) -> tuple[JobInstance, JobDefinition] | None:
        if await self.workspace_paused():
            return None
        workspace_running = int(
            await self.session.scalar(
                select(func.count())
                .select_from(JobInstance)
                .where(
                    JobInstance.workspace_id == self.context.tenant.workspace_id,
                    JobInstance.status == "running",
                )
            )
            or 0
        )
        if workspace_running >= 20:
            return None
        definition_not_paused = (
            ~select(JobOperatorControl.id)
            .where(
                JobOperatorControl.workspace_id == JobDefinition.workspace_id,
                JobOperatorControl.scope_type == "definition",
                JobOperatorControl.scope_reference == cast(JobDefinition.id, String),
                JobOperatorControl.paused.is_(True),
            )
            .exists()
        )
        statement = (
            select(JobInstance, JobDefinition)
            .join(
                JobDefinition,
                (
                    (JobDefinition.organization_id == JobInstance.organization_id)
                    & (JobDefinition.workspace_id == JobInstance.workspace_id)
                    & (JobDefinition.cell_id == JobInstance.cell_id)
                    & (JobDefinition.id == JobInstance.definition_id)
                ),
            )
            .where(
                JobInstance.workspace_id == self.context.tenant.workspace_id,
                JobInstance.status.in_(("queued", "retry_wait")),
                JobInstance.available_at <= now,
                JobInstance.deadline > now,
                JobDefinition.status == "active",
                definition_not_paused,
            )
            .order_by(JobInstance.available_at, JobInstance.created_at, JobInstance.id)
            .limit(1)
            .with_for_update(of=JobInstance, skip_locked=True)
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        job, definition = row
        running = int(
            await self.session.scalar(
                select(func.count())
                .select_from(JobInstance)
                .where(
                    JobInstance.workspace_id == self.context.tenant.workspace_id,
                    JobInstance.definition_id == definition.id,
                    JobInstance.status == "running",
                )
            )
            or 0
        )
        if running >= definition.max_concurrency:
            return None
        recent = int(
            await self.session.scalar(
                select(func.count())
                .select_from(JobAttempt)
                .where(
                    JobAttempt.workspace_id == self.context.tenant.workspace_id,
                    JobAttempt.started_at > now - timedelta(minutes=1),
                    JobAttempt.job_id.in_(
                        select(JobInstance.id).where(
                            JobInstance.workspace_id == self.context.tenant.workspace_id,
                            JobInstance.definition_id == definition.id,
                        )
                    ),
                )
            )
            or 0
        )
        if recent >= definition.rate_limit_per_minute:
            return None
        return job, definition

    async def current_attempt(
        self, job: JobInstance, *, for_update: bool = False
    ) -> JobAttempt | None:
        statement = select(JobAttempt).where(
            JobAttempt.workspace_id == self.context.tenant.workspace_id,
            JobAttempt.job_id == job.id,
            JobAttempt.attempt_number == job.attempt_count,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def expired_leases(self, now: datetime) -> tuple[JobInstance, ...]:
        rows = await self.session.scalars(
            select(JobInstance)
            .where(
                JobInstance.workspace_id == self.context.tenant.workspace_id,
                JobInstance.status == "running",
                JobInstance.lease_expires_at <= now,
            )
            .order_by(JobInstance.lease_expires_at)
            .with_for_update(skip_locked=True)
        )
        return tuple(rows)

    async def expired_waiting(self, now: datetime) -> tuple[JobInstance, ...]:
        rows = await self.session.scalars(
            select(JobInstance)
            .where(
                JobInstance.workspace_id == self.context.tenant.workspace_id,
                JobInstance.status.in_(("queued", "retry_wait")),
                JobInstance.deadline <= now,
            )
            .with_for_update(skip_locked=True)
        )
        return tuple(rows)

    async def dead_letter(
        self, job_id: uuid.UUID, *, for_update: bool = False
    ) -> JobDeadLetter | None:
        statement = select(JobDeadLetter).where(
            JobDeadLetter.workspace_id == self.context.tenant.workspace_id,
            JobDeadLetter.job_id == job_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def schedule(
        self, schedule_id: uuid.UUID, *, for_update: bool = False
    ) -> JobSchedule | None:
        statement = select(JobSchedule).where(
            JobSchedule.workspace_id == self.context.tenant.workspace_id,
            JobSchedule.id == schedule_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def due_schedules(self, now: datetime) -> tuple[JobSchedule, ...]:
        rows = await self.session.scalars(
            select(JobSchedule)
            .where(
                JobSchedule.workspace_id == self.context.tenant.workspace_id,
                JobSchedule.status == "active",
                JobSchedule.next_due_at <= now,
            )
            .order_by(JobSchedule.next_due_at, JobSchedule.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        return tuple(rows)

    async def control(
        self, scope_type: str, scope_reference: str, *, for_update: bool = False
    ) -> JobOperatorControl | None:
        statement = select(JobOperatorControl).where(
            JobOperatorControl.workspace_id == self.context.tenant.workspace_id,
            JobOperatorControl.scope_type == scope_type,
            JobOperatorControl.scope_reference == scope_reference,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)
