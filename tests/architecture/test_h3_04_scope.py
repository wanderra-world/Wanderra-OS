"""Architecture Fitness boundary for the H3-04-only implementation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_04_knowledge_is_provider_neutral_and_excludes_later_slices() -> None:
    context = ROOT / "app" / "knowledge"
    assert context.is_dir()
    production = "\n".join(path.read_text() for path in context.rglob("*.py")).casefold()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar_capability",
        "drive adapter",
        "memory item",
        "embedding",
        "vector search",
        "business agent",
    ):
        assert forbidden not in production
    for later_context in ("notifications",):
        assert not (ROOT / "app" / later_context).exists()


def test_h3_04_migration_is_additive_forced_rls_and_guarded() -> None:
    text = (ROOT / "alembic" / "versions" / "0025_add_knowledge_timeline.py").read_text()
    assert 'down_revision = "0024_h3_document_custody"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text


def test_h3_04_keeps_knowledge_timeline_and_audit_separate() -> None:
    models = (ROOT / "app" / "knowledge" / "models.py").read_text()
    assert '"knowledge_claims"' in models
    assert '"knowledge_evidence"' in models
    assert '"knowledge_source_dispositions"' in models
    assert '"timeline_entries"' in models
    assert '"timeline_checkpoints"' in models
    assert '"audit_events"' not in models
    assert "Memory" not in models


def test_h3_04_uses_h3_02_jobs_without_cross_context_repository_access() -> None:
    service = (ROOT / "app" / "knowledge" / "service.py").read_text()
    assert "SourceDispositionJobPort" in service
    assert "JobRepository" not in service
    assert "app.jobs.repository" not in service
    repository = (ROOT / "app" / "knowledge" / "repository.py").read_text()
    assert "pg_advisory_xact_lock" in repository


def test_h3_03_scope_gate_now_defers_knowledge_to_h3_04() -> None:
    previous = (ROOT / "tests" / "architecture" / "test_h3_03_scope.py").read_text()
    assert 'later_context in ("notifications",)' in previous
