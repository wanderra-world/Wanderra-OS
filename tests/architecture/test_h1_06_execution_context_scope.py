"""Architecture fitness tests for strict H1-06 slice isolation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXT_ROOT = ROOT / "app" / "execution_context"


def test_h1_06_has_canonical_context_and_repository_contracts() -> None:
    contracts = (CONTEXT_ROOT / "contracts.py").read_text()
    repository = (CONTEXT_ROOT / "repository.py").read_text()
    service = (CONTEXT_ROOT / "service.py").read_text()

    for contract in (
        "RequestContext",
        "ActorContext",
        "TenantContext",
        "ExecutionContext",
    ):
        assert f"class {contract}" in contracts
    assert "class ContextBoundRepository" in repository
    assert "set_config(" in service
    assert "TRUE" in service
    assert "session.info" in service


def test_h1_06_context_module_has_no_deferred_capabilities() -> None:
    source = "\n".join(
        path.read_text()
        for path in CONTEXT_ROOT.glob("*.py")
    ).lower()
    for deferred in (
        "custom_role",
        "permission_inheritance",
        "attribute_based",
        "agent_authorization",
        "workflow_engine",
        "memory_engine",
        "search_index",
        "notification_service",
        "background_job",
    ):
        assert deferred not in source


def test_h1_06_does_not_import_phase_one_provider_modules() -> None:
    for path in CONTEXT_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(module.startswith("app.integrations") for module in imports)
        assert not any(module.startswith("app.api") for module in imports)


def test_h1_06_adds_no_domain_schema_or_authorization_changes() -> None:
    assert not list(
        (ROOT / "alembic" / "versions").glob("*execution_context*")
    ), "H1-06 execution context must remain schema-free"
    changed_context_sources = {
        path.name for path in CONTEXT_ROOT.glob("*.py")
    }
    assert changed_context_sources == {
        "__init__.py",
        "contracts.py",
        "repository.py",
        "service.py",
    }
