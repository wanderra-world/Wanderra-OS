from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_09_is_provider_neutral_and_excludes_future_slices() -> None:
    root = ROOT / "app" / "notifications"
    production = "\n".join(path.read_text() for path in root.rglob("*.py")).casefold()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar",
        "drive",
        "slack",
        "telegram",
        "whatsapp",
        "agent registry",
        "planner",
        "orchestrator",
    ):
        assert forbidden not in production
    assert "protocol" in production
    assert not (ROOT / "app" / "h4").exists()


def test_h3_09_migration_is_additive_forced_rls_and_guarded() -> None:
    text = (ROOT / "alembic" / "versions" / "0030_add_notification_center.py").read_text()
    assert 'down_revision = "0029_h3_workflow_approval"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text
