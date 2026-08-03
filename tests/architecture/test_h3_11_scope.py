from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_11_is_provider_neutral_and_excludes_future_product_work() -> None:
    root = ROOT / "app" / "platform_hardening"
    assert root.is_dir()
    production = "\n".join(path.read_text() for path in root.rglob("*.py")).casefold()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar",
        "drive",
        "telegram",
        "whatsapp",
        "instagram",
        "facebook",
        "linkedin",
        "tiktok",
        "provider sdk",
        "business agent",
        "subprocess",
        "exec(",
        "eval(",
    ):
        assert forbidden not in production
    assert not (ROOT / "app" / "h4").exists()
    assert not (ROOT / "app" / "business_agents").exists()


def test_h3_11_formal_evidence_set_is_complete_and_traceable() -> None:
    required = {
        "H3_EVIDENCE_MATRIX.md": ("H3-01", "H3-10", "Gate K"),
        "H3_SECURITY_REVIEW.md": ("critical", "high", "residual risk"),
        "H3_RECOVERY_REPORT.md": ("RPO", "RTO", "restore", "deletion"),
        "H3_EVALUATION_REPORT.md": ("search", "prompt injection", "planning", "cost"),
        "H3_EXIT_REPORT.md": ("Formal H3 Exit", "pending merge", "H4"),
        "H3_11_ACCEPTANCE_EVIDENCE.md": ("Architecture Fitness", "PostgreSQL", "Docker"),
        "H3_OPERATIONS_RUNBOOK.md": ("pause", "replay", "directly", "SLO"),
    }
    for filename, phrases in required.items():
        text = (ROOT / filename).read_text()
        for phrase in phrases:
            assert phrase.casefold() in text.casefold()


def test_h3_11_migration_is_additive_forced_rls_and_guarded() -> None:
    text = (ROOT / "alembic" / "versions" / "0032_add_platform_hardening.py").read_text()
    assert 'down_revision = "0031_h3_agent_platform"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text
