"""Architecture fitness evidence for strict H2-01 slice isolation."""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONNECTION_ROOT = REPOSITORY_ROOT / "app" / "connections"
FORBIDDEN_PROVIDER_MODULES = (
    "google",
    "googleapiclient",
    "app.integrations",
)
FORBIDDEN_LATER_SLICE_TERMS = (
    "access_token",
    "refresh_token",
    "pkce",
    "oauth",
    "ciphertext",
    "encrypted_envelope",
    "provider_mirror",
    "external_reference",
)


def test_h2_01_has_no_provider_sdk_or_adapter_dependency() -> None:
    python_files = sorted(CONNECTION_ROOT.glob("*.py"))
    assert python_files
    for path in python_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(
            module == forbidden or module.startswith(f"{forbidden}.")
            for module in imported
            for forbidden in FORBIDDEN_PROVIDER_MODULES
        ), f"{path} imports a provider or adapter module"


def test_h2_01_does_not_introduce_h2_02_or_later_concepts() -> None:
    for path in sorted(CONNECTION_ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        assert not any(term in source for term in FORBIDDEN_LATER_SLICE_TERMS), (
            f"{path} introduces a later H2 concept"
        )
