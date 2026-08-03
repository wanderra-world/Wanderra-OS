"""Architecture Fitness boundary for the H3-05-only implementation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_05_stays_inside_memory_and_excludes_later_slices() -> None:
    context = ROOT / "app" / "memory"
    assert (context / "governance_contracts.py").is_file()
    production = "\n".join(
        path.read_text() for path in context.glob("governed_*.py") if path.is_file()
    ).casefold()
    for forbidden in (
        "googleapiclient",
        "gmail",
        "calendar adapter",
        "drive adapter",
        "pgvector",
        "embedding",
        "hybrid search",
        "business agent",
    ):
        assert forbidden not in production
    for later_context in ("h4",):
        assert not (ROOT / "app" / later_context).exists()


def test_h3_05_migration_is_additive_forced_rls_and_guarded() -> None:
    text = (ROOT / "alembic" / "versions" / "0026_add_governed_memory.py").read_text()
    assert 'down_revision = "0025_h3_knowledge_timeline"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "FORCE ROW LEVEL SECURITY" in text
    assert "reviewed forward fix" in text
    assert "drop_column" not in text


def test_h3_05_does_not_modify_legacy_memory_runtime_or_implement_search() -> None:
    assert (
        (ROOT / "app" / "memory" / "service.py")
        .read_text()
        .startswith('"""Application service for creating and retrieving durable Atlas memory."""')
    )
    governed = (ROOT / "app" / "memory" / "governed_service.py").read_text()
    assert "GovernedMemoryService" in governed
    assert "CosineSimilarity" not in governed
    assert "OpenAI" not in governed


def test_h3_04_scope_gate_now_defers_memory_to_h3_05() -> None:
    previous = (ROOT / "tests" / "architecture" / "test_h3_04_scope.py").read_text()
    assert 'for later_context in ("h4",)' in previous
