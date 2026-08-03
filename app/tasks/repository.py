"""Execution-context-bound persistence for H3-07 tasks."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution_context import ContextBoundRepository, ExecutionContext
from app.memberships.models import WorkspaceMembership
from app.resource_graph.models import Resource
from app.tasks.contracts import TaskQuery
from app.tasks.models import (
    Task,
    TaskCompletionEvidence,
    TaskDependency,
    TaskParticipant,
    TaskReminder,
)


class TaskRepository(ContextBoundRepository):
    def __init__(self, session: AsyncSession, context: ExecutionContext) -> None:
        super().__init__(session, context)

    async def add(self, value: object) -> object:
        self.require_workspace(getattr(value, "workspace_id"))
        self.session.add(value)
        await self.session.flush()
        return value

    async def task(self, task_id: uuid.UUID, *, for_update: bool = False) -> Task | None:
        statement = select(Task).where(
            Task.workspace_id == self.context.tenant.workspace_id, Task.id == task_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def task_resource(self, resource_id: uuid.UUID) -> Resource | None:
        return await self.session.scalar(
            select(Resource).where(
                Resource.workspace_id == self.context.tenant.workspace_id,
                Resource.id == resource_id,
                Resource.resource_type == "task",
                Resource.status == "active",
            )
        )

    async def list_tasks(self, query: TaskQuery) -> tuple[Task, ...]:
        statement = select(Task).where(
            Task.workspace_id == self.context.tenant.workspace_id,
            Task.status.in_(status.value for status in query.statuses),
        )
        if query.due_before is not None:
            statement = statement.where(Task.due_at <= query.due_before)
        if query.assignee_user_id is not None:
            statement = statement.join(
                TaskParticipant,
                (TaskParticipant.workspace_id == Task.workspace_id)
                & (TaskParticipant.task_id == Task.id),
            ).where(
                TaskParticipant.kind == "assignee",
                TaskParticipant.user_id == query.assignee_user_id,
            )
        rows = await self.session.scalars(
            statement.order_by(Task.due_at.asc().nulls_last(), Task.created_at, Task.id).limit(
                query.limit
            )
        )
        return tuple(rows)

    async def active_member(self, user_id: uuid.UUID) -> bool:
        value = await self.session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == self.context.tenant.workspace_id,
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.status == "active",
            )
        )
        return value is not None

    async def dependencies(self) -> tuple[tuple[uuid.UUID, uuid.UUID], ...]:
        rows = await self.session.execute(
            select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
                TaskDependency.workspace_id == self.context.tenant.workspace_id
            )
        )
        return tuple(rows.tuples())

    async def evidence_count(self, task_id: uuid.UUID) -> int:
        rows = await self.session.scalars(
            select(TaskCompletionEvidence.id).where(
                TaskCompletionEvidence.workspace_id == self.context.tenant.workspace_id,
                TaskCompletionEvidence.task_id == task_id,
            )
        )
        return len(tuple(rows))

    async def cancel_reminders(self, task_id: uuid.UUID) -> None:
        await self.session.execute(
            update(TaskReminder)
            .where(
                TaskReminder.workspace_id == self.context.tenant.workspace_id,
                TaskReminder.task_id == task_id,
                TaskReminder.status == "scheduled",
            )
            .values(status="cancelled")
        )
