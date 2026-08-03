"""Architecture fitness boundary for H3-01."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_01_is_provider_neutral_and_contains_no_later_slice_modules() -> None:
    graph = ROOT / "app" / "resource_graph"
    assert graph.is_dir()
    production = "\n".join(path.read_text(encoding="utf-8") for path in graph.rglob("*.py")).lower()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar",
        "drive",
        "scheduler",
        "workflow",
        "agent",
        "embedding",
        "vector",
    ):
        assert forbidden not in production
    for later_context in ("agent_platform",):
        assert not (ROOT / "app" / later_context).exists()


def test_h3_01_migration_is_additive_and_guarded() -> None:
    migration = ROOT / "alembic" / "versions" / "0022_add_resource_graph.py"
    text = migration.read_text(encoding="utf-8")
    assert 'down_revision = "0021_h2_connection_cutover"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text
