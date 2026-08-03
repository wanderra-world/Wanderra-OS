from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_08_is_provider_neutral_and_excludes_later_slices() -> None:
    root = ROOT / "app" / "workflows"
    production = "\n".join(path.read_text() for path in root.rglob("*.py")).casefold()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar",
        "drive",
        "notification",
        "agent",
        "slack",
    ):
        assert forbidden not in production
    assert not (ROOT / "app" / "notifications").exists()


def test_h3_08_migration_is_additive_forced_rls_and_guarded() -> None:
    text = (ROOT / "alembic" / "versions" / "0029_add_workflow_approval.py").read_text()
    assert 'down_revision = "0028_h3_task_manager"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text
