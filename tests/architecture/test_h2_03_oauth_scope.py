"""Failing-first architecture fitness tests for strict H2-03 isolation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_ROOT = ROOT / "app" / "oauth_transactions"


def test_h2_03_module_exists_and_has_no_provider_sdk_or_later_slice_imports() -> None:
    assert MODULE_ROOT.is_dir()
    forbidden = (
        "google.",
        "googleapiclient",
        "google_auth_oauthlib",
        "app.integrations.gmail",
        "app.integrations.calendar",
        "app.integrations.drive",
        "app.provider_mirrors",
        "app.capabilities",
        "app.memory",
        "app.search",
        "app.agents",
        "app.workflows",
    )
    for path in MODULE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports = [node.module]
            assert not any(
                name.startswith(prefix)
                for name in imports
                for prefix in forbidden
            ), f"{path.name} imports forbidden boundary {imports}"


def test_h2_03_does_not_move_provider_business_operations() -> None:
    source = "\n".join(path.read_text() for path in MODULE_ROOT.glob("*.py"))
    forbidden_operation_names = (
        "list_messages",
        "send_email",
        "list_events",
        "create_event",
        "list_files",
        "upload_file",
        "provider_mirror",
        "external_reference",
    )
    assert not any(name in source for name in forbidden_operation_names)


def test_h2_03_never_persists_raw_state_pkce_or_authorization_code() -> None:
    model_source = (MODULE_ROOT / "models.py").read_text()
    forbidden_columns = (
        "state =",
        "raw_state",
        "code_verifier",
        "authorization_code",
        "access_token",
        "refresh_token",
    )
    assert not any(column in model_source for column in forbidden_columns)
