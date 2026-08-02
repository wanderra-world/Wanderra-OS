"""Repository-level evidence for the mandatory P0.14 CI fitness gate."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "h0-required.yml"


def workflow_text() -> str:
    assert WORKFLOW.is_file(), "P0.14 required workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")


def test_fit_ci_001_gate_runs_for_pull_requests_and_protected_branches() -> None:
    """FIT-CI-001 ensures proposed and integrated changes execute the gate."""

    workflow = workflow_text()

    assert "pull_request:" in workflow
    assert "branches:" in workflow
    assert "- master" in workflow
    assert "- main" in workflow
    assert "contents: read" in workflow


def test_fit_ci_002_architecture_job_runs_postgresql_rls_and_lint() -> None:
    """FIT-CI-002 requires the complete architecture suite and Ruff."""

    workflow = workflow_text()

    assert "image: pgvector/pgvector:pg16" in workflow
    assert "H0_TEST_DATABASE_URL:" in workflow
    assert "ruff check tests/architecture" in workflow
    assert "pytest -q tests/architecture" in workflow


def test_fit_ci_003_regression_job_runs_all_nonarchitecture_tests() -> None:
    """FIT-CI-003 keeps Phase 1 behavior under mandatory regression coverage."""

    assert (
        "pytest -q tests --ignore=tests/architecture"
        in workflow_text()
    )


def test_fit_ci_004_docker_job_builds_and_smoke_tests_production() -> None:
    """FIT-CI-004 prevents an unbuildable or unimportable image from merging."""

    workflow = workflow_text()

    assert "docker build --tag atlas-h0-ci ." in workflow
    assert "from app.main import app; assert app.title" in workflow


def test_fit_ci_005_aggregate_gate_depends_on_every_required_job() -> None:
    """FIT-CI-005 exposes one branch-protection status covering every check."""

    workflow = workflow_text()

    assert "name: H0 Required Gate" in workflow
    assert "if: always()" in workflow
    assert "- architecture" in workflow
    assert "- regression" in workflow
    assert "- docker" in workflow
    assert 'test "$ARCHITECTURE_RESULT" = "success"' in workflow
    assert 'test "$REGRESSION_RESULT" = "success"' in workflow
    assert 'test "$DOCKER_RESULT" = "success"' in workflow


def test_fit_ci_006_gate_has_bounded_execution_and_no_write_permission() -> None:
    """FIT-CI-006 limits CI runtime and repository authority."""

    workflow = workflow_text()

    assert workflow.count("timeout-minutes: 15") == 3
    assert "contents: write" not in workflow
