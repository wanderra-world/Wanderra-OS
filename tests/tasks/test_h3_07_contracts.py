from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.tasks.contracts import (
    TaskConcurrencyError,
    TaskCreate,
    TaskError,
    TaskQuery,
    TaskStatus,
    require_task_version,
    transition_status,
)
from app.tasks.service import TaskService


def test_task_contract_normalizes_and_validates_canonical_work() -> None:
    command = TaskCreate(
        task_id=uuid4(),
        resource_id=uuid4(),
        title="  Prepare evidence  ",
        description=" bounded work ",
        priority="high",
        classification="internal",
        policy_version=1,
        due_at=datetime(2026, 8, 3, 12, tzinfo=UTC),
        timezone="Europe/Stockholm",
        completion_evidence_required=True,
    )
    assert command.title == "Prepare evidence"
    assert command.description == "bounded work"
    with pytest.raises(ValueError):
        TaskCreate(
            task_id=uuid4(),
            resource_id=uuid4(),
            title=" ",
            priority="normal",
            classification="internal",
            policy_version=1,
        )


def test_task_lifecycle_is_explicit_and_terminal_states_fail_closed() -> None:
    assert transition_status(TaskStatus.OPEN, TaskStatus.IN_PROGRESS) is TaskStatus.IN_PROGRESS
    assert transition_status(TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED) is TaskStatus.COMPLETED
    with pytest.raises(TaskError, match="transition"):
        transition_status(TaskStatus.COMPLETED, TaskStatus.OPEN)
    with pytest.raises(TaskConcurrencyError):
        require_task_version(current=2, expected=1)


def test_dependency_cycle_detection_is_deterministic_and_bounded() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    edges = ((first, second), (second, third))
    assert TaskService._creates_cycle(third, first, edges)
    assert not TaskService._creates_cycle(first, third, edges)


def test_task_query_is_bounded_and_timezone_safe() -> None:
    assert TaskQuery(limit=500).limit == 500
    with pytest.raises(ValueError):
        TaskQuery(limit=501)
    with pytest.raises(ValueError):
        TaskQuery(due_before=datetime(2026, 8, 3))
