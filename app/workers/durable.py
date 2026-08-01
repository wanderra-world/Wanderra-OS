"""Generic deployable worker boundary for H3-02 durable execution."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.jobs.contracts import FailureCategory, JobError
from app.jobs.service import JobLease, JobService


@dataclass(frozen=True, slots=True)
class HandlerResult:
    result_digest: str


class JobHandler(Protocol):
    async def __call__(self, lease: JobLease) -> HandlerResult: ...


class TypedJobFailure(Exception):
    def __init__(self, category: FailureCategory, error_code: str) -> None:
        super().__init__(error_code)
        self.category = category
        self.error_code = error_code


class DurableWorker:
    """Run one bounded claim through an explicitly registered handler."""

    def __init__(self, handlers: dict[str, JobHandler]) -> None:
        self._handlers = dict(handlers)

    async def run_once(
        self,
        service: JobService,
        *,
        worker_id: str,
        now: datetime,
    ) -> bool:
        lease = await service.claim_next(worker_id=worker_id, now=now)
        if lease is None:
            return False
        handler = self._handlers.get(lease.handler_key)
        if handler is None:
            await service.fail(
                lease.job_id,
                worker_id=worker_id,
                category=FailureCategory.PERMANENT,
                error_code="handler_not_registered",
                now=now,
            )
            return True
        try:
            result = await handler(lease)
        except TypedJobFailure as error:
            await service.fail(
                lease.job_id,
                worker_id=worker_id,
                category=error.category,
                error_code=error.error_code,
                now=now,
            )
        except JobError:
            raise
        except Exception:
            await service.fail(
                lease.job_id,
                worker_id=worker_id,
                category=FailureCategory.POISON,
                error_code="untyped_handler_failure",
                now=now,
            )
        else:
            await service.succeed(
                lease.job_id,
                worker_id=worker_id,
                result_digest=result.result_digest,
                now=now,
            )
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas durable worker")
    parser.add_argument("--smoke", action="store_true")
    arguments = parser.parse_args()
    if arguments.smoke:
        worker = DurableWorker({})
        assert worker is not None
        print("atlas durable worker smoke passed")
        return
    raise SystemExit("worker runtime requires an application-owned context provider")


if __name__ == "__main__":
    main()
