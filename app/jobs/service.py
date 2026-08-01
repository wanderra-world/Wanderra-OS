"""Authorized transactional H3-02 durable execution service."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import AuthorizationRequest, AuthorizationService, DecisionEffect
from app.execution_context import ExecutionContext
from app.jobs.contracts import (
    DailySchedule,
    FailureCategory,
    IdempotencyConflict,
    JobAuthorizationError,
    JobDefinitionSpec,
    JobEnqueue,
    JobError,
    JobStatus,
    LeaseConflict,
    LocalTimePolicy,
    MisfirePolicy,
    RetryPolicy,
    ScheduleKind,
    ScheduleSpec,
    due_occurrences,
    next_occurrence,
    retry_decision,
    safe_payload,
)
from app.jobs.models import (
    JobAttempt,
    JobDeadLetter,
    JobDefinition,
    JobInstance,
    JobOperatorControl,
    JobSchedule,
)
from app.jobs.repository import JobRepository
from app.messaging.contracts import AuditInput
from app.messaging.service import AuditWriterService
from app.tenancy.models import OutboxEvent


class JobAuthorizer(Protocol):
    async def authorize(self, context: ExecutionContext, permission_key: str) -> bool: ...


class H1JobAuthorizer:
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


class JobLease:
    def __init__(self, job: JobInstance, definition: JobDefinition) -> None:
        self.job_id = job.id
        self.definition_id = definition.id
        self.handler_key = definition.handler_key
        self.command_type = job.command_type
        self.payload = job.payload
        self.idempotency_key = job.idempotency_key
        self.attempt_number = job.attempt_count
        self.deadline = job.deadline
        self.correlation_id = job.correlation_id


def _digest(command: JobEnqueue) -> str:
    payload = {
        "definition_id": str(command.definition_id),
        "command_type": command.command_type,
        "payload": command.payload,
        "resource_id": str(command.resource_id) if command.resource_id else None,
        "classification": command.classification,
        "available_at": command.available_at.astimezone(UTC).isoformat(),
        "deadline": command.deadline.astimezone(UTC).isoformat(),
        "causation_id": str(command.causation_id) if command.causation_id else None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class JobService:
    """Manage jobs inside the caller-owned execution-context transaction."""

    def __init__(
        self,
        session: AsyncSession,
        context: ExecutionContext,
        *,
        authorizer: JobAuthorizer | None = None,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._session = session
        self._context = context
        self._repository = JobRepository(session, context)
        self._authorizer = authorizer or H1JobAuthorizer(session)
        self._audit = AuditWriterService(session, context)
        self._id_factory = id_factory

    def _tenant(self) -> dict[str, uuid.UUID]:
        return {
            "organization_id": self._context.tenant.organization_id,
            "workspace_id": self._context.tenant.workspace_id,
            "cell_id": self._context.tenant.cell_id,
        }

    async def register_definition(
        self, spec: JobDefinitionSpec, *, now: datetime | None = None
    ) -> JobDefinition:
        await self._require_authorized("manage_workspace")
        if await self._repository.definition(spec.definition_id) is not None:
            raise JobError("job definition identity already exists")
        occurred_at = now or datetime.now(UTC)
        value = JobDefinition(
            **self._tenant(),
            id=spec.definition_id,
            definition_key=spec.key,
            definition_version=spec.version,
            handler_key=spec.handler_key,
            max_attempts=spec.retry_policy.max_attempts,
            retry_delays=list(spec.retry_policy.delays),
            max_concurrency=spec.max_concurrency,
            rate_limit_per_minute=spec.rate_limit_per_minute,
            status="active",
            state_version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        await self._repository.add(value)
        await self._record(value, "job_definition.registered", "job_definition", occurred_at)
        return value

    async def enqueue(self, command: JobEnqueue, *, now: datetime | None = None) -> JobInstance:
        await self._require_authorized("update_content")
        definition = await self._repository.definition(command.definition_id)
        if definition is None or definition.status == "retired":
            raise JobError("job definition is unavailable")
        digest = _digest(command)
        await self._repository.lock_enqueue_boundary(command.definition_id, command.idempotency_key)
        existing = await self._repository.job_by_idempotency(
            command.definition_id, command.idempotency_key, for_update=True
        )
        if existing is not None:
            if existing.request_digest != digest:
                raise IdempotencyConflict("idempotency key was reused with changed input")
            return existing
        occurred_at = now or datetime.now(UTC)
        if await self._repository.backlog_count() >= 10_000:
            raise JobError("workspace job backlog quota exceeded")
        if await self._repository.recent_enqueue_count(occurred_at) >= 120:
            raise JobError("workspace enqueue rate quota exceeded")
        value = JobInstance(
            **self._tenant(),
            id=command.job_id,
            definition_id=command.definition_id,
            resource_id=command.resource_id,
            idempotency_key=command.idempotency_key,
            request_digest=digest,
            command_type=command.command_type,
            payload=safe_payload(command.payload),
            classification=command.classification,
            status="queued",
            available_at=command.available_at,
            deadline=command.deadline,
            attempt_count=0,
            replay_of_job_id=None,
            causation_id=command.causation_id,
            correlation_id=self._context.request.correlation_id,
            state_version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        await self._repository.add(value)
        await self._record(value, "job.enqueued", "job", occurred_at)
        return value

    async def claim_next(
        self, *, worker_id: str, now: datetime, lease_seconds: int = 30
    ) -> JobLease | None:
        await self._require_authorized("update_content")
        worker_id = worker_id.strip()
        if not worker_id or len(worker_id) > 128:
            raise JobError("worker identity is invalid")
        if lease_seconds != 30:
            raise JobError("lease duration must match the approved default")
        await self._recover_expired(now)
        await self._expire_waiting(now)
        candidate = await self._repository.claim_candidate(now)
        if candidate is None:
            return None
        job, definition = candidate
        job.attempt_count += 1
        job.status = "running"
        job.lease_owner = worker_id
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.updated_at = now
        job.state_version += 1
        attempt = JobAttempt(
            **self._tenant(),
            id=self._id_factory(),
            job_id=job.id,
            attempt_number=job.attempt_count,
            worker_id=worker_id,
            status="running",
            started_at=now,
            heartbeat_at=now,
            lease_expires_at=job.lease_expires_at,
        )
        await self._repository.add(attempt)
        await self._record(job, "job.claimed", "job", now)
        return JobLease(job, definition)

    async def heartbeat(self, job_id: uuid.UUID, *, worker_id: str, now: datetime) -> None:
        job = await self._leased_job(job_id, worker_id=worker_id, now=now)
        attempt = await self._require_attempt(job)
        if job.cancellation_requested_at is not None:
            attempt.status = "cancelled"
            attempt.finished_at = now
            self._clear_lease(job)
            job.status = "cancelled"
            job.completed_at = now
            job.state_version += 1
            await self._record(job, "job.cancelled", "job", now)
            raise JobError("job cancellation observed")
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=30)
        job.updated_at = now
        job.state_version += 1
        attempt.heartbeat_at = now
        attempt.lease_expires_at = job.lease_expires_at
        await self._record(job, "job.heartbeat", "job", now)

    async def succeed(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        result_digest: str,
        now: datetime,
    ) -> JobInstance:
        if len(result_digest) != 64:
            raise JobError("result digest is invalid")
        job = await self._leased_job(job_id, worker_id=worker_id, now=now)
        if job.cancellation_requested_at is not None:
            raise JobError("cancelled job cannot succeed")
        attempt = await self._require_attempt(job)
        attempt.status = "succeeded"
        attempt.finished_at = now
        job.status = "succeeded"
        job.result_digest = result_digest
        job.completed_at = now
        job.updated_at = now
        job.state_version += 1
        self._clear_lease(job)
        await self._record(job, "job.succeeded", "job", now)
        return job

    async def fail(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        category: FailureCategory,
        error_code: str,
        now: datetime,
    ) -> JobInstance:
        job = await self._leased_job(job_id, worker_id=worker_id, now=now)
        attempt = await self._require_attempt(job)
        category = FailureCategory(category)
        code = error_code.strip()
        if not code or len(code) > 96:
            raise JobError("safe error code is invalid")
        attempt.status = "failed"
        attempt.failure_category = category.value
        attempt.error_code = code
        attempt.finished_at = now
        definition = await self._require_definition(job.definition_id)
        decision = retry_decision(
            policy=RetryPolicy(
                max_attempts=definition.max_attempts,
                delays=tuple(definition.retry_delays),
            ),
            category=category,
            attempt_number=job.attempt_count,
            now=now,
            deadline=job.deadline,
        )
        self._clear_lease(job)
        job.updated_at = now
        job.state_version += 1
        if decision.retry:
            assert decision.retry_at is not None
            job.status = "retry_wait"
            job.available_at = decision.retry_at
            await self._record(job, "job.retry_scheduled", "job", now)
        elif decision.terminal_status is JobStatus.EXPIRED:
            job.status = "expired"
            job.completed_at = now
            await self._record(job, "job.expired", "job", now)
        else:
            await self._dead_letter(job, category=category, error_code=code, now=now)
        return job

    async def cancel(
        self, job_id: uuid.UUID, *, reason: str, now: datetime | None = None
    ) -> JobInstance:
        await self._require_authorized("update_content")
        job = await self._require_job(job_id, for_update=True)
        occurred_at = now or datetime.now(UTC)
        reason = reason.strip()
        if not reason or len(reason) > 256:
            raise JobError("cancellation reason is invalid")
        if job.status in {"succeeded", "cancelled", "dead_lettered", "expired"}:
            raise JobError("terminal job cannot be cancelled")
        job.cancellation_requested_at = occurred_at
        job.cancellation_reason = reason
        job.updated_at = occurred_at
        job.state_version += 1
        if job.status != "running":
            job.status = "cancelled"
            job.completed_at = occurred_at
            self._clear_lease(job)
        await self._record(job, "job.cancellation_requested", "job", occurred_at)
        return job

    async def replay(
        self,
        job_id: uuid.UUID,
        *,
        new_job_id: uuid.UUID,
        idempotency_key: str,
        reason: str,
        now: datetime,
    ) -> JobInstance:
        await self._require_authorized("manage_workspace")
        original = await self._require_job(job_id, for_update=True)
        letter = await self._repository.dead_letter(job_id, for_update=True)
        if original.status != "dead_lettered" or letter is None or letter.status != "open":
            raise JobError("job is not available for replay")
        reason = reason.strip()
        if not reason or len(reason) > 256:
            raise JobError("replay reason is invalid")
        duration = max(original.deadline - original.created_at, timedelta(seconds=30))
        replay = await self.enqueue(
            JobEnqueue(
                job_id=new_job_id,
                definition_id=original.definition_id,
                idempotency_key=idempotency_key,
                command_type=original.command_type,
                payload=original.payload,
                available_at=now,
                deadline=now + duration,
                resource_id=original.resource_id,
                classification=original.classification,
                causation_id=original.id,
            ),
            now=now,
        )
        replay.replay_of_job_id = original.id
        letter.status = "replayed"
        letter.replayed_at = now
        letter.replayed_by_user_id = self._context.actor.actor_id
        letter.replay_job_id = replay.id
        letter.replay_reason = reason
        original.state_version += 1
        original.updated_at = now
        await self._record(original, "job.replayed", "job", now)
        return replay

    async def set_paused(
        self,
        *,
        scope_type: str,
        scope_reference: str,
        paused: bool,
        reason: str,
        expected_version: int,
        now: datetime | None = None,
    ) -> JobOperatorControl:
        await self._require_authorized("manage_workspace")
        if scope_type not in {"workspace", "definition"}:
            raise JobError("operator-control scope is invalid")
        if scope_type == "workspace" and scope_reference != str(self._context.tenant.workspace_id):
            raise JobError("workspace control does not match execution context")
        occurred_at = now or datetime.now(UTC)
        reason = reason.strip()
        if not reason or len(reason) > 256:
            raise JobError("operator-control reason is invalid")
        value = await self._repository.control(scope_type, scope_reference, for_update=True)
        if value is None:
            if expected_version != 0:
                raise JobError("operator-control version precondition failed")
            value = JobOperatorControl(
                **self._tenant(),
                id=self._id_factory(),
                scope_type=scope_type,
                scope_reference=scope_reference,
                paused=paused,
                reason=reason,
                state_version=1,
                changed_by_user_id=self._context.actor.actor_id,
                changed_at=occurred_at,
            )
            await self._repository.add(value)
        else:
            if value.state_version != expected_version:
                raise JobError("operator-control version precondition failed")
            value.paused = paused
            value.reason = reason
            value.state_version += 1
            value.changed_by_user_id = self._context.actor.actor_id
            value.changed_at = occurred_at
        await self._record(value, "job_control.changed", "job_control", occurred_at)
        return value

    async def set_schedule_paused(
        self,
        schedule_id: uuid.UUID,
        *,
        paused: bool,
        reason: str,
        expected_version: int,
        now: datetime | None = None,
    ) -> JobSchedule:
        await self._require_authorized("manage_workspace")
        schedule = await self._repository.schedule(schedule_id, for_update=True)
        if schedule is None:
            raise JobError("schedule does not exist")
        if schedule.state_version != expected_version:
            raise JobError("schedule version precondition failed")
        if schedule.status == "completed":
            raise JobError("completed schedule cannot be changed")
        reason = reason.strip()
        if not reason or len(reason) > 256:
            raise JobError("schedule pause reason is invalid")
        occurred_at = now or datetime.now(UTC)
        schedule.status = "paused" if paused else "active"
        schedule.state_version += 1
        schedule.updated_at = occurred_at
        await self._record(
            schedule,
            "job_schedule.paused" if paused else "job_schedule.resumed",
            "job_schedule",
            occurred_at,
        )
        return schedule

    async def register_schedule(
        self,
        spec: ScheduleSpec,
        *,
        command_type: str,
        payload: dict[str, object],
        idempotency_prefix: str,
        job_deadline_seconds: int,
        now: datetime | None = None,
    ) -> JobSchedule:
        await self._require_authorized("manage_workspace")
        await self._require_definition(spec.definition_id)
        if await self._repository.schedule(spec.schedule_id) is not None:
            raise JobError("schedule identity already exists")
        if not 1 <= job_deadline_seconds <= 86_400:
            raise JobError("scheduled job deadline is invalid")
        occurred_at = now or datetime.now(UTC)
        daily = spec.daily
        value = JobSchedule(
            **self._tenant(),
            id=spec.schedule_id,
            definition_id=spec.definition_id,
            schedule_kind=spec.kind.value,
            misfire_policy=spec.misfire_policy.value,
            first_due_at=spec.first_due_at,
            interval_seconds=spec.interval_seconds,
            timezone=daily.timezone if daily else None,
            local_hour=daily.hour if daily else None,
            local_minute=daily.minute if daily else None,
            local_time_policy=daily.local_time_policy.value if daily else None,
            command_type=command_type,
            command_payload=safe_payload(payload),
            idempotency_prefix=idempotency_prefix,
            job_deadline_seconds=job_deadline_seconds,
            status="active",
            next_due_at=spec.first_due_at,
            state_version=1,
            created_by_user_id=self._context.actor.actor_id,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        await self._repository.add(value)
        await self._record(value, "job_schedule.registered", "job_schedule", occurred_at)
        return value

    async def dispatch_due_schedules(self, *, now: datetime) -> tuple[JobInstance, ...]:
        await self._require_authorized("update_content")
        created: list[JobInstance] = []
        for schedule in await self._repository.due_schedules(now):
            spec = self._schedule_spec(schedule)
            occurrences = due_occurrences(spec, now)
            for occurrence in occurrences:
                created.append(
                    await self.enqueue(
                        JobEnqueue(
                            job_id=self._id_factory(),
                            definition_id=schedule.definition_id,
                            idempotency_key=f"{schedule.idempotency_prefix}:{occurrence.isoformat()}",
                            command_type=schedule.command_type,
                            payload=schedule.command_payload,
                            available_at=occurrence,
                            deadline=occurrence + timedelta(seconds=schedule.job_deadline_seconds),
                            causation_id=schedule.id,
                        ),
                        now=now,
                    )
                )
            schedule.last_evaluated_at = now
            schedule.updated_at = now
            schedule.state_version += 1
            following = next_occurrence(spec, now)
            if following is None:
                schedule.status = "completed"
            else:
                schedule.next_due_at = following
            await self._record(schedule, "job_schedule.evaluated", "job_schedule", now)
        return tuple(created)

    def _schedule_spec(self, value: JobSchedule) -> ScheduleSpec:
        daily = None
        if value.schedule_kind == "daily_local":
            assert value.local_hour is not None
            assert value.local_minute is not None
            assert value.timezone is not None
            assert value.local_time_policy is not None
            daily = DailySchedule(
                hour=value.local_hour,
                minute=value.local_minute,
                timezone=value.timezone,
                local_time_policy=LocalTimePolicy(value.local_time_policy),
            )
        return ScheduleSpec(
            schedule_id=value.id,
            definition_id=value.definition_id,
            kind=ScheduleKind(value.schedule_kind),
            first_due_at=value.first_due_at,
            misfire_policy=MisfirePolicy(value.misfire_policy),
            interval_seconds=value.interval_seconds,
            daily=daily,
        )

    async def _recover_expired(self, now: datetime) -> None:
        for job in await self._repository.expired_leases(now):
            attempt = await self._require_attempt(job)
            attempt.status = "abandoned"
            attempt.failure_category = FailureCategory.TRANSIENT.value
            attempt.error_code = "lease_expired"
            attempt.finished_at = now
            definition = await self._require_definition(job.definition_id)
            decision = retry_decision(
                policy=RetryPolicy(definition.max_attempts, tuple(definition.retry_delays)),
                category=FailureCategory.TRANSIENT,
                attempt_number=job.attempt_count,
                now=now,
                deadline=job.deadline,
            )
            self._clear_lease(job)
            job.updated_at = now
            job.state_version += 1
            if decision.retry:
                assert decision.retry_at is not None
                job.status = "retry_wait"
                job.available_at = decision.retry_at
                await self._record(job, "job.lease_recovered", "job", now)
            elif decision.terminal_status is JobStatus.EXPIRED:
                job.status = "expired"
                job.completed_at = now
                await self._record(job, "job.expired", "job", now)
            else:
                await self._dead_letter(
                    job,
                    category=FailureCategory.TRANSIENT,
                    error_code="lease_expired",
                    now=now,
                )

    async def _expire_waiting(self, now: datetime) -> None:
        for job in await self._repository.expired_waiting(now):
            job.status = "expired"
            job.completed_at = now
            job.updated_at = now
            job.state_version += 1
            await self._record(job, "job.expired", "job", now)

    async def _dead_letter(
        self,
        job: JobInstance,
        *,
        category: FailureCategory,
        error_code: str,
        now: datetime,
    ) -> None:
        job.status = "dead_lettered"
        job.completed_at = now
        await self._repository.add(
            JobDeadLetter(
                **self._tenant(),
                id=self._id_factory(),
                job_id=job.id,
                failure_category=category.value,
                error_code=error_code,
                status="open",
                created_at=now,
            )
        )
        await self._record(job, "job.dead_lettered", "job", now)

    async def _leased_job(self, job_id: uuid.UUID, *, worker_id: str, now: datetime) -> JobInstance:
        await self._require_authorized("update_content")
        job = await self._require_job(job_id, for_update=True)
        if (
            job.status != "running"
            or job.lease_owner != worker_id
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            raise LeaseConflict("worker does not own a live job lease")
        return job

    async def _require_job(self, job_id: uuid.UUID, *, for_update: bool = False) -> JobInstance:
        job = await self._repository.job(job_id, for_update=for_update)
        if job is None:
            raise JobError("job does not exist")
        return job

    async def _require_definition(self, definition_id: uuid.UUID) -> JobDefinition:
        definition = await self._repository.definition(definition_id)
        if definition is None:
            raise JobError("job definition does not exist")
        return definition

    async def _require_attempt(self, job: JobInstance) -> JobAttempt:
        attempt = await self._repository.current_attempt(job, for_update=True)
        if attempt is None or attempt.status != "running":
            raise LeaseConflict("running job attempt is unavailable")
        return attempt

    @staticmethod
    def _clear_lease(job: JobInstance) -> None:
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None

    async def _require_authorized(self, permission_key: str) -> None:
        if not await self._authorizer.authorize(self._context, permission_key):
            raise JobAuthorizationError("durable execution operation is denied")

    async def _record(
        self,
        aggregate: JobDefinition | JobInstance | JobSchedule | JobOperatorControl,
        event_type: str,
        aggregate_type: str,
        now: datetime,
    ) -> None:
        aggregate_id = aggregate.id
        sequence = aggregate.state_version
        await self._audit.write(
            AuditInput(
                action=event_type,
                target_type=aggregate_type,
                target_id=aggregate_id,
                outcome="success",
                details={"state_version": sequence},
            )
        )
        self._session.add(
            OutboxEvent(
                workspace_id=self._context.tenant.workspace_id,
                id=self._id_factory(),
                event_type=event_type,
                schema_version=1,
                schema_major=1,
                schema_minor=0,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_sequence=sequence,
                actor_id=self._context.actor.actor_id,
                delegation_id=self._context.actor.delegation_id,
                correlation_id=self._context.request.correlation_id,
                classification="internal",
                payload={
                    f"{aggregate_type}_id": str(aggregate_id),
                    "state_version": sequence,
                },
                recorded_at=now,
                partition_key=now.strftime("%Y-%m"),
            )
        )
        await self._session.flush()
