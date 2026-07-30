"""Architecture fitness evidence for the bounded H1-09 slice."""

from __future__ import annotations

from pathlib import Path

from app.recovery.repository import MANIFEST_TABLES

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic/versions/0013_add_recovery_closure.py"
RECOVERY = ROOT / "app/recovery"


def test_h1_09_manifest_is_limited_to_h1_owned_workspace_rows() -> None:
    assert "gmail_credentials" not in MANIFEST_TABLES
    assert "calendar_credentials" not in MANIFEST_TABLES
    assert "drive_credentials" not in MANIFEST_TABLES
    assert "conversation_messages" not in MANIFEST_TABLES
    assert "audit_events" in MANIFEST_TABLES
    assert "encrypted_envelopes" in MANIFEST_TABLES


def test_h1_09_migration_forces_rls_and_write_freeze() -> None:
    source = MIGRATION.read_text()
    for table in (
        "workspace_data_governance",
        "workspace_exports",
        "workspace_closures",
        "workspace_recovery_evidence",
    ):
        assert f'"{table}"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "enforce_workspace_write_state" in source
    assert "atlas.closure_operation" in source
    assert "recovery evidence is immutable" in source


def test_h1_09_has_no_provider_deletion_or_later_slice_runtime() -> None:
    source = "\n".join(path.read_text() for path in RECOVERY.glob("*.py")).lower()
    for forbidden in (
        "gmailservice",
        "calendarservice",
        "driveservice",
        "provider.delete",
        "cell migration",
        "workspace transfer",
        "universal entity",
        "formal h1 exit",
    ):
        assert forbidden not in source


def test_h1_09_reuses_managed_key_and_execution_context_contracts() -> None:
    backup_source = (RECOVERY / "backup.py").read_text()
    service_source = (RECOVERY / "service.py").read_text()
    assert "from app.encryption import KeyProvider, KeyReference" in backup_source
    assert "from app.execution_context import ExecutionContext" in service_source
    assert "provider_reconciliation_required" in service_source
    assert "phase_one_provider_data_erased" in service_source
