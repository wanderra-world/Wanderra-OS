"""Architecture fitness evidence for strict H2-02 slice isolation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_ROOT = ROOT / "app" / "connection_credentials"


def test_h2_02_core_has_no_provider_sdk_or_later_slice_dependencies() -> None:
    forbidden_prefixes = (
        "google.",
        "googleapiclient",
        "app.integrations",
        "app.memory",
        "app.search",
        "app.agents",
        "app.workflows",
    )
    for path in MODULE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            assert not any(
                name.startswith(prefix)
                for name in imported
                for prefix in forbidden_prefixes
            ), f"{path.name} imports forbidden boundary {imported}"


def test_phase_one_compatibility_is_confined_to_migration_adapter() -> None:
    phase_one_importers: list[str] = []
    for path in MODULE_ROOT.glob("*.py"):
        if "app.models.gmail" in path.read_text() or "app.models.calendar" in path.read_text():
            phase_one_importers.append(path.name)
    assert phase_one_importers == ["phase_one.py"]


def test_h2_02_does_not_change_phase_one_runtime_read_paths() -> None:
    for relative in (
        "app/integrations/gmail/service.py",
        "app/integrations/calendar/service.py",
        "app/integrations/drive/service.py",
    ):
        source = (ROOT / relative).read_text()
        assert "connection_credentials" not in source
        assert "envelope_cutover" not in source


def test_no_secret_material_is_written_to_audit_or_outbox_details() -> None:
    source = (MODULE_ROOT / "service.py").read_text()
    tree = ast.parse(source)
    forbidden_keys = {
        "token",
        "secret",
        "plaintext",
        "ciphertext",
        "wrapped_dek",
        "refresh_token",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            assert not keys.intersection(forbidden_keys)
