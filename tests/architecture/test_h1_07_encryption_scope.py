"""Architecture fitness tests for the H1-07 encryption-only boundary."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENCRYPTION_ROOT = ROOT / "app" / "encryption"


def test_h1_07_owns_one_envelope_model_and_managed_kms_port() -> None:
    models = (ENCRYPTION_ROOT / "models.py").read_text()
    contracts = (ENCRYPTION_ROOT / "contracts.py").read_text()
    providers = (
        ROOT / "app" / "integrations" / "kms" / "google_cloud.py"
    ).read_text()
    assert models.count("class EncryptedEnvelope(") == 1
    assert "class KeyProvider(Protocol)" in contracts
    assert "class GoogleCloudKmsKeyProvider" in providers
    assert "AES-256-GCM" in contracts


def test_h1_07_has_no_plaintext_or_raw_dek_persistence() -> None:
    model_source = (ENCRYPTION_ROOT / "models.py").read_text().lower()
    for forbidden in (
        "plaintext",
        "raw_dek",
        "decrypted_payload",
        "encryption_key =",
    ):
        assert forbidden not in model_source


def test_h1_07_has_no_deferred_runtime_capabilities() -> None:
    source = "\n".join(
        path.read_text()
        for path in ENCRYPTION_ROOT.rglob("*.py")
    ).lower()
    for deferred in (
        "agent_runtime",
        "workflow_engine",
        "scheduler",
        "memory_engine",
        "search_index",
        "notification_service",
        "background_job",
        "tool_execution",
        "h1_08",
    ):
        assert deferred not in source


def test_h1_07_does_not_import_provider_business_integrations() -> None:
    for path in ENCRYPTION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(module.startswith("app.integrations") for module in imports)
        assert not any(module.startswith("app.api") for module in imports)


def test_h1_07_migration_is_additive_and_keeps_legacy_ciphertext() -> None:
    migration = (
        ROOT / "alembic" / "versions" / "0011_add_managed_envelopes.py"
    ).read_text()
    assert "encrypted_envelopes" in migration
    assert "envelope_cutover" in migration
    assert "reauthorization_required" in migration
    assert 'drop_column(table_name, "encrypted_payload")' not in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "reviewed forward fix" in migration
