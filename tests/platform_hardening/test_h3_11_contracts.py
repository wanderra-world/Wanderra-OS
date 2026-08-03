from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.platform_hardening.contracts import (
    EvaluationResult,
    OperatorAction,
    OperatorCommand,
    RecoveryDrillResult,
    SLODefinition,
    TelemetryRecord,
    evaluate_slo,
)

NOW = datetime(2026, 8, 3, tzinfo=UTC)


def test_telemetry_is_versioned_correlated_redacted_and_provider_neutral() -> None:
    value = TelemetryRecord(
        schema_version=1,
        signal_key="workflow.duration",
        correlation_id="corr-1",
        classification="internal",
        value=125,
        unit="milliseconds",
        labels={"outcome": "verified", "boundary": "workflow"},
        occurred_at=NOW,
    )
    assert value.labels == {"outcome": "verified", "boundary": "workflow"}
    with pytest.raises(ValueError, match="sensitive"):
        value.model_copy(update={"labels": {"access_token": "never"}}, deep=True).model_validate(
            {**value.model_dump(), "labels": {"access_token": "never"}}
        )


def test_slo_evaluation_is_deterministic_and_fails_closed() -> None:
    target = SLODefinition(
        key="workflow.success",
        version=1,
        comparator="gte",
        threshold=0.99,
        minimum_samples=100,
    )
    assert evaluate_slo(target, samples=100, observed=0.995).passed is True
    assert evaluate_slo(target, samples=99, observed=1.0).reason == "insufficient_samples"
    assert evaluate_slo(target, samples=100, observed=0.98).reason == "threshold_missed"


def test_operator_commands_are_typed_versioned_and_auditable() -> None:
    command = OperatorCommand(
        command_id=uuid4(),
        action=OperatorAction.PAUSE,
        scope_type="workspace",
        scope_reference=str(uuid4()),
        expected_version=3,
        reason="bounded recovery drill",
        idempotency_key="pause-drill-1",
        occurred_at=NOW,
    )
    assert command.expected_version == 3
    with pytest.raises(ValueError, match="scope"):
        OperatorCommand(**{**command.model_dump(), "scope_type": "provider"})


def test_evaluation_and_recovery_require_reproducible_verified_evidence() -> None:
    evaluation = EvaluationResult(
        run_id=uuid4(),
        dataset_key="synthetic.h3-exit.v1",
        dataset_version=1,
        commit_sha="a" * 40,
        result_digest="b" * 64,
        passed=True,
        critical_findings=0,
        high_findings=0,
        measured_at=NOW,
    )
    assert evaluation.release_eligible is True
    drill = RecoveryDrillResult(
        drill_id=uuid4(),
        drill_type="restore",
        artifact_digest="c" * 64,
        restored_digest="c" * 64,
        rpo_seconds=0,
        rto_seconds=30,
        passed=True,
        performed_at=NOW,
    )
    assert drill.verified is True
    assert drill.model_copy(update={"restored_digest": "d" * 64}).verified is False


def test_critical_or_high_findings_block_release() -> None:
    value = EvaluationResult(
        run_id=uuid4(),
        dataset_key="synthetic.security.v1",
        dataset_version=1,
        commit_sha="a" * 40,
        result_digest="b" * 64,
        passed=True,
        critical_findings=0,
        high_findings=1,
        measured_at=NOW,
    )
    assert value.release_eligible is False
