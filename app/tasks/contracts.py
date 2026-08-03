"""Typed contracts and deterministic invariants for canonical tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class TaskError(ValueError):
    pass


class TaskAuthorizationError(TaskError):
    pass


class TaskConcurrencyError(TaskError):
    pass


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DELETED = "deleted"


TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.OPEN: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.BLOCKED,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
            TaskStatus.DELETED,
        }
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {
            TaskStatus.OPEN,
            TaskStatus.BLOCKED,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
            TaskStatus.DELETED,
        }
    ),
    TaskStatus.BLOCKED: frozenset(
        {TaskStatus.OPEN, TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED, TaskStatus.DELETED}
    ),
    TaskStatus.COMPLETED: frozenset({TaskStatus.DELETED}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.DELETED}),
    TaskStatus.DELETED: frozenset(),
}


def transition_status(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in TRANSITIONS[current]:
        raise TaskError(f"task transition from {current.value} to {target.value} is invalid")
    return target


def require_task_version(*, current: int, expected: int) -> None:
    if current != expected:
        raise TaskConcurrencyError("task version precondition failed")


class TaskCreate(BaseModel):
    model_config = ConfigDict(frozen=True)
    task_id: uuid.UUID
    resource_id: uuid.UUID
    title: str
    description: str = ""
    priority: str = "normal"
    classification: str
    policy_version: int
    due_at: datetime | None = None
    timezone: str | None = None
    source_resource_id: uuid.UUID | None = None
    recurrence_reference: str | None = None
    completion_evidence_required: bool = False

    @field_validator("title", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_contract(self) -> TaskCreate:
        if not self.title or len(self.title) > 512 or len(self.description) > 20_000:
            raise TaskError("task text is invalid")
        if self.priority not in {"low", "normal", "high", "urgent"}:
            raise TaskError("task priority is invalid")
        if self.classification not in {"public", "internal", "confidential", "restricted"}:
            raise TaskError("task classification is invalid")
        if self.policy_version < 1:
            raise TaskError("task policy version is invalid")
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise TaskError("task due time must be timezone-aware")
        if (self.due_at is None) != (self.timezone is None):
            raise TaskError("task due time and timezone must be supplied together")
        return self


class TaskQuery(BaseModel):
    model_config = ConfigDict(frozen=True)
    statuses: tuple[TaskStatus, ...] = (
        TaskStatus.OPEN,
        TaskStatus.IN_PROGRESS,
        TaskStatus.BLOCKED,
    )
    assignee_user_id: uuid.UUID | None = None
    due_before: datetime | None = None
    limit: int = 100

    @model_validator(mode="after")
    def validate_query(self) -> TaskQuery:
        if not self.statuses or not 1 <= self.limit <= 500:
            raise TaskError("task query is invalid")
        if self.due_before is not None and self.due_before.tzinfo is None:
            raise TaskError("task query due boundary must be timezone-aware")
        return self
