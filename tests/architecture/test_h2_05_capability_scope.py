"""Architecture fitness tests for strict H2-05 slice isolation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_ROOT = ROOT / "app" / "provider_capabilities"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_h2_05_module_has_no_provider_sdk_or_runtime_imports() -> None:
    assert MODULE_ROOT.is_dir()
    forbidden = (
        "google.",
        "googleapiclient",
        "google_auth_oauthlib",
        "app.integrations",
        "app.database",
        "sqlalchemy",
        "fastapi",
    )
    for path in MODULE_ROOT.glob("*.py"):
        assert not any(
            name.startswith(prefix) for name in _imports(path) for prefix in forbidden
        )


def test_h2_05_contains_no_adapter_cutover_or_later_slice_concepts() -> None:
    source = "\n".join(path.read_text() for path in MODULE_ROOT.glob("*.py")).lower()
    forbidden = (
        "gmail",
        "google calendar",
        "google drive",
        "webhook",
        "scheduler",
        "worker",
        "shadow read",
        "cutover",
        "universal_entity",
    )
    assert not any(term in source for term in forbidden)


def test_application_and_business_modules_do_not_branch_on_provider_names() -> None:
    roots = (
        ROOT / "app" / "provider_capabilities",
        ROOT / "app" / "connections",
        ROOT / "app" / "provider_mirrors",
    )
    provider_names = ("google", "microsoft", "dropbox")
    violations: list[str] = []
    for module_root in roots:
        for path in module_root.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    text = ast.unparse(node.test).lower()
                    if any(name in text for name in provider_names):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []
