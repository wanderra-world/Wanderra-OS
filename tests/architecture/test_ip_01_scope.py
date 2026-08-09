from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "app" / "integration_layer"


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text())
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return tuple(values)


def test_ip_01_is_provider_neutral_and_has_no_external_boundary() -> None:
    assert MODULE.is_dir()
    forbidden_imports = (
        "google",
        "googleapiclient",
        "requests",
        "httpx",
        "app.integrations",
        "app.email_capability",
        "app.calendar_capability",
        "app.storage_capability",
    )
    for path in MODULE.glob("*.py"):
        assert not any(
            imported.startswith(forbidden)
            for imported in _imports(path)
            for forbidden in forbidden_imports
        )


def test_ip_01_reuses_canonical_h2_models_and_adds_no_migration() -> None:
    source = "\n".join(path.read_text() for path in MODULE.glob("*.py"))
    assert "app.connections" in source
    assert "app.connection_credentials" in source
    assert "app.provider_capabilities" in source
    assert "class Integration(" not in source
    assert "class Provider(" not in source
    assert "class Account(" not in source
    assert "class Credential(" not in source
    assert not (ROOT / "alembic" / "versions" / "0033_add_integration_layer.py").exists()


def test_ip_01_governance_and_evidence_are_traceable() -> None:
    index = (ROOT / "README_ARCHITECTURE.md").read_text()
    status = (ROOT / "PROJECT_STATUS.md").read_text()
    evidence = (ROOT / "IP_01_ACCEPTANCE_EVIDENCE.md").read_text()
    assert "IP-01 Provider-Neutral Integration Layer Foundation" in index
    assert "IP-01 Provider-Neutral Integration Layer Foundation" in status
    assert "H2 canonical ownership map" in evidence
    assert "No provider adapter" in evidence


def test_ip_01_and_ip_02_are_accepted_and_ip_03_is_authorized() -> None:
    index = " ".join((ROOT / "README_ARCHITECTURE.md").read_text().split())
    status = " ".join((ROOT / "PROJECT_STATUS.md").read_text().split())
    evidence = (ROOT / "IP_01_ACCEPTANCE_EVIDENCE.md").read_text()
    decisions = " ".join((ROOT / "DECISIONS.md").read_text().split())
    guide = (ROOT / "IMPLEMENTATION_GUIDE.md").read_text()

    assert "IP-01 Provider-Neutral Integration Layer Foundation is Accepted" in index
    assert "IP-01 Provider-Neutral Integration Layer Foundation is Accepted" in status
    assert "**Status:** Accepted and merged through PR #48" in evidence
    assert "GitHub Architecture Fitness, Regression Tests" in evidence
    assert "IP-02 implementation authorization" in decisions
    assert "IP-02 Gmail OAuth Workspace Connection is Accepted" in index
    assert "IP-03 Operator-facing Gmail Connection Lifecycle is the only authorized" in index
    assert "### IP-02 Gmail OAuth Workspace Connection" in guide
    assert "`0032_h3_platform_hardening` remains the accepted migration baseline" in guide
    for excluded in (
        "Calendar",
        "Drive",
        "Contacts",
        "WhatsApp",
        "Stripe",
        "LinkedIn",
        "Facebook",
        "Instagram",
        "TikTok",
        "YouTube",
        "X",
        "CRM",
        "business agents",
    ):
        assert excluded in index
    assert not (ROOT / "app" / "ip_02").exists()
    assert not (ROOT / "alembic" / "versions" / "0033_add_ip_02.py").exists()
