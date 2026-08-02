from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_h3_06_is_provider_neutral_and_slice_isolated() -> None:
    source = "\n".join(
        path.read_text() for path in sorted((ROOT / "app" / "search_context").glob("*.py"))
    ).lower()
    for forbidden in ("gmail", "google drive", "google calendar", "h3-07", "business agent"):
        assert forbidden not in source


def test_h3_06_migration_is_additive_forced_rls_and_guarded() -> None:
    migration = (ROOT / "alembic/versions/0027_add_search_context.py").read_text()
    assert 'down_revision = "0026_h3_governed_memory"' in migration
    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "use a reviewed forward fix or export" in migration
    assert "op.alter_column" not in migration
    assert "op.drop_column" not in migration


def test_h3_06_authorization_precedes_candidate_retrieval() -> None:
    repository = (ROOT / "app/search_context/repository.py").read_text()
    assert "self._authorized(actor_id)" in repository
    assert "SearchAclProjection" in repository
    assert 'Resource.status == "active"' in repository
