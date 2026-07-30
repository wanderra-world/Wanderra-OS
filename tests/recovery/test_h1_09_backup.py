"""Unit evidence for encrypted backup and restore verification."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.encryption import KeyReference
from app.encryption.contracts import KeyProviderUnavailableError
from app.recovery import (
    BackupIntegrityError,
    BackupSnapshot,
    ClosureState,
    EncryptedBackupService,
    RecoveryTargetViolation,
    WorkspaceManifest,
)
from tests.encryption.support import MockManagedKeyProvider

KEY = KeyReference("atlas-backup-key", "1")
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def manifest() -> WorkspaceManifest:
    return WorkspaceManifest(
        workspace_id=uuid4(),
        schema_version=1,
        created_at=NOW,
        table_counts={"workspaces": 1, "audit_events": 3},
        table_digests={"workspaces": "a" * 64, "audit_events": "b" * 64},
    )


async def test_backup_is_authenticated_and_restore_evidence_meets_targets() -> None:
    expected = manifest()
    provider = MockManagedKeyProvider({KEY: b"k" * 32})
    service = EncryptedBackupService(provider)
    artifact = await service.create(
        BackupSnapshot(
            payload=b"postgresql-custom-format-snapshot",
            source_snapshot_at=NOW - timedelta(minutes=5),
            manifest=expected,
        ),
        key_reference=KEY,
        now=NOW,
    )
    assert b"postgresql-custom-format-snapshot" not in artifact.ciphertext

    restored_payloads: list[bytes] = []

    async def restore(payload: bytes) -> WorkspaceManifest:
        restored_payloads.append(payload)
        return expected

    evidence = await service.restore(
        artifact,
        isolated_target="restore-h1-09-001",
        restore=restore,
        started_at=NOW,
        now=NOW + timedelta(minutes=3),
    )
    assert restored_payloads == [b"postgresql-custom-format-snapshot"]
    assert evidence.counts_verified and evidence.digests_verified
    assert evidence.rpo_met and evidence.rto_met
    assert evidence.recovery_point_seconds == 300
    assert evidence.recovery_time_seconds == 180


async def test_backup_fails_closed_for_key_loss_corruption_and_drift() -> None:
    expected = manifest()
    provider = MockManagedKeyProvider({KEY: b"k" * 32})
    service = EncryptedBackupService(provider)
    artifact = await service.create(
        BackupSnapshot(b"snapshot", NOW, expected),
        key_reference=KEY,
        now=NOW,
    )
    provider.available = False
    with pytest.raises(KeyProviderUnavailableError):
        await service.restore(
            artifact,
            isolated_target="isolated",
            restore=lambda _: _return_manifest(expected),
            started_at=NOW,
            now=NOW,
        )
    provider.available = True
    corrupted = replace(
        artifact,
        ciphertext=artifact.ciphertext[:-1] + b"\x00",
    )
    with pytest.raises(BackupIntegrityError, match="authentication"):
        await service.restore(
            corrupted,
            isolated_target="isolated",
            restore=lambda _: _return_manifest(expected),
            started_at=NOW,
            now=NOW,
        )
    drifted = WorkspaceManifest(
        workspace_id=expected.workspace_id,
        schema_version=1,
        created_at=NOW,
        table_counts={"workspaces": 2},
        table_digests={"workspaces": "c" * 64},
    )
    with pytest.raises(BackupIntegrityError, match="manifest"):
        await service.restore(
            artifact,
            isolated_target="isolated",
            restore=lambda _: _return_manifest(drifted),
            started_at=NOW,
            now=NOW,
        )


async def test_recovery_targets_and_contracts_are_enforced() -> None:
    expected = manifest()
    service = EncryptedBackupService(MockManagedKeyProvider({KEY: b"k" * 32}))
    with pytest.raises(RecoveryTargetViolation, match="recovery point"):
        await service.create(
            BackupSnapshot(
                b"late",
                NOW - timedelta(minutes=16),
                expected,
            ),
            key_reference=KEY,
            now=NOW,
        )
    with pytest.raises(FrozenInstanceError):
        expected.schema_version = 2  # type: ignore[misc]
    assert ClosureState.CLOSED == "closed"


async def _return_manifest(value: WorkspaceManifest) -> WorkspaceManifest:
    return value
