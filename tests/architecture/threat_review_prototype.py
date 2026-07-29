"""Disposable H0 prototype for threat review and critical-risk acceptance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum

THREAT_ID_PATTERN = re.compile(r"^T\d{2}$")


class Severity(IntEnum):
    MODERATE = 1
    HIGH = 2
    CRITICAL = 3


class Treatment(StrEnum):
    MITIGATED = "mitigated"
    ACCEPTED = "accepted"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class RiskAcceptance:
    """Time-bounded, explicitly approved exception for one unresolved risk."""

    owner: str
    compensating_controls: tuple[str, ...]
    expires_at: datetime
    approved_by: str
    approval_reference: str

    def deficiencies(self, *, reviewed_at: datetime) -> tuple[str, ...]:
        deficiencies: list[str] = []
        if not self.owner.strip():
            deficiencies.append("risk acceptance requires a named owner")
        if not any(control.strip() for control in self.compensating_controls):
            deficiencies.append("risk acceptance requires a compensating control")
        if self.expires_at <= reviewed_at:
            deficiencies.append("risk acceptance must not be expired")
        if not self.approved_by.strip():
            deficiencies.append("risk acceptance requires an approver")
        if not self.approval_reference.strip():
            deficiencies.append("risk acceptance requires an approval reference")
        return tuple(deficiencies)


@dataclass(frozen=True, slots=True)
class MitigationEvidence:
    """Traceable control evidence resolving to one executable fitness test."""

    control: str
    test_id: str
    source_path: str

    def deficiencies(self) -> tuple[str, ...]:
        deficiencies: list[str] = []
        if not self.control.strip():
            deficiencies.append("evidence control is required")
        if not self.test_id.startswith("FIT-"):
            deficiencies.append("evidence requires a stable FIT test identifier")
        if not self.source_path.startswith("tests/architecture/test_"):
            deficiencies.append("evidence must reference an architecture test module")
        return tuple(deficiencies)


@dataclass(frozen=True, slots=True)
class Threat:
    """One reviewed threat at an identified trust boundary."""

    threat_id: str
    description: str
    risk_owner: str
    inherent_severity: Severity
    residual_severity: Severity
    trust_boundaries: tuple[str, ...]
    protected_assets: tuple[str, ...]
    primary_controls: tuple[str, ...]
    treatment: Treatment
    evidence_references: tuple[MitigationEvidence, ...]
    remaining_gap: str | None = None
    acceptance: RiskAcceptance | None = None

    def __post_init__(self) -> None:
        if THREAT_ID_PATTERN.fullmatch(self.threat_id) is None:
            raise ValueError(f"invalid threat identifier: {self.threat_id!r}")
        if self.residual_severity > self.inherent_severity:
            raise ValueError("residual severity cannot exceed inherent severity")


@dataclass(frozen=True, slots=True)
class ThreatReview:
    ready_to_exit: bool
    blockers: tuple[str, ...]
    reviewed_threats: int
    unresolved_critical_ids: tuple[str, ...]


class ThreatRegister:
    """Review engine enforcing complete coverage and explicit critical treatment."""

    def __init__(
        self,
        threats: tuple[Threat, ...],
        *,
        required_threat_ids: frozenset[str],
    ) -> None:
        threat_ids = tuple(threat.threat_id for threat in threats)
        if len(threat_ids) != len(set(threat_ids)):
            raise ValueError("threat identifiers must be unique")
        self._threats = threats
        self._required_threat_ids = required_threat_ids

    def review(self, *, reviewed_at: datetime) -> ThreatReview:
        blockers: list[str] = []
        present_ids = {threat.threat_id for threat in self._threats}

        for threat_id in sorted(self._required_threat_ids - present_ids):
            blockers.append(f"{threat_id}: required threat is missing")

        for threat in self._threats:
            prefix = f"{threat.threat_id}:"
            if not threat.description.strip():
                blockers.append(f"{prefix} description is required")
            if not threat.risk_owner.strip():
                blockers.append(f"{prefix} risk owner is required")
            if not any(boundary.strip() for boundary in threat.trust_boundaries):
                blockers.append(f"{prefix} trust boundary is required")
            if not any(asset.strip() for asset in threat.protected_assets):
                blockers.append(f"{prefix} protected asset is required")
            if not any(control.strip() for control in threat.primary_controls):
                blockers.append(f"{prefix} primary control is required")
            if not threat.evidence_references:
                blockers.append(f"{prefix} mitigation evidence is required")
            for evidence in threat.evidence_references:
                blockers.extend(
                    f"{prefix} {deficiency}"
                    for deficiency in evidence.deficiencies()
                )

            if threat.treatment is Treatment.MITIGATED:
                if threat.acceptance is not None:
                    blockers.append(
                        f"{prefix} mitigated threat must not retain risk acceptance"
                    )
            elif threat.treatment is Treatment.UNRESOLVED:
                if not threat.remaining_gap or not threat.remaining_gap.strip():
                    blockers.append(
                        f"{prefix} unresolved threat requires a documented gap"
                    )
            elif threat.treatment is Treatment.ACCEPTED:
                if threat.acceptance is None:
                    blockers.append(f"{prefix} explicit risk acceptance is required")
                else:
                    blockers.extend(
                        f"{prefix} {deficiency}"
                        for deficiency in threat.acceptance.deficiencies(
                            reviewed_at=reviewed_at
                        )
                    )

            if (
                threat.residual_severity is Severity.CRITICAL
                and threat.treatment is not Treatment.ACCEPTED
            ):
                blockers.append(f"{prefix} residual critical threat is unaccepted")

        unresolved_critical_ids = tuple(
            threat.threat_id
            for threat in self._threats
            if threat.residual_severity is Severity.CRITICAL
            and threat.treatment is not Treatment.ACCEPTED
        )
        return ThreatReview(
            ready_to_exit=not blockers,
            blockers=tuple(blockers),
            reviewed_threats=len(self._threats),
            unresolved_critical_ids=unresolved_critical_ids,
        )
