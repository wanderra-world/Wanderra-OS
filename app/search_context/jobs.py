"""H3-02 durable-job adapter for H3-06 reindex and cleanup work."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.jobs.contracts import JobEnqueue
from app.search_context.contracts import SearchError


class JobResult(Protocol):
    id: uuid.UUID


class JobEnqueueService(Protocol):
    async def enqueue(self, command: JobEnqueue, *, now: datetime) -> JobResult: ...


class DurableSearchJobAdapter:
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

    async def enqueue_reindex(
        self, generation_id: uuid.UUID, source_manifest_digest: str
    ) -> uuid.UUID:
        if len(source_manifest_digest) != 64:
            raise SearchError("reindex source manifest digest is invalid")
        now = self._clock()
        command = JobEnqueue(
            job_id=self._id_factory(),
            definition_id=self._definition_id,
            idempotency_key=f"search-reindex:{generation_id}:{source_manifest_digest}",
            command_type="search.reindex",
            payload={
                "generation_id": str(generation_id),
                "source_manifest_digest": source_manifest_digest,
            },
            classification="confidential",
            available_at=now,
            deadline=now + timedelta(hours=24),
        )
        return (await self._jobs.enqueue(command, now=now)).id

    async def enqueue_cleanup(self, source_kind: str, source_id: uuid.UUID) -> uuid.UUID:
        now = self._clock()
        command = JobEnqueue(
            job_id=self._id_factory(),
            definition_id=self._definition_id,
            idempotency_key=f"search-cleanup:{source_kind}:{source_id}",
            command_type="search.cleanup",
            payload={"source_kind": source_kind, "source_id": str(source_id)},
            classification="confidential",
            available_at=now,
            deadline=now + timedelta(minutes=5),
        )
        return (await self._jobs.enqueue(command, now=now)).id
