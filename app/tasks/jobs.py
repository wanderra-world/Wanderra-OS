"""H3-02 durable-job adapter for idempotent task reminders."""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.jobs.contracts import JobEnqueue
from app.jobs.service import JobService
from app.tasks.models import Task


class DurableTaskReminderScheduler:
    """Translate canonical task eligibility into an H3-02 command envelope."""

    def __init__(self, jobs: JobService, definition_id: uuid.UUID) -> None:
        self._jobs = jobs
        self._definition_id = definition_id

    async def enqueue(self, task: Task, identity_key: str) -> uuid.UUID:
        if task.due_at is None:
            raise ValueError("task reminder requires a due time")
        job_id = uuid.uuid5(uuid.NAMESPACE_URL, f"atlas:task-reminder:{identity_key}")
        job = await self._jobs.enqueue(
            JobEnqueue(
                job_id=job_id,
                definition_id=self._definition_id,
                idempotency_key=f"task-reminder:{identity_key}",
                command_type="task.reminder_due.v1",
                payload={
                    "task_id": str(task.id),
                    "task_version": task.version,
                    "timezone": task.timezone or "UTC",
                },
                resource_id=task.resource_id,
                classification=task.classification,
                available_at=task.due_at,
                deadline=task.due_at + timedelta(minutes=5),
            )
        )
        return job.id
