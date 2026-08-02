"""H3-02 durable-job adapter for H3-03 extraction eligibility."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.documents.contracts import CustodyError
from app.jobs.contracts import JobEnqueue


class JobResult(Protocol):
    id: uuid.UUID


class JobEnqueueService(Protocol):
    async def enqueue(self, command: JobEnqueue, *, now: datetime) -> JobResult: ...


class DurableExtractionJobAdapter:
    """Map one verified source version to an idempotent H3-02 command envelope."""

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

    async def enqueue_extraction(self, version_id: uuid.UUID, input_digest: str) -> uuid.UUID:
        if len(input_digest) != 64:
            raise CustodyError("extraction input digest is invalid")
        now = self._clock()
        command = JobEnqueue(
            job_id=self._id_factory(),
            definition_id=self._definition_id,
            idempotency_key=f"document-extraction:{version_id}:{input_digest}",
            command_type="documents.extract",
            payload={
                "source_version_id": str(version_id),
                "input_digest": input_digest,
            },
            classification="confidential",
            available_at=now,
            deadline=now + timedelta(minutes=15),
        )
        job = await self._jobs.enqueue(command, now=now)
        return job.id


class DurableDeletionJobAdapter:
    """Map one durable deletion request to an idempotent H3-02 command envelope."""

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

    async def enqueue_deletion(self, deletion_id: uuid.UUID, document_id: uuid.UUID) -> uuid.UUID:
        now = self._clock()
        command = JobEnqueue(
            job_id=self._id_factory(),
            definition_id=self._definition_id,
            idempotency_key=f"document-deletion:{deletion_id}",
            command_type="documents.delete",
            payload={
                "deletion_id": str(deletion_id),
                "document_id": str(document_id),
            },
            classification="confidential",
            available_at=now,
            deadline=now + timedelta(hours=24),
        )
        job = await self._jobs.enqueue(command, now=now)
        return job.id
