"""H3-02 durable-job adapter for H3-04 source disposition."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.jobs.contracts import JobEnqueue


class JobResult(Protocol):
    id: uuid.UUID


class JobEnqueueService(Protocol):
    async def enqueue(self, command: JobEnqueue, *, now: datetime) -> JobResult: ...


class DurableSourceDispositionJobAdapter:
    def __init__(
        self,
        jobs: JobEnqueueService,
        *,
        definition_id: uuid.UUID,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._jobs = jobs
        self._definition_id = definition_id
        self._id_factory = id_factory
        self._clock = clock

    async def enqueue_source_disposition(self, source_version_id: uuid.UUID) -> uuid.UUID:
        now = self._clock()
        command = JobEnqueue(
            job_id=self._id_factory(),
            definition_id=self._definition_id,
            idempotency_key=f"knowledge-source-disposition:{source_version_id}",
            command_type="knowledge.source_disposition",
            payload={"source_version_id": str(source_version_id)},
            classification="confidential",
            available_at=now,
            deadline=now + timedelta(hours=24),
        )
        return (await self._jobs.enqueue(command, now=now)).id
