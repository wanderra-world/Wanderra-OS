from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.capability_routing.contracts import CapabilityRoute
from app.connection_cutover.contracts import (
    BackfillCandidate,
    CutoverThreshold,
    IntegrationCapability,
    ShadowMetrics,
)
from app.connection_cutover.service import (
    BackfillPlanner,
    CutoverNotReadyError,
    CutoverReadiness,
)


def candidate(
    capability: IntegrationCapability,
    *,
    source_id: str,
    checksum: str = "a" * 64,
    eligible: bool = True,
) -> BackfillCandidate:
    return BackfillCandidate(
        workspace_id=UUID("10000000-0000-0000-0000-000000000001"),
        organization_id=UUID("20000000-0000-0000-0000-000000000001"),
        cell_id=UUID("30000000-0000-0000-0000-000000000001"),
        user_id=UUID("40000000-0000-0000-0000-000000000001"),
        provider_account_id="atlas@example.com",
        capability=capability,
        source_record_id=source_id,
        source_checksum=checksum,
        credential_eligible=eligible,
    )


def test_backfill_plan_is_deterministic_idempotent_and_combines_google_suite() -> None:
    records = (
        candidate(IntegrationCapability.STORAGE, source_id="drive:1"),
        candidate(IntegrationCapability.EMAIL, source_id="gmail:1"),
        candidate(IntegrationCapability.CALENDAR, source_id="calendar:1"),
    )

    first = BackfillPlanner().plan(records)
    replay = BackfillPlanner().plan(tuple(reversed(records)))

    assert first == replay
    assert first.connection_id == UUID("561904c3-29d0-5a85-a6fc-a1124cee64eb")
    assert first.capabilities == (
        IntegrationCapability.CALENDAR,
        IntegrationCapability.EMAIL,
        IntegrationCapability.STORAGE,
    )
    assert first.exception_code is None
    assert len(first.evidence_checksum) == 64


def test_backfill_requires_one_account_and_records_reauthorization_exception() -> None:
    records = (
        candidate(IntegrationCapability.EMAIL, source_id="gmail:1"),
        candidate(
            IntegrationCapability.CALENDAR,
            source_id="calendar:1",
            eligible=False,
        ),
    )
    plan = BackfillPlanner().plan(records)
    assert plan.exception_code == "reauthorization_required"

    with pytest.raises(ValueError, match="one workspace and provider account"):
        BackfillPlanner().plan(
            records
            + (
                BackfillCandidate(
                    **{
                        **records[0].__dict__,
                        "workspace_id": uuid4(),
                        "source_record_id": "gmail:other",
                    }
                ),
            )
        )


def test_cutover_requires_threshold_and_rollback_is_always_available() -> None:
    threshold = CutoverThreshold(minimum_samples=10, maximum_mismatch_rate=0)
    readiness = CutoverReadiness(threshold)

    assert readiness.evaluate(ShadowMetrics(samples=10, matches=10)).ready
    assert not readiness.evaluate(ShadowMetrics(samples=9, matches=9)).ready
    assert not readiness.evaluate(ShadowMetrics(samples=10, matches=9)).ready
    with pytest.raises(CutoverNotReadyError):
        readiness.require_transition(
            current=CapabilityRoute.SHADOW,
            requested=CapabilityRoute.CANONICAL,
            metrics=ShadowMetrics(samples=10, matches=9),
        )
    assert (
        readiness.require_transition(
            current=CapabilityRoute.CANONICAL,
            requested=CapabilityRoute.LEGACY,
            metrics=ShadowMetrics(samples=0, matches=0),
        )
        is CapabilityRoute.LEGACY
    )


def test_metrics_reject_invalid_counts_and_thresholds() -> None:
    with pytest.raises(ValueError):
        ShadowMetrics(samples=2, matches=3)
    with pytest.raises(ValueError):
        CutoverThreshold(minimum_samples=0, maximum_mismatch_rate=0)


def test_backfill_evidence_timestamp_is_not_part_of_deterministic_checksum() -> None:
    record = candidate(IntegrationCapability.EMAIL, source_id="gmail:1")
    first = BackfillPlanner(now=lambda: datetime(2026, 1, 1, tzinfo=UTC)).plan((record,))
    second = BackfillPlanner(now=lambda: datetime(2026, 2, 1, tzinfo=UTC)).plan((record,))
    assert first.evidence_checksum == second.evidence_checksum
