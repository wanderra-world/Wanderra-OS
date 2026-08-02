"""Architecture fitness boundary for the H3-02-only implementation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_02_is_provider_neutral_and_excludes_later_slices() -> None:
    jobs = ROOT / "app" / "jobs"
    assert jobs.is_dir()
    production = "\n".join(path.read_text(encoding="utf-8") for path in jobs.rglob("*.py")).lower()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar_capability",
        "storage_capability",
        "embedding",
        "model planning",
        "business agent",
    ):
        assert forbidden not in production
    for later_context in ("workflows", "notifications"):
        assert not (ROOT / "app" / later_context).exists()


def test_h3_02_migration_is_additive_forced_rls_and_guarded() -> None:
    migration = ROOT / "alembic" / "versions" / "0023_add_durable_execution.py"
    text = migration.read_text(encoding="utf-8")
    assert 'down_revision = "0022_h3_resource_graph"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text


def test_h3_01_scope_defers_jobs_and_documents_without_changing_resource_graph() -> None:
    h3_01 = (ROOT / "tests" / "architecture" / "test_h3_01_scope.py").read_text()
    assert 'later_context in ("workflows",)' in h3_01
    assert '"jobs"' not in h3_01.split("later_context in", 1)[1]
    assert '"documents"' not in h3_01.split("later_context in", 1)[1]


def test_required_gate_smoke_tests_the_deployable_worker() -> None:
    workflow = (ROOT / ".github" / "workflows" / "h0-required.yml").read_text()
    assert "Smoke-test durable worker" in workflow
    assert "-m app.workers.durable --smoke" in workflow
