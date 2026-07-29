"""Executable dependency and canonical-scope fitness gate for H0-12."""

from pathlib import Path

from tests.architecture.fitness import (
    check_business_provider_independence,
    check_canonical_scope,
    check_postgresql_default,
    check_postgresql_platform,
    python_sources,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPOSITORY_ROOT / "app"


def test_fit_scope_001_repository_contains_no_deferred_core_modules() -> None:
    """FIT-SCOPE-001 keeps future business modules outside the Phase 2 core."""

    violations = check_canonical_scope(
        python_sources(APP_ROOT),
        repository_root=REPOSITORY_ROOT,
    )

    assert not violations, "\n".join(str(violation) for violation in violations)


def test_fit_scope_002_deferred_module_is_detected(tmp_path: Path) -> None:
    """FIT-SCOPE-001 proves the scope rule rejects premature finance code."""

    source = tmp_path / "app" / "finance" / "invoice.py"
    source.parent.mkdir(parents=True)
    source.write_text("class Invoice: pass\n", encoding="utf-8")

    violations = check_canonical_scope(
        (source,),
        repository_root=tmp_path,
    )

    assert len(violations) == 1
    assert violations[0].rule_id == "FIT-SCOPE-001"
    assert "deferred module 'finance'" in violations[0].message


def test_fit_scope_003_new_broad_agent_module_is_detected(tmp_path: Path) -> None:
    """FIT-SCOPE-001 freezes the existing Phase 1 agent compatibility surface."""

    source = tmp_path / "app" / "agents" / "autonomous_planner.py"
    source.parent.mkdir(parents=True)
    source.write_text("class AutonomousPlanner: pass\n", encoding="utf-8")

    violations = check_canonical_scope(
        (source,),
        repository_root=tmp_path,
    )

    assert len(violations) == 1
    assert "new broad agent modules are deferred" in violations[0].message


def test_fit_scope_004_business_modules_are_provider_neutral() -> None:
    """FIT-SCOPE-002 prevents adapters from leaking into business modules."""

    violations = check_business_provider_independence(
        python_sources(APP_ROOT),
        repository_root=REPOSITORY_ROOT,
    )

    assert not violations, "\n".join(str(violation) for violation in violations)


def test_fit_scope_005_provider_dependency_leak_is_detected(tmp_path: Path) -> None:
    """FIT-SCOPE-002 proves business code cannot import provider adapters."""

    source = tmp_path / "app" / "domain" / "project.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from app.integrations.gmail.service import GmailService\n",
        encoding="utf-8",
    )

    violations = check_business_provider_independence(
        (source,),
        repository_root=tmp_path,
    )

    assert len(violations) == 1
    assert violations[0].rule_id == "FIT-SCOPE-002"


def test_fit_scope_006_postgresql_is_the_only_record_search_platform() -> None:
    """FIT-SCOPE-003 retains PostgreSQL until extraction criteria are measured."""

    violations = check_postgresql_platform(REPOSITORY_ROOT / "pyproject.toml")

    assert not violations, "\n".join(str(violation) for violation in violations)


def test_fit_scope_007_premature_search_platform_is_detected(
    tmp_path: Path,
) -> None:
    """FIT-SCOPE-003 proves external search requires evidence and a new ADR."""

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "scope-test"
version = "0.0.0"
dependencies = ["asyncpg", "sqlalchemy", "elasticsearch"]
""".strip(),
        encoding="utf-8",
    )

    violations = check_postgresql_platform(pyproject)

    assert len(violations) == 1
    assert "premature data/search platform" in violations[0].message


def test_fit_scope_008_postgresql_runtime_default_is_enforced() -> None:
    """FIT-SCOPE-004 verifies the deployable defaults to PostgreSQL/asyncpg."""

    violations = check_postgresql_default(APP_ROOT / "core" / "config.py")

    assert not violations, "\n".join(str(violation) for violation in violations)


def test_fit_scope_009_non_postgresql_default_is_detected(tmp_path: Path) -> None:
    """FIT-SCOPE-004 proves platform drift fails the architecture gate."""

    config = tmp_path / "config.py"
    config.write_text(
        'class Settings:\n    database_url: str = "sqlite:///atlas.db"\n',
        encoding="utf-8",
    )

    violations = check_postgresql_default(config)

    assert len(violations) == 1
    assert violations[0].rule_id == "FIT-SCOPE-004"
