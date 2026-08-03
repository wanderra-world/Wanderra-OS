"""Authorized transactional application service for H3-07 tasks."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import AuthorizationRequest, AuthorizationService, DecisionEffect
from app.execution_context import ExecutionContext
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tasks.contracts import (
    TaskAuthorizationError,
    TaskCreate,
    TaskError,
    TaskQuery,
    TaskStatus,
    require_task_version,
    transition_status,
)
from app.tasks.models import (
    Task,
    TaskComment,
    TaskCompletionEvidence,
    TaskDependency,
    TaskExternalReference,
    TaskParticipant,
    TaskReminder,
)
from app.tasks.repository import TaskRepository
from app.tenancy.models import OutboxEvent


class TaskAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class ReminderScheduler(Protocol):
    async def enqueue(self, task: Task, identity_key: str) -> uuid.UUID: ...


class H1TaskAuthorizer:
    def __init__(self, session: AsyncSession) -> None:
        self._service = AuthorizationService(session)

    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool:
        decision = await self._service.authorize(
            AuthorizationRequest(
                actor_id=context.actor.actor_id,
                session_id=context.actor.session_id,
                organization_id=context.tenant.organization_id,
                requested_workspace_id=context.tenant.workspace_id,
                membership_workspace_id=context.tenant.workspace_id,
                membership_id=context.actor.membership_id,
                permission_key=permission_key,
                request_reference=context.request.request_id,
            )
        )
        return decision.effect is DecisionEffect.ALLOW


class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: TaskAuthorizer | None = None,
        reminder_scheduler: ReminderScheduler | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._repository = TaskRepository(session, context)
        self._authorizer = authorizer or H1TaskAuthorizer(session)
        self._audit = AuditWriterService(session, context)
        self._reminder_scheduler = reminder_scheduler

    def _tenant(self) -> dict[str, uuid.UUID]:
        return {
            "organization_id": self._context.tenant.organization_id,
            "workspace_id": self._context.tenant.workspace_id,
            "cell_id": self._context.tenant.cell_id,
        }

    async def create(self, command: TaskCreate, *, now: datetime | None = None) -> Task:
        await self._require("update_content")
        if await self._repository.task(command.task_id) is not None:
            raise TaskError("task identity already exists")
        if await self._repository.task_resource(command.resource_id) is None:
            raise TaskError("task requires an active canonical task resource")
        occurred = now or datetime.now(UTC)
        value = Task(
            **self._tenant(),
            id=command.task_id,
            resource_id=command.resource_id,
            title=command.title,
            description=command.description,
            status=TaskStatus.OPEN.value,
            priority=command.priority,
            classification=command.classification,
            policy_version=command.policy_version,
            due_at=command.due_at,
            timezone=command.timezone,
            recurrence_reference=command.recurrence_reference,
            source_resource_id=command.source_resource_id,
            completion_evidence_required=command.completion_evidence_required,
            version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred,
            updated_at=occurred,
        )
        await self._repository.add(value)
        await self._record(value, "task.created", occurred)
        return value

    async def get(self, task_id: uuid.UUID) -> Task:
        await self._require("read_content")
        task = await self._task(task_id)
        if task.status == TaskStatus.DELETED.value:
            raise TaskError("task does not exist")
        return task

    async def list(self, query: TaskQuery) -> tuple[Task, ...]:
        await self._require("read_content")
        return await self._repository.list_tasks(query)

    async def transition(
        self,
        task_id: uuid.UUID,
        target: TaskStatus,
        *,
        expected_version: int,
        now: datetime | None = None,
    ) -> Task:
        permission = "delete_content" if target is TaskStatus.DELETED else "update_content"
        await self._require(permission)
        task = await self._locked(task_id, expected_version)
        transition_status(TaskStatus(task.status), target)
        if (
            target is TaskStatus.COMPLETED
            and task.completion_evidence_required
            and await self._repository.evidence_count(task.id) == 0
        ):
            raise TaskError("completion evidence is required")
        occurred = now or datetime.now(UTC)
        task.status = target.value
        task.completed_at = occurred if target is TaskStatus.COMPLETED else task.completed_at
        task.deleted_at = occurred if target is TaskStatus.DELETED else task.deleted_at
        if target in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.DELETED}:
            await self._repository.cancel_reminders(task.id)
        await self._changed(task, f"task.{target.value}", occurred)
        return task

    async def add_participant(
        self, task_id: uuid.UUID, user_id: uuid.UUID, kind: str, *, expected_version: int
    ) -> TaskParticipant:
        await self._require("update_content")
        if kind not in {"assignee", "watcher"} or not await self._repository.active_member(user_id):
            raise TaskError("task participant is invalid")
        task = await self._locked(task_id, expected_version)
        value = TaskParticipant(
            **self._tenant(),
            task_id=task.id,
            user_id=user_id,
            kind=kind,
            added_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add(value)
        await self._changed(task, "task.participant_added", datetime.now(UTC))
        return value

    async def add_dependency(
        self, task_id: uuid.UUID, depends_on_task_id: uuid.UUID, *, expected_version: int
    ) -> TaskDependency:
        await self._require("update_content")
        task = await self._locked(task_id, expected_version)
        await self._task(depends_on_task_id)
        if task_id == depends_on_task_id or self._creates_cycle(
            task_id, depends_on_task_id, await self._repository.dependencies()
        ):
            raise TaskError("task dependency cycle is prohibited")
        value = TaskDependency(
            **self._tenant(),
            task_id=task.id,
            depends_on_task_id=depends_on_task_id,
            created_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add(value)
        await self._changed(task, "task.dependency_added", datetime.now(UTC))
        return value

    @staticmethod
    def _creates_cycle(
        task_id: uuid.UUID, dependency_id: uuid.UUID, edges: tuple[tuple[uuid.UUID, uuid.UUID], ...]
    ) -> bool:
        graph: dict[uuid.UUID, set[uuid.UUID]] = {}
        for source, target in edges:
            graph.setdefault(source, set()).add(target)
        pending, visited = [dependency_id], set()
        while pending:
            current = pending.pop()
            if current == task_id:
                return True
            if current not in visited and len(visited) < 10_000:
                visited.add(current)
                pending.extend(graph.get(current, ()))
        return False

    async def add_comment(
        self, task_id: uuid.UUID, comment_id: uuid.UUID, body: str, *, expected_version: int
    ) -> TaskComment:
        await self._require("update_content")
        task = await self._locked(task_id, expected_version)
        text = body.strip()
        if not text or len(text) > 20_000:
            raise TaskError("task comment is invalid")
        value = TaskComment(
            **self._tenant(),
            id=comment_id,
            task_id=task.id,
            body=text,
            classification=task.classification,
            policy_version=task.policy_version,
            created_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add(value)
        await self._changed(task, "task.comment_added", datetime.now(UTC))
        return value

    async def add_completion_evidence(
        self,
        task_id: uuid.UUID,
        evidence_id: uuid.UUID,
        statement: str,
        *,
        expected_version: int,
        evidence_resource_id: uuid.UUID | None = None,
        supersedes_evidence_id: uuid.UUID | None = None,
    ) -> TaskCompletionEvidence:
        await self._require("update_content")
        task = await self._locked(task_id, expected_version)
        text = statement.strip()
        if not text:
            raise TaskError("completion evidence statement is required")
        digest = hashlib.sha256(text.encode()).hexdigest()
        value = TaskCompletionEvidence(
            **self._tenant(),
            id=evidence_id,
            task_id=task.id,
            evidence_resource_id=evidence_resource_id,
            evidence_digest=digest,
            statement=text,
            supersedes_evidence_id=supersedes_evidence_id,
            recorded_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add(value)
        await self._changed(task, "task.completion_evidence_added", datetime.now(UTC))
        return value

    async def link_external(
        self,
        task_id: uuid.UUID,
        reference_id: uuid.UUID,
        authority: str,
        external_id: str,
        *,
        expected_version: int,
        external_version: str | None = None,
    ) -> TaskExternalReference:
        await self._require("update_content")
        task = await self._locked(task_id, expected_version)
        authority, external_id = authority.strip(), external_id.strip()
        if not authority or not external_id:
            raise TaskError("external task reference is invalid")
        value = TaskExternalReference(
            **self._tenant(),
            id=reference_id,
            task_id=task.id,
            authority=authority,
            external_id=external_id,
            external_version=external_version,
            linked_by_user_id=self._context.actor.actor_id,
        )
        await self._repository.add(value)
        await self._changed(task, "task.external_reference_linked", datetime.now(UTC))
        return value

    async def schedule_reminder(
        self, task_id: uuid.UUID, reminder_id: uuid.UUID, *, expected_version: int
    ) -> TaskReminder:
        await self._require("update_content")
        task = await self._locked(task_id, expected_version)
        if (
            task.due_at is None
            or task.timezone is None
            or task.status
            in {TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value, TaskStatus.DELETED.value}
        ):
            raise TaskError("task is not eligible for a reminder")
        identity = hashlib.sha256(
            f"{task.id}:{task.due_at.isoformat()}:{task.version}".encode()
        ).hexdigest()
        value = TaskReminder(
            **self._tenant(),
            id=reminder_id,
            task_id=task.id,
            identity_key=identity,
            due_at=task.due_at,
            timezone=task.timezone,
            status="scheduled",
        )
        if self._reminder_scheduler is not None:
            value.job_id = await self._reminder_scheduler.enqueue(task, identity)
        await self._repository.add(value)
        await self._changed(task, "task.reminder_scheduled", datetime.now(UTC))
        return value

    async def _task(self, task_id: uuid.UUID) -> Task:
        task = await self._repository.task(task_id)
        if task is None:
            raise TaskError("task does not exist")
        return task

    async def _locked(self, task_id: uuid.UUID, expected_version: int) -> Task:
        task = await self._repository.task(task_id, for_update=True)
        if task is None:
            raise TaskError("task does not exist")
        require_task_version(current=task.version, expected=expected_version)
        if task.status == TaskStatus.DELETED.value:
            raise TaskError("deleted task cannot be changed")
        return task

    async def _require(self, permission: str) -> None:
        if not await self._authorizer.authorize(self._context, permission):
            raise TaskAuthorizationError("task operation is denied")

    async def _changed(self, task: Task, event: str, occurred: datetime) -> None:
        task.version += 1
        task.updated_at = occurred
        await self._record(task, event, occurred)

    async def _record(self, task: Task, event: str, occurred: datetime) -> None:
        await self._audit.write(
            AuditInput(
                action=event,
                target_type="task",
                target_id=task.id,
                outcome="success",
                details={
                    "version": task.version,
                    "status": task.status,
                    "classification": task.classification,
                },
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=task.workspace_id,
                id=uuid.uuid4(),
                event_type=event,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type="task",
                aggregate_id=task.id,
                aggregate_sequence=task.version,
                actor_id=self._context.actor.actor_id,
                correlation_id=self._context.request.correlation_id,
                classification=task.classification,
                payload={
                    "task_id": str(task.id),
                    "resource_id": str(task.resource_id),
                    "version": task.version,
                    "status": task.status,
                    "policy_version": task.policy_version,
                },
                recorded_at=occurred,
                partition_key=occurred.strftime("%Y-%m"),
            )
        )
        await self._session.flush()
