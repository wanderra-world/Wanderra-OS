"""Failing-first domain tests for H3-02 durable execution."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.jobs.contracts import (
    DailySchedule,
    FailureCategory,
    IdempotencyConflict,
    JobDefinitionSpec,
    JobEnqueue,
    JobError,
    LocalTimePolicy,
    MisfirePolicy,
    RetryPolicy,
    ScheduleKind,
    ScheduleSpec,
    due_occurrences,
    next_occurrence,
    retry_decision,
)
from app.jobs.dispatcher import FairWorkspaceDispatcher


def test_retry_taxonomy_is_typed_and_bounded_by_deadline() -> None:
    policy = RetryPolicy(max_attempts=5, delays=(1, 5, 30, 120))
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    assert retry_decision(
        policy=policy,
        category=FailureCategory.TRANSIENT,
        attempt_number=1,
        now=now,
        deadline=now + timedelta(minutes=1),
    ).retry_at == now + timedelta(seconds=1)
    assert not retry_decision(
        policy=policy,
        category=FailureCategory.AUTHORIZATION,
        attempt_number=1,
        now=now,
        deadline=now + timedelta(minutes=1),
    ).retry
    assert not retry_decision(
        policy=policy,
        category=FailureCategory.TRANSIENT,
        attempt_number=5,
        now=now,
        deadline=now + timedelta(minutes=1),
    ).retry


def test_job_envelope_rejects_secret_terms_and_naive_time() -> None:
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    with pytest.raises(JobError, match="sensitive"):
        JobEnqueue(
            job_id=uuid4(),
            definition_id=uuid4(),
            idempotency_key="job-1",
            command_type="synthetic.run",
            payload={"access_token": "forbidden"},
            available_at=now,
            deadline=now + timedelta(minutes=1),
        )
    with pytest.raises(JobError, match="timezone-aware"):
        JobEnqueue(
            job_id=uuid4(),
            definition_id=uuid4(),
            idempotency_key="job-2",
            command_type="synthetic.run",
            payload={},
            available_at=now.replace(tzinfo=None),
            deadline=now + timedelta(minutes=1),
        )


def test_definition_enforces_approved_default_ceiling() -> None:
    with pytest.raises(JobError, match="attempt"):
        JobDefinitionSpec(
            definition_id=uuid4(),
            key="synthetic",
            version=1,
            handler_key="synthetic.run",
            retry_policy=RetryPolicy(max_attempts=6, delays=(1, 5, 30, 120, 120)),
        )


def test_interval_misfire_policies_are_explicit_and_bounded() -> None:
    start = datetime(2026, 7, 31, 10, tzinfo=UTC)
    now = start + timedelta(minutes=5)
    base = dict(
        schedule_id=uuid4(),
        definition_id=uuid4(),
        kind=ScheduleKind.INTERVAL,
        first_due_at=start,
        interval_seconds=60,
    )
    assert due_occurrences(ScheduleSpec(**base, misfire_policy=MisfirePolicy.SKIP), now) == ()
    assert due_occurrences(ScheduleSpec(**base, misfire_policy=MisfirePolicy.FIRE_ONCE), now) == (
        now,
    )
    catch_up = due_occurrences(ScheduleSpec(**base, misfire_policy=MisfirePolicy.CATCH_UP), now)
    assert len(catch_up) == 6
    assert len(catch_up) <= 10


def test_recurring_schedule_advances_to_next_actual_eligibility() -> None:
    start = datetime(2026, 7, 31, 10, tzinfo=UTC)
    interval = ScheduleSpec(
        schedule_id=uuid4(),
        definition_id=uuid4(),
        kind=ScheduleKind.INTERVAL,
        first_due_at=start,
        interval_seconds=60,
        misfire_policy=MisfirePolicy.FIRE_ONCE,
    )
    assert next_occurrence(interval, start + timedelta(minutes=5)) == start + timedelta(minutes=6)

    daily = ScheduleSpec(
        schedule_id=uuid4(),
        definition_id=uuid4(),
        kind=ScheduleKind.DAILY_LOCAL,
        first_due_at=datetime(2026, 3, 28, 1, 30, tzinfo=UTC),
        daily=DailySchedule(
            hour=2,
            minute=30,
            timezone="Europe/Stockholm",
            local_time_policy=LocalTimePolicy.SKIP,
        ),
        misfire_policy=MisfirePolicy.FIRE_ONCE,
    )
    assert next_occurrence(daily, datetime(2026, 3, 29, 3, tzinfo=UTC)) == datetime(
        2026, 3, 30, 0, 30, tzinfo=UTC
    )


def test_daily_schedule_handles_stockholm_dst_gap_and_overlap() -> None:
    gap = DailySchedule(
        hour=2,
        minute=30,
        timezone="Europe/Stockholm",
        local_time_policy=LocalTimePolicy.SKIP,
    )
    spec = ScheduleSpec(
        schedule_id=uuid4(),
        definition_id=uuid4(),
        kind=ScheduleKind.DAILY_LOCAL,
        first_due_at=datetime(2026, 3, 28, 1, 30, tzinfo=UTC),
        daily=gap,
        misfire_policy=MisfirePolicy.CATCH_UP,
    )
    due = due_occurrences(spec, datetime(2026, 3, 29, 3, tzinfo=UTC))
    assert datetime(2026, 3, 29, 1, 30, tzinfo=UTC) not in due

    earliest = DailySchedule(
        hour=2,
        minute=30,
        timezone="Europe/Stockholm",
        local_time_policy=LocalTimePolicy.EARLIEST,
    )
    overlap = ScheduleSpec(
        schedule_id=uuid4(),
        definition_id=uuid4(),
        kind=ScheduleKind.DAILY_LOCAL,
        first_due_at=datetime(2026, 10, 24, 0, 30, tzinfo=UTC),
        daily=earliest,
        misfire_policy=MisfirePolicy.CATCH_UP,
    )
    assert datetime(2026, 10, 25, 0, 30, tzinfo=UTC) in due_occurrences(
        overlap, datetime(2026, 10, 25, 2, tzinfo=UTC)
    )


def test_workspace_dispatch_is_deterministic_and_fair() -> None:
    workspaces = [uuid4(), uuid4(), uuid4()]
    dispatcher = FairWorkspaceDispatcher()
    claims = dispatcher.order({workspace: 4 for workspace in workspaces}, limit=9)
    assert claims == tuple(workspaces * 3)
    counts = {workspace: claims.count(workspace) for workspace in workspaces}
    assert max(counts.values()) - min(counts.values()) <= 1
    assert (
        dispatcher.order(
            {workspaces[0]: 1},
            limit=1,
            organization_running=100,
        )
        == ()
    )


def test_idempotency_conflict_is_a_distinct_failure() -> None:
    assert issubclass(IdempotencyConflict, JobError)
