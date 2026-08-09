"""Architecture Fitness for the bounded ADR-036 bootstrap ceremony."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_adr_036_is_indexed_and_records_final_exact_approval() -> None:
    decisions = (ROOT / "DECISIONS.md").read_text()
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    guide = (ROOT / "IMPLEMENTATION_GUIDE.md").read_text()

    assert "## ADR-036:" in decisions
    assert "The ceremony MUST stop after verification" in decisions
    assert "MUST NOT create an `ExternalIdentityLink` until" in decisions
    assert "Accepted and executed once" in decisions
    assert "ADR-036" in index
    assert "completed once" in index
    assert "now disabled" in index
    assert "Preparation approval alone cannot create the link" in guide


def test_bootstrap_has_no_application_route_session_or_email_lookup() -> None:
    router = (ROOT / "app/api/v1/operator_auth.py").read_text()
    bootstrap = (ROOT / "app/identity/bootstrap.py").read_text()
    command = (ROOT / "app/identity/bootstrap_cli.py").read_text()

    assert "bootstrap" not in router.lower()
    assert "issue_session" not in bootstrap
    assert "issue_session" not in command
    assert "User.email" not in bootstrap
    assert "User.email" not in command
    assert "127.0.0.1" in command
    assert "ExternalIdentityLink" in bootstrap
    assert "AuditEvent" in bootstrap
    assert "select(func.count()).select_from(ExternalIdentityLink)" in bootstrap


def test_bootstrap_introduces_no_migration() -> None:
    versions = sorted((ROOT / "alembic/versions").glob("*.py"))
    assert versions[-1].name == "0032_add_platform_hardening.py"
