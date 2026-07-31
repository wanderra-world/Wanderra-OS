"""Architecture fitness tests for strict H2-04 slice isolation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_ROOT = ROOT / "app" / "provider_mirrors"


def test_h2_04_module_has_no_provider_sdk_or_later_slice_imports() -> None:
    assert MODULE_ROOT.is_dir()
    forbidden = (
        "google.",
        "googleapiclient",
        "google_auth_oauthlib",
        "app.integrations",
        "app.capabilities",
        "app.memory",
        "app.search",
        "app.agents",
        "app.workflows",
    )
    for path in MODULE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(
            name.startswith(prefix)
            for name in imports
            for prefix in forbidden
        )


def test_h2_04_contains_no_execution_or_later_slice_concepts() -> None:
    source = "\n".join(path.read_text() for path in MODULE_ROOT.glob("*.py"))
    forbidden = (
        "list_messages",
        "send_email",
        "list_events",
        "list_files",
        "provider sdk",
        "webhook",
        "scheduler",
        "worker",
        "universal_entity",
    )
    assert not any(term in source.lower() for term in forbidden)
