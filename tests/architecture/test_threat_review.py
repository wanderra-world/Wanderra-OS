"""Threat-specific evidence and negative-path matrix for Atlas P0.5."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.architecture.threat_evidence import h0_threats
from tests.architecture.threat_review_prototype import (
    MitigationEvidence,
    RiskAcceptance,
    Severity,
    ThreatRegister,
    Treatment,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_THREAT_IDS = frozenset(f"T{number:02d}" for number in range(1, 15))


def complete_register(*, threats=None) -> ThreatRegister:
    return ThreatRegister(
        threats or h0_threats(),
        required_threat_ids=REQUIRED_THREAT_IDS,
    )


def test_fit_threat_001_complete_threat_specific_register_passes_review() -> None:
    """FIT-THREAT-001 confirms T01–T14 have complete reviewed evidence."""

    review = complete_register().review(reviewed_at=NOW)

    assert review.ready_to_exit
    assert review.blockers == ()
    assert review.reviewed_threats == 14
    assert review.unresolved_critical_ids == ()


def test_fit_threat_002_register_matches_normative_threat_ids_exactly() -> None:
    """FIT-THREAT-002 prevents missing or invented threat records."""

    assert {threat.threat_id for threat in h0_threats()} == REQUIRED_THREAT_IDS


def test_fit_threat_003_every_mitigation_evidence_reference_resolves() -> None:
    """FIT-THREAT-003 proves evidence links name real executable tests."""

    for threat in h0_threats():
        for evidence in threat.evidence_references:
            source = REPOSITORY_ROOT / evidence.source_path
            assert source.is_file(), f"{threat.threat_id}: missing {evidence.source_path}"
            assert evidence.test_id in source.read_text(encoding="utf-8"), (
                f"{threat.threat_id}: {evidence.test_id} not found in "
                f"{evidence.source_path}"
            )


def test_fit_threat_004_all_threats_have_explicit_residual_risk_and_owner() -> None:
    """FIT-THREAT-004 requires accountable inherent-to-residual assessment."""

    for threat in h0_threats():
        assert threat.risk_owner.strip()
        assert threat.inherent_severity in Severity
        assert threat.residual_severity in Severity
        assert threat.residual_severity <= threat.inherent_severity
        assert threat.evidence_references


def test_fit_threat_005_open_noncritical_gaps_are_owned_and_documented() -> None:
    """FIT-THREAT-005 permits visible gaps but never hides their residual risk."""

    unresolved = tuple(
        threat
        for threat in h0_threats()
        if threat.treatment is Treatment.UNRESOLVED
    )

    assert {threat.threat_id for threat in unresolved} == {"T12", "T13", "T14"}
    assert all(threat.residual_severity is Severity.HIGH for threat in unresolved)
    assert all(threat.remaining_gap and threat.remaining_gap.strip() for threat in unresolved)


def test_fit_threat_006_unaccepted_residual_critical_threat_blocks_exit() -> None:
    """FIT-THREAT-006 enforces the normative no-unaccepted-critical-risk gate."""

    threats = list(h0_threats())
    threats[0] = replace(
        threats[0],
        residual_severity=Severity.CRITICAL,
        treatment=Treatment.UNRESOLVED,
        remaining_gap="Critical isolation control is unresolved.",
    )

    review = complete_register(threats=tuple(threats)).review(reviewed_at=NOW)

    assert not review.ready_to_exit
    assert review.unresolved_critical_ids == ("T01",)
    assert "T01: residual critical threat is unaccepted" in review.blockers


@pytest.mark.parametrize(
    ("acceptance", "message"),
    [
        (
            RiskAcceptance(
                owner="",
                compensating_controls=("disable affected capability",),
                expires_at=NOW + timedelta(days=7),
                approved_by="cto",
                approval_reference="risk-001",
            ),
            "named owner",
        ),
        (
            RiskAcceptance(
                owner="security-owner",
                compensating_controls=(),
                expires_at=NOW + timedelta(days=7),
                approved_by="cto",
                approval_reference="risk-001",
            ),
            "compensating control",
        ),
        (
            RiskAcceptance(
                owner="security-owner",
                compensating_controls=("disable affected capability",),
                expires_at=NOW,
                approved_by="cto",
                approval_reference="risk-001",
            ),
            "must not be expired",
        ),
        (
            RiskAcceptance(
                owner="security-owner",
                compensating_controls=("disable affected capability",),
                expires_at=NOW + timedelta(days=7),
                approved_by="",
                approval_reference="risk-001",
            ),
            "approver",
        ),
        (
            RiskAcceptance(
                owner="security-owner",
                compensating_controls=("disable affected capability",),
                expires_at=NOW + timedelta(days=7),
                approved_by="cto",
                approval_reference="",
            ),
            "approval reference",
        ),
    ],
)
def test_fit_threat_007_critical_acceptance_requires_complete_governance(
    acceptance: RiskAcceptance,
    message: str,
) -> None:
    """FIT-THREAT-007 rejects incomplete or expired critical acceptance."""

    threats = list(h0_threats())
    threats[0] = replace(
        threats[0],
        residual_severity=Severity.CRITICAL,
        treatment=Treatment.ACCEPTED,
        acceptance=acceptance,
    )

    review = complete_register(threats=tuple(threats)).review(reviewed_at=NOW)

    assert not review.ready_to_exit
    assert any(message in blocker for blocker in review.blockers)


def test_fit_threat_008_valid_critical_acceptance_is_explicit_and_temporary() -> None:
    """FIT-THREAT-008 accepts only a governed, time-bounded exception."""

    threats = list(h0_threats())
    threats[0] = replace(
        threats[0],
        residual_severity=Severity.CRITICAL,
        treatment=Treatment.ACCEPTED,
        acceptance=RiskAcceptance(
            owner="security-owner",
            compensating_controls=("disable affected capability",),
            expires_at=NOW + timedelta(days=7),
            approved_by="cto",
            approval_reference="risk-acceptance-t01",
        ),
    )

    review = complete_register(threats=tuple(threats)).review(reviewed_at=NOW)

    assert review.ready_to_exit
    assert review.unresolved_critical_ids == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"risk_owner": ""}, "risk owner"),
        ({"trust_boundaries": ()}, "trust boundary"),
        ({"protected_assets": ()}, "protected asset"),
        ({"primary_controls": ()}, "primary control"),
        ({"evidence_references": ()}, "mitigation evidence"),
        (
            {
                "evidence_references": (
                    MitigationEvidence("", "invalid", "missing.py"),
                )
            },
            "evidence control",
        ),
    ],
)
def test_fit_threat_009_incomplete_assessment_blocks_exit(
    change: dict[str, object],
    message: str,
) -> None:
    """FIT-THREAT-009 rejects incomplete assessment and evidence metadata."""

    threats = list(h0_threats())
    threats[0] = replace(threats[0], **change)
    review = complete_register(threats=tuple(threats)).review(reviewed_at=NOW)

    assert not review.ready_to_exit
    assert any(message in blocker for blocker in review.blockers)
