"""Typed public contracts for H3-02 durable execution."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

APPROVED_RETRY_DELAYS: Final = (1, 5, 30, 120)
FORBIDDEN_PAYLOAD_TERMS: Final = (
    "password",
    "secret",
    "token",
    "credential",
    "ciphertext",
    "private_key",
)


class JobError(ValueError):
    """Raised when a durable-execution invariant is violated."""


class JobAuthorizationError(PermissionError):
    """Raised before an unauthorized durable-execution operation."""


class IdempotencyConflict(JobError):
    """Raised when an enqueue key is reused with changed input."""


class LeaseConflict(JobError):
    """Raised when a worker does not own a live job lease."""


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    DEAD_LETTERED = "dead_lettered"
    EXPIRED = "expired"


class AttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"


class FailureCategory(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    PERMANENT = "permanent"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    CANCELLED = "cancelled"
    DEADLINE = "deadline"
    POISON = "poison"


class ScheduleKind(StrEnum):
    ONCE = "once"
    INTERVAL = "interval"
    DAILY_LOCAL = "daily_local"


class MisfirePolicy(StrEnum):
    SKIP = "skip"
    FIRE_ONCE = "fire_once"
    CATCH_UP = "catch_up"


class LocalTimePolicy(StrEnum):
    SKIP = "skip"
    NEXT_VALID = "next_valid"
    EARLIEST = "earliest"
    LATEST = "latest"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise JobError(f"{name} must be timezone-aware")
    return value


def _reference(value: str, name: str, limit: int = 128) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise JobError(f"{name} is invalid")
    return normalized


def safe_payload(payload: dict[str, object]) -> dict[str, object]:
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise JobError("job payload must be deterministic JSON") from error
    lowered = encoded.casefold()
    if any(term in lowered for term in FORBIDDEN_PAYLOAD_TERMS):
        raise JobError("sensitive job payload is prohibited")
    if len(encoded.encode()) > 262_144:
        raise JobError("job payload exceeds 256 KiB")
    return payload


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    delays: tuple[int, ...] = APPROVED_RETRY_DELAYS

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 5:
            raise JobError("attempt count exceeds the approved retry budget")
        if len(self.delays) < self.max_attempts - 1:
            raise JobError("retry delays do not cover the retry budget")
        if any(delay <= 0 or delay > 120 for delay in self.delays):
            raise JobError("retry delay exceeds the approved bound")


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    retry_at: datetime | None
    terminal_status: JobStatus | None


def retry_decision(
    *,
    policy: RetryPolicy,
    category: FailureCategory,
    attempt_number: int,
    now: datetime,
    deadline: datetime,
) -> RetryDecision:
    now = _aware(now, "now")
    deadline = _aware(deadline, "deadline")
    retryable = category in {
        FailureCategory.TRANSIENT,
        FailureCategory.RATE_LIMIT,
        FailureCategory.QUOTA,
    }
    if not retryable or attempt_number >= policy.max_attempts:
        return RetryDecision(False, None, JobStatus.DEAD_LETTERED)
    retry_at = now + timedelta(seconds=policy.delays[attempt_number - 1])
    if retry_at >= deadline:
        return RetryDecision(False, None, JobStatus.EXPIRED)
    return RetryDecision(True, retry_at, None)


@dataclass(frozen=True, slots=True)
class JobDefinitionSpec:
    definition_id: uuid.UUID
    key: str
    version: int
    handler_key: str
    retry_policy: RetryPolicy = RetryPolicy()
    max_concurrency: int = 20
    rate_limit_per_minute: int = 120

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _reference(self.key, "definition key", 96))
        object.__setattr__(self, "handler_key", _reference(self.handler_key, "handler key", 128))
        if self.version < 1:
            raise JobError("definition version must be positive")
        if not 1 <= self.max_concurrency <= 20:
            raise JobError("definition concurrency exceeds the workspace ceiling")
        if not 1 <= self.rate_limit_per_minute <= 120:
            raise JobError("definition rate exceeds the workspace ceiling")


@dataclass(frozen=True, slots=True)
class JobEnqueue:
    job_id: uuid.UUID
    definition_id: uuid.UUID
    idempotency_key: str
    command_type: str
    payload: dict[str, object]
    available_at: datetime
    deadline: datetime
    resource_id: uuid.UUID | None = None
    classification: str = "internal"
    causation_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "idempotency_key", _reference(self.idempotency_key, "idempotency key")
        )
        object.__setattr__(self, "command_type", _reference(self.command_type, "command type"))
        _aware(self.available_at, "available_at")
        _aware(self.deadline, "deadline")
        if self.deadline <= self.available_at:
            raise JobError("deadline must follow availability")
        if self.classification not in {"public", "internal", "confidential", "restricted"}:
            raise JobError("job classification is invalid")
        safe_payload(self.payload)


@dataclass(frozen=True, slots=True)
class DailySchedule:
    hour: int
    minute: int
    timezone: str
    local_time_policy: LocalTimePolicy

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23 or not 0 <= self.minute <= 59:
            raise JobError("daily local time is invalid")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise JobError("schedule timezone is unknown") from error


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    schedule_id: uuid.UUID
    definition_id: uuid.UUID
    kind: ScheduleKind
    first_due_at: datetime
    misfire_policy: MisfirePolicy
    interval_seconds: int | None = None
    daily: DailySchedule | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ScheduleKind(self.kind))
        object.__setattr__(self, "misfire_policy", MisfirePolicy(self.misfire_policy))
        _aware(self.first_due_at, "first_due_at")
        if self.kind is ScheduleKind.INTERVAL and (
            self.interval_seconds is None or self.interval_seconds < 1
        ):
            raise JobError("interval schedule requires a positive interval")
        if self.kind is ScheduleKind.DAILY_LOCAL and self.daily is None:
            raise JobError("daily schedule requires local-time policy")
        if self.kind is not ScheduleKind.DAILY_LOCAL and self.daily is not None:
            raise JobError("local-time policy belongs only to daily schedules")


def _resolve_local(day: date, daily: DailySchedule) -> datetime | None:
    zone = ZoneInfo(daily.timezone)
    naive = datetime.combine(day, time(daily.hour, daily.minute))
    candidates: list[datetime] = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        utc_value = aware.astimezone(UTC)
        if utc_value.astimezone(zone).replace(tzinfo=None) == naive and utc_value not in candidates:
            candidates.append(utc_value)
    if not candidates:
        if daily.local_time_policy is LocalTimePolicy.NEXT_VALID:
            for offset in range(1, 181):
                shifted = naive + timedelta(minutes=offset)
                aware = shifted.replace(tzinfo=zone)
                utc_value = aware.astimezone(UTC)
                if utc_value.astimezone(zone).replace(tzinfo=None) == shifted:
                    return utc_value
        return None
    if daily.local_time_policy is LocalTimePolicy.LATEST:
        return max(candidates)
    return min(candidates)


def _all_due(spec: ScheduleSpec, now: datetime) -> list[datetime]:
    now = _aware(now, "now").astimezone(UTC)
    first = spec.first_due_at.astimezone(UTC)
    if first > now:
        return []
    if spec.kind is ScheduleKind.ONCE:
        return [first]
    if spec.kind is ScheduleKind.INTERVAL:
        assert spec.interval_seconds is not None
        elapsed = int((now - first).total_seconds())
        count = elapsed // spec.interval_seconds + 1
        start = max(0, count - 10)
        return [
            first + timedelta(seconds=spec.interval_seconds * value)
            for value in range(start, count)
        ]
    assert spec.daily is not None
    zone = ZoneInfo(spec.daily.timezone)
    first_day = first.astimezone(zone).date()
    last_day = now.astimezone(zone).date()
    days = (last_day - first_day).days
    values: list[datetime] = []
    for offset in range(max(0, days - 10), days + 1):
        occurrence = _resolve_local(first_day + timedelta(days=offset), spec.daily)
        if occurrence is not None and first <= occurrence <= now:
            values.append(occurrence)
    return values[-10:]


def due_occurrences(spec: ScheduleSpec, now: datetime) -> tuple[datetime, ...]:
    """Return bounded deterministic due instants according to explicit misfire policy."""
    due = _all_due(spec, now)
    if not due or spec.misfire_policy is MisfirePolicy.SKIP:
        return ()
    if spec.misfire_policy is MisfirePolicy.FIRE_ONCE:
        return (_aware(now, "now").astimezone(UTC),)
    return tuple(due[-10:])


def next_occurrence(spec: ScheduleSpec, after: datetime) -> datetime | None:
    """Return the first eligibility instant strictly after an aware instant."""
    after = _aware(after, "after").astimezone(UTC)
    first = spec.first_due_at.astimezone(UTC)
    if spec.kind is ScheduleKind.ONCE:
        return first if first > after else None
    if spec.kind is ScheduleKind.INTERVAL:
        assert spec.interval_seconds is not None
        if after < first:
            return first
        elapsed = int((after - first).total_seconds())
        return first + timedelta(
            seconds=(elapsed // spec.interval_seconds + 1) * spec.interval_seconds
        )
    assert spec.daily is not None
    zone = ZoneInfo(spec.daily.timezone)
    day = after.astimezone(zone).date()
    for offset in range(0, 370):
        candidate = _resolve_local(day + timedelta(days=offset), spec.daily)
        if candidate is not None and candidate >= first and candidate > after:
            return candidate
    raise JobError("daily schedule has no resolvable occurrence within one year")
