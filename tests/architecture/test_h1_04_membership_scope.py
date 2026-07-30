"""Architecture fitness rules that keep H1-04 membership-only."""

from __future__ import annotations

import ast
from pathlib import Path

import app.models  # noqa: F401
from app.database.base import Base

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MEMBERSHIP_ROOT = REPOSITORY_ROOT / "app" / "memberships"


def test_h1_04_has_no_permission_policy_or_capability_schema() -> None:
    prohibited_tables = {
        "capabilities",
        "exceptional_grants",
        "permissions",
        "policy_decisions",
        "role_capabilities",
        "role_permissions",
    }
    assert prohibited_tables.isdisjoint(Base.metadata.tables)


def test_h1_04_membership_boundary_has_no_provider_or_agent_dependencies() -> None:
    prohibited_prefixes = (
        "app.agents",
        "app.integrations",
        "app.memory",
        "google",
        "openai",
    )
    for source_path in MEMBERSHIP_ROOT.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(
            module.startswith(prohibited_prefixes)
            for module in imported_modules
        ), source_path


def test_h1_04_does_not_expose_api_routes_or_authorization_decisions() -> None:
    for source_path in MEMBERSHIP_ROOT.glob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert "APIRouter" not in source
        assert "PolicyDecision" not in source
        assert "deny_reason" not in source
