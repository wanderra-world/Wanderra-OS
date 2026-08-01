"""Worker conformance tests for typed H3-02 handlers."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.jobs import FailureCategory
from app.workers.durable import DurableWorker, HandlerResult, TypedJobFailure

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class FakeService:
    def __init__(self, lease) -> None:
        self.lease = lease
        self.succeeded = []
        self.failed = []

    async def claim_next(self, **_kwargs):
        value, self.lease = self.lease, None
        return value

    async def succeed(self, job_id, **kwargs):
        self.succeeded.append((job_id, kwargs))

    async def fail(self, job_id, **kwargs):
        self.failed.append((job_id, kwargs))


def _lease(handler_key: str = "synthetic.ok"):
    return SimpleNamespace(job_id=uuid4(), handler_key=handler_key)


async def test_worker_records_success_only_through_job_service() -> None:
    lease = _lease()

    async def handler(_lease):
        return HandlerResult(result_digest="a" * 64)

    service = FakeService(lease)
    assert await DurableWorker({"synthetic.ok": handler}).run_once(
        service, worker_id="worker", now=NOW
    )
    assert service.succeeded[0][0] == lease.job_id
    assert service.failed == []


async def test_worker_preserves_typed_failure_and_quarantines_untyped_failure() -> None:
    typed_lease = _lease("synthetic.typed")

    async def typed(_lease):
        raise TypedJobFailure(FailureCategory.TRANSIENT, "temporary")

    typed_service = FakeService(typed_lease)
    await DurableWorker({"synthetic.typed": typed}).run_once(
        typed_service, worker_id="worker", now=NOW
    )
    assert typed_service.failed[0][1]["category"] is FailureCategory.TRANSIENT

    poison_lease = _lease("synthetic.poison")

    async def poison(_lease):
        raise RuntimeError("raw content must not be persisted")

    poison_service = FakeService(poison_lease)
    await DurableWorker({"synthetic.poison": poison}).run_once(
        poison_service, worker_id="worker", now=NOW
    )
    assert poison_service.failed[0][1]["category"] is FailureCategory.POISON
    assert poison_service.failed[0][1]["error_code"] == "untyped_handler_failure"


async def test_missing_handler_is_non_retriable() -> None:
    lease = _lease("missing")
    service = FakeService(lease)
    await DurableWorker({}).run_once(service, worker_id="worker", now=NOW)
    assert service.failed[0][1]["category"] is FailureCategory.PERMANENT
