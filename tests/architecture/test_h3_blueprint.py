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


def test_h3_03_governance_gate_has_one_normative_policy_owner() -> None:
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    architecture = (ROOT / "H3_ARCHITECTURE.md").read_text()
    guide = (ROOT / "H3_IMPLEMENTATION_GUIDE.md").read_text()
    status = (ROOT / "PROJECT_STATUS.md").read_text()
    evidence = (ROOT / "H3_02_ACCEPTANCE_EVIDENCE.md").read_text()

    assert "H3-01 is Accepted and merged" in index
    assert "H3-02 is Accepted and" in index
    assert "H3-03 implementation gate is open" in index
    assert "H3-01 Resource Graph is Accepted and merged" in status
    assert "H3-02 Durable\nExecution and Scheduler is Accepted and merged" in status
    assert "**Status:** Accepted and merged through PR #28" in evidence
    assert "`0023_h3_durable_execution`" in index
    assert "`0023_h3_durable_execution`" in status
    assert "H3-03 accepted security-review scope" in guide
    assert "H3-03 accepted classification impact" in guide
    assert "H3-03 accepted custody impact" in guide
    assert "H3-03 accepted retention impact" in guide
    assert "H3-03 accepted deletion impact" in guide
    assert "H3-03 accepted recovery impact" in guide
    assert "H3-03 accepted migration plan" in guide
    assert "H3-02 SLO and quota policy" in architecture
    assert "H3-04 and later slices" in index
