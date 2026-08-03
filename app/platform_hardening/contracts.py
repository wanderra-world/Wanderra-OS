"""Typed, deterministic, content-minimized H3-11 hardening contracts."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
SENSITIVE_MARKERS = ("password", "secret", "token", "credential", "payload", "prompt")


class HardeningError(ValueError):
    pass


class OperatorAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    QUARANTINE = "quarantine"
    REPLAY = "replay"
    RECONCILE = "reconcile"
    DISABLE = "disable"
    INSPECT = "inspect"


class TelemetryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: int
    signal_key: str
    correlation_id: str
    classification: str
    value: float
    unit: str
    labels: dict[str, str]
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_record(self) -> TelemetryRecord:
        if self.schema_version < 1 or not KEY.fullmatch(self.signal_key):
            raise HardeningError("telemetry identity is invalid")
        if self.classification not in CLASSIFICATIONS:
            raise HardeningError("telemetry classification is invalid")
        if not self.correlation_id.strip() or self.occurred_at.tzinfo is None:
            raise HardeningError("telemetry correlation and clock are required")
        if len(self.labels) > 16:
            raise HardeningError("telemetry label cardinality is excessive")
        for key, value in self.labels.items():
            normalized_key = key.casefold()
            if any(marker in normalized_key for marker in SENSITIVE_MARKERS):
                raise HardeningError("sensitive telemetry labels are prohibited")
            if "provider" in normalized_key:
                raise HardeningError("provider-specific telemetry labels are prohibited")
            if not KEY.fullmatch(key) or len(value) > 128:
                raise HardeningError("telemetry label is invalid")
        return self


class SLODefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    key: str
    version: int
    comparator: Literal["gte", "lte"]
    threshold: float
    minimum_samples: int

    @model_validator(mode="after")
    def validate_definition(self) -> SLODefinition:
        if not KEY.fullmatch(self.key) or self.version < 1 or self.minimum_samples < 1:
            raise HardeningError("SLO definition is invalid")
        return self


class SLOResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    definition_key: str
    definition_version: int
    samples: int
    observed: float
    passed: bool
    reason: str


def evaluate_slo(definition: SLODefinition, *, samples: int, observed: float) -> SLOResult:
    if samples < definition.minimum_samples:
        passed, reason = False, "insufficient_samples"
    else:
        passed = (
            observed >= definition.threshold
            if definition.comparator == "gte"
            else observed <= definition.threshold
        )
        reason = "threshold_satisfied" if passed else "threshold_missed"
    return SLOResult(
        definition_key=definition.key,
        definition_version=definition.version,
        samples=samples,
        observed=observed,
        passed=passed,
        reason=reason,
    )


class OperatorCommand(BaseModel):
    model_config = ConfigDict(frozen=True)
    command_id: uuid.UUID
    action: OperatorAction
    scope_type: Literal["global", "workspace", "capability", "workflow", "manifest"]
    scope_reference: str
    expected_version: int
    reason: str
    idempotency_key: str
    occurred_at: datetime

    @model_validator(mode="after")
    def validate_command(self) -> OperatorCommand:
        if self.expected_version < 0 or not self.scope_reference.strip():
            raise HardeningError("operator scope or version is invalid")
        if len(self.reason.strip()) < 8:
            raise HardeningError("operator reason is required")
        if not self.idempotency_key.strip() or self.occurred_at.tzinfo is None:
            raise HardeningError("operator identity and clock are required")
        return self


class EvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: uuid.UUID
    dataset_key: str
    dataset_version: int
    commit_sha: str
    result_digest: str
    passed: bool
    critical_findings: int
    high_findings: int
    measured_at: datetime

    @model_validator(mode="after")
    def validate_result(self) -> EvaluationResult:
        if not KEY.fullmatch(self.dataset_key) or self.dataset_version < 1:
            raise HardeningError("evaluation dataset identity is invalid")
        if not COMMIT.fullmatch(self.commit_sha) or not DIGEST.fullmatch(self.result_digest):
            raise HardeningError("evaluation evidence digest is invalid")
        if min(self.critical_findings, self.high_findings) < 0:
            raise HardeningError("evaluation finding counts are invalid")
        if self.measured_at.tzinfo is None:
            raise HardeningError("evaluation clock must be timezone-aware")
        return self

    @computed_field
    @property
    def release_eligible(self) -> bool:
        return self.passed and self.critical_findings == 0 and self.high_findings == 0


class RecoveryDrillResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    drill_id: uuid.UUID
    drill_type: Literal["backup", "restore", "export", "closure", "deletion"]
    artifact_digest: str
    restored_digest: str
    rpo_seconds: int
    rto_seconds: int
    passed: bool
    performed_at: datetime

    @model_validator(mode="after")
    def validate_drill(self) -> RecoveryDrillResult:
        if not DIGEST.fullmatch(self.artifact_digest) or not DIGEST.fullmatch(self.restored_digest):
            raise HardeningError("recovery evidence digest is invalid")
        if min(self.rpo_seconds, self.rto_seconds) < 0 or self.performed_at.tzinfo is None:
            raise HardeningError("recovery measurement is invalid")
        return self

    @computed_field
    @property
    def verified(self) -> bool:
        return self.passed and self.artifact_digest == self.restored_digest
