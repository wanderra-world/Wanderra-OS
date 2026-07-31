"""Architecture fitness checks for the H2-10 evidence-only exit slice."""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_h2_10_formal_evidence_is_complete_and_traceable() -> None:
    evidence = (ROOT / "H2_10_ACCEPTANCE_EVIDENCE.md").read_text()
    exit_report = (ROOT / "H2_EXIT_REPORT.md").read_text()
    matrix = (ROOT / "H2_EVIDENCE_MATRIX.md").read_text()
    security = (ROOT / "H2_SECURITY_REVIEW.md").read_text()

    for slice_number in range(1, 11):
        assert f"H2-{slice_number:02d}" in matrix
    for required in (
        "multi-provider",
        "migration",
        "rollback",
        "recovery",
        "closure",
        "Docker",
        "security",
        "H3 has not been started",
    ):
        assert required.casefold() in evidence.casefold()
    assert "Formal H2 Exit" in exit_report
    assert "critical" in security.casefold() and "high" in security.casefold()


def test_h2_10_remains_schema_free_after_the_approved_h3_successor() -> None:
    versions = sorted((ROOT / "alembic/versions").glob("*.py"))
    h2_head = next(path for path in versions if path.name.startswith("0021_"))
    assert 'revision = "0021_h2_connection_cutover"' in h2_head.read_text()
    h3_successor = next(path for path in versions if path.name.startswith("0022_"))
    assert 'down_revision = "0021_h2_connection_cutover"' in h3_successor.read_text()
    assert not (ROOT / "app/entities").exists()
