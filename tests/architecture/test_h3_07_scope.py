from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_07_is_provider_neutral_and_slice_isolated() -> None:
    source = "\n".join(
        path.read_text() for path in sorted((ROOT / "app" / "tasks").glob("*.py"))
    ).lower()
    for forbidden in (
        "gmail",
        "google drive",
        "google calendar",
        "workflow",
        "business agent",
        "h3-08",
    ):
        assert forbidden not in source


def test_h3_07_migration_is_additive_forced_rls_and_guarded() -> None:
    migration = (ROOT / "alembic/versions/0028_add_task_manager.py").read_text()
    assert 'down_revision = "0027_h3_search_context"' in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "task completion evidence is immutable" in migration
    assert "use a reviewed forward fix or export" in migration
    assert "op.alter_column" not in migration
    assert "op.drop_column" not in migration


def test_h3_07_does_not_change_accepted_layers() -> None:
    migration = (ROOT / "alembic/versions/0028_add_task_manager.py").read_text()
    for table in ("resources", "job_instances", "timeline_events", "search_documents"):
        assert f'op.create_table("{table}"' not in migration
