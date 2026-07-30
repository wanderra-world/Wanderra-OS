"""Architecture fitness checks for the bounded Formal H1 Exit slice."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "H1_EXIT_EVIDENCE.md"
MIGRATIONS = ROOT / "alembic/versions"


def test_h1_10_uses_the_accepted_h1_schema_without_new_migration() -> None:
    revisions = sorted(MIGRATIONS.glob("*.py"))
    assert revisions[-1].name == "0013_add_recovery_closure.py"
    assert len(revisions) == 13


def test_h1_10_evidence_covers_every_formal_exit_criterion() -> None:
    evidence = EVIDENCE.read_text()
    for required in (
        "Synthetic tenant isolation",
        "Session revocation",
        "Authorization",
        "Audit integrity",
        "Event idempotency and concurrency",
        "Backup and isolated restore",
        "Workspace closure and deletion",
        "Repository context enforcement",
        "Phase 1 compatibility",
        "Security review",
        "Formal H1 Exit",
    ):
        assert required in evidence


def test_h1_10_does_not_authorize_or_implement_h2() -> None:
    evidence = EVIDENCE.read_text().lower()
    assert "h2 status: not started" in evidence
    assert "provider migration: not performed" in evidence
    assert "formal h1 exit is accepted" in evidence
