"""Architecture fitness rules for the H1-05 authorization boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import app.models  # noqa: F401
from app.authorization.models import Permission, RolePermission
from app.memberships.models import Role, WorkspaceMembership

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION_ROOT = REPOSITORY_ROOT / "app" / "authorization"


def test_h1_05_reuses_role_and_assignment_models_without_duplicates() -> None:
    assert Role.__tablename__ == "fixed_membership_roles"
    assert WorkspaceMembership.__tablename__ == "workspace_memberships"
    assert Permission.__tablename__ == "permissions"
    assert RolePermission.__tablename__ == "role_permissions"


def test_h1_05_has_no_provider_agent_memory_search_or_api_dependency() -> None:
    prohibited_prefixes = (
        "app.agents",
        "app.api",
        "app.integrations",
        "app.memory",
        "google",
        "openai",
    )
    for source_path in AUTHORIZATION_ROOT.glob("*.py"):
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


def test_h1_05_has_no_custom_roles_inheritance_abac_or_h1_06_context() -> None:
    combined_source = "\n".join(
        source_path.read_text(encoding="utf-8")
        for source_path in AUTHORIZATION_ROOT.glob("*.py")
    )
    for prohibited in (
        "CustomRole",
        "parent_role",
        "inherits_from",
        "atlas.actor_id",
        "set_config(",
        "APIRouter",
    ):
        assert prohibited not in combined_source
