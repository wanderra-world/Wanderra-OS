"""Architecture fitness boundary for the H3-03-only implementation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_03_is_provider_neutral_and_excludes_later_slices() -> None:
    documents = ROOT / "app" / "documents"
    assert documents.is_dir()
    production = "\n".join(
        path.read_text(encoding="utf-8") for path in documents.rglob("*.py")
    ).casefold()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar_capability",
        "drive adapter",
        "knowledge claim",
        "embedding",
        "vector search",
        "business agent",
    ):
        assert forbidden not in production
    for later_context in ("platform_hardening",):
        assert not (ROOT / "app" / later_context).exists()


def test_h3_03_migration_is_additive_forced_rls_and_guarded() -> None:
    migration = ROOT / "alembic" / "versions" / "0024_add_document_custody.py"
    text = migration.read_text(encoding="utf-8")
    assert 'down_revision = "0023_h3_durable_execution"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text


def test_h3_03_documents_remain_a_distinct_data_plane() -> None:
    models = (ROOT / "app" / "documents" / "models.py").read_text(encoding="utf-8")
    for forbidden_table in (
        "knowledge_claims",
        "memory_items",
        "timeline_events",
        "search_documents",
    ):
        assert forbidden_table not in models
    assert "document_versions" in models
    assert "document_derivatives" in models
    assert "document_chunks" in models


def test_h3_03_reuses_h3_02_jobs_without_cross_context_repository_access() -> None:
    service = (ROOT / "app" / "documents" / "service.py").read_text(encoding="utf-8")
    assert "ExtractionJobPort" in service
    assert "JobRepository" not in service
    assert "app.jobs.repository" not in service


def test_earlier_h3_scope_gates_now_defer_documents_to_h3_03() -> None:
    h3_01 = (ROOT / "tests" / "architecture" / "test_h3_01_scope.py").read_text()
    h3_02 = (ROOT / "tests" / "architecture" / "test_h3_02_scope.py").read_text()
    assert 'later_context in ("platform_hardening",)' in h3_01
    assert 'later_context in ("platform_hardening",)' in h3_02
