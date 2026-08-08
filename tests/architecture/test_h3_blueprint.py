"""Architecture fitness checks for the H3 blueprint and ownership boundaries."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_h3_blueprint_defines_every_slice_contract() -> None:
    architecture = (ROOT / "H3_ARCHITECTURE.md").read_text()
    required_fields = (
        "**Objective:**",
        "**Scope:**",
        "**Excluded:**",
        "**Dependencies:**",
        "**Acceptance criteria:**",
        "**Required tests:**",
        "**Rollback:**",
        "**Complexity:**",
    )

    for number in range(1, 12):
        heading = f"### H3-{number:02d}:"
        start = architecture.index(heading)
        next_start = architecture.find("### H3-", start + len(heading))
        section = architecture[start : next_start if next_start >= 0 else None]
        for field in required_fields:
            assert field in section, f"{heading} is missing {field}"


def test_h3_documents_have_single_non_overlapping_owners() -> None:
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    assert (
        "`H3_ARCHITECTURE.md` | Atlas Architecture Council | H3 vision, component"
        in index
    )
    assert (
        "`H3_IMPLEMENTATION_GUIDE.md` | Atlas Platform Engineering | H3-specific"
        in index
    )
    assert (
        "`H3_EXIT_DEFINITION.md` | Atlas Architecture Council | Formal H3 Exit"
        in index
    )


def test_h3_sequencing_change_is_accepted_without_starting_implementation() -> None:
    decisions = (ROOT / "DECISIONS.md").read_text()
    architecture = (ROOT / "H3_ARCHITECTURE.md").read_text()
    guide = (ROOT / "H3_IMPLEMENTATION_GUIDE.md").read_text()
    assert "## ADR-033:" in decisions
    assert "**Status:** Accepted; formally approved through PR #24" in decisions
    assert "**Status:** Approved;" in architecture
    assert "**Status:** Approved for implementation" in guide
    assert "h4 or later-stage implementation" in architecture.casefold()
    assert not list((ROOT / "app").glob("h3*"))


def test_h3_08_governance_gate_has_one_normative_policy_owner() -> None:
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    architecture = (ROOT / "H3_ARCHITECTURE.md").read_text()
    guide = (ROOT / "H3_IMPLEMENTATION_GUIDE.md").read_text()
    status = (ROOT / "PROJECT_STATUS.md").read_text()
    evidence = (ROOT / "H3_07_ACCEPTANCE_EVIDENCE.md").read_text()
    normalized_index = " ".join(index.split())

    assert "H3-01 is Accepted and merged" in index
    assert "H3-02 is Accepted and" in index
    assert "H3-08 is Accepted and merged through PR #40" in normalized_index
    assert "H3-01 Resource Graph is Accepted and merged" in status
    assert "H3-02 Durable\nExecution and Scheduler is Accepted and merged" in status
    assert "H3-07 Task Manager is Accepted and merged" in status
    assert "**Status:** Accepted and merged through PR #38" in evidence
    assert "H3-08 accepted security-review scope" in guide
    assert "H3-08 accepted classification and authorization impact" in guide
    assert "H3-08 accepted custody and lineage impact" in guide
    assert "H3-08 accepted retention and deletion impact" in guide
    assert "H3-08 accepted recovery and execution impact" in guide
    assert "H3-08 approved determinism, approval, and execution policy" in guide
    assert "H3-08 accepted migration plan" in guide
    assert "H3-08 implementation authorization" in guide
    assert "H3-08 governance impacts" in architecture
    for excluded in (
        "H4",
        "provider-specific integrations",
        "connectors",
        "business agents",
        "external integrations",
        "UI functionality",
    ):
        assert excluded in normalized_index


def test_h3_09_governance_gate_accepts_h3_08_and_excludes_future_work() -> None:
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    architecture = (ROOT / "H3_ARCHITECTURE.md").read_text()
    guide = (ROOT / "H3_IMPLEMENTATION_GUIDE.md").read_text()
    status = (ROOT / "PROJECT_STATUS.md").read_text()
    evidence = (ROOT / "H3_08_ACCEPTANCE_EVIDENCE.md").read_text()

    normalized_index = " ".join(index.split())
    assert "H3-08 is Accepted and merged through PR #40" in normalized_index
    assert "H3-08 Workflow and Approval Engine is Accepted and merged" in status
    assert "**Status:** Accepted and merged through PR #40" in evidence
    assert "H3-09 accepted security-review scope" in guide
    assert "H3-09 accepted classification and authorization impact" in guide
    assert "H3-09 accepted custody and lineage impact" in guide
    assert "H3-09 accepted retention and deletion impact" in guide
    assert "H3-09 accepted recovery and delivery impact" in guide
    assert "H3-09 approved determinism and delivery policy" in guide
    assert "H3-09 accepted migration plan" in guide
    assert "H3-09 implementation authorization" in guide
    assert "H3-09 governance impacts" in architecture
    for excluded in (
        "H4",
        "provider-specific integrations",
        "connectors",
        "business agents",
        "external integrations",
        "UI functionality",
    ):
        assert excluded in normalized_index


def test_h3_11_governance_gate_accepts_h3_10_and_excludes_future_work() -> None:
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    architecture = (ROOT / "H3_ARCHITECTURE.md").read_text()
    guide = (ROOT / "H3_IMPLEMENTATION_GUIDE.md").read_text()
    status = (ROOT / "PROJECT_STATUS.md").read_text()
    evidence = (ROOT / "H3_10_ACCEPTANCE_EVIDENCE.md").read_text()

    normalized_index = " ".join(index.split())
    normalized_status = " ".join(status.split())
    assert "H3-10 is Accepted and merged through PR #44" in normalized_index
    assert "H3-10 Agent Platform Contracts is Accepted and merged" in normalized_status
    assert "**Status:** Accepted and merged through PR #44" in evidence
    assert "`0031_h3_agent_platform`" in index
    assert "`0031_h3_agent_platform`" in status
    assert "H3-11 accepted security-review scope" in guide
    assert "H3-11 accepted classification and authorization impact" in guide
    assert "H3-11 accepted custody, evidence, and audit impact" in guide
    assert "H3-11 accepted retention, deletion, and recovery impact" in guide
    assert "H3-11 accepted SLO, telemetry, and operator-control policy" in guide
    assert "H3-11 accepted migration and rollback plan" in guide
    assert "H3-11 accepted evidence and completion boundary" in guide
    assert "H3-11 implementation authorization" in guide
    assert "H3-11 governance impacts" in architecture
    assert "H3-11 Platform Hardening and Formal H3 Exit is Accepted" in normalized_index
    for excluded in (
        "H4",
        "provider-specific integrations",
        "connectors",
        "business agents",
        "external integrations",
        "UI functionality",
    ):
        assert excluded in normalized_index
