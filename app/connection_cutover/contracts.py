"""Immutable provider-neutral H2-09 migration contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class IntegrationCapability(StrEnum):
    EMAIL = "email"
    CALENDAR = "calendar"
    STORAGE = "storage"


@dataclass(frozen=True)
class BackfillCandidate:
    workspace_id: uuid.UUID
    organization_id: uuid.UUID
    cell_id: uuid.UUID
    user_id: uuid.UUID
    provider_account_id: str
    capability: IntegrationCapability
    source_record_id: str
    source_checksum: str
    credential_eligible: bool

    def __post_init__(self) -> None:
        if not self.provider_account_id.strip() or not self.source_record_id.strip():
            raise ValueError("provider account and source record are required")
        if len(self.source_checksum) != 64:
            raise ValueError("source checksum must be SHA-256")


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    workspace_id: uuid.UUID
    connection_id: uuid.UUID
    provider_account_id: str
    capabilities: tuple[IntegrationCapability, ...]
    source_records: tuple[str, ...]
    evidence_checksum: str
    exception_code: str | None


@dataclass(frozen=True, slots=True)
class CutoverThreshold:
    minimum_samples: int
    maximum_mismatch_rate: float

    def __post_init__(self) -> None:
        if self.minimum_samples < 1:
            raise ValueError("minimum samples must be positive")
        if not 0 <= self.maximum_mismatch_rate <= 1:
            raise ValueError("mismatch rate must be between zero and one")


@dataclass(frozen=True, slots=True)
class ShadowMetrics:
    samples: int
    matches: int

    def __post_init__(self) -> None:
        if self.samples < 0 or self.matches < 0 or self.matches > self.samples:
            raise ValueError("shadow metric counts are invalid")

    @property
    def mismatches(self) -> int:
        return self.samples - self.matches

    @property
    def mismatch_rate(self) -> float:
        return self.mismatches / self.samples if self.samples else 1.0


@dataclass(frozen=True, slots=True)
class CutoverDecision:
    ready: bool
    reason: str
    metrics: ShadowMetrics
    threshold: CutoverThreshold
