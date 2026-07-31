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
