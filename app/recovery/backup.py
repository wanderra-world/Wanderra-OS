"""Managed-key encrypted backup and isolated restore verification."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.encryption import KeyProvider, KeyReference
from app.recovery.contracts import (
    BackupArtifact,
    BackupSnapshot,
    RestoreEvidence,
    WorkspaceManifest,
)

POSTGRES_RPO_SECONDS = 15 * 60
CORE_RTO_SECONDS = 4 * 60 * 60


class BackupIntegrityError(RuntimeError):
    """Backup or restore evidence is corrupt or does not match its manifest."""


class RecoveryTargetViolation(RuntimeError):
    """A completed backup or restore exceeded an approved recovery target."""


class EncryptedBackupService:
    """Encrypt PostgreSQL snapshots and verify isolated restore evidence."""

    def __init__(self, key_provider: KeyProvider) -> None:
        self._keys = key_provider

    async def create(
        self,
        snapshot: BackupSnapshot,
        *,
        key_reference: KeyReference,
        now: datetime | None = None,
    ) -> BackupArtifact:
        completed_at = now or datetime.now(UTC)
        rpo = int((completed_at - snapshot.source_snapshot_at).total_seconds())
        if rpo < 0 or rpo > POSTGRES_RPO_SECONDS:
            raise RecoveryTargetViolation("PostgreSQL recovery point target missed")
        backup_id = uuid.uuid4()
        data_key = os.urandom(32)
        nonce = os.urandom(12)
        associated_data = self._associated_data(
            backup_id,
            snapshot.manifest.workspace_id,
            key_reference,
        )
        ciphertext = AESGCM(data_key).encrypt(
            nonce,
            snapshot.payload,
            associated_data,
        )
        wrapped_key = await self._keys.wrap_key(
            data_key,
            key_reference,
            authenticated_data=associated_data,
        )
        return BackupArtifact(
            backup_id=backup_id,
            workspace_id=snapshot.manifest.workspace_id,
            ciphertext=ciphertext,
            nonce=nonce,
            wrapped_key=wrapped_key,
            key_reference=key_reference,
            checksum=hashlib.sha256(snapshot.payload).hexdigest(),
            source_snapshot_at=snapshot.source_snapshot_at,
            completed_at=completed_at,
            manifest=snapshot.manifest,
        )

    async def restore(
        self,
        artifact: BackupArtifact,
        *,
        isolated_target: str,
        restore: Callable[[bytes], Awaitable[WorkspaceManifest]],
        started_at: datetime,
        now: datetime | None = None,
    ) -> RestoreEvidence:
        if not isolated_target.strip():
            raise ValueError("isolated restore target is required")
        data_key = await self._keys.unwrap_key(
            artifact.wrapped_key,
            artifact.key_reference,
            authenticated_data=self._associated_data(
                artifact.backup_id,
                artifact.workspace_id,
                artifact.key_reference,
            ),
        )
        try:
            plaintext = AESGCM(data_key).decrypt(
                artifact.nonce,
                artifact.ciphertext,
                self._associated_data(
                    artifact.backup_id,
                    artifact.workspace_id,
                    artifact.key_reference,
                ),
            )
        except Exception as error:
            raise BackupIntegrityError("backup authentication failed") from error
        if hashlib.sha256(plaintext).hexdigest() != artifact.checksum:
            raise BackupIntegrityError("backup checksum mismatch")
        restored_manifest = await restore(plaintext)
        if restored_manifest.workspace_id != artifact.workspace_id:
            raise BackupIntegrityError("restored workspace does not match")
        counts_verified = (
            restored_manifest.table_counts == artifact.manifest.table_counts
        )
        digests_verified = (
            restored_manifest.table_digests == artifact.manifest.table_digests
        )
        if not counts_verified or not digests_verified:
            raise BackupIntegrityError("restored manifest does not match backup")
        restored_at = now or datetime.now(UTC)
        rpo = int(
            (artifact.completed_at - artifact.source_snapshot_at).total_seconds()
        )
        rto = int((restored_at - started_at).total_seconds())
        if rto < 0:
            raise RecoveryTargetViolation("restore duration is invalid")
        return RestoreEvidence(
            backup_id=artifact.backup_id,
            workspace_id=artifact.workspace_id,
            restored_at=restored_at,
            recovery_point_seconds=rpo,
            recovery_time_seconds=rto,
            counts_verified=True,
            digests_verified=True,
            rpo_met=rpo <= POSTGRES_RPO_SECONDS,
            rto_met=rto <= CORE_RTO_SECONDS,
            isolated_target=isolated_target,
        )

    @staticmethod
    def _associated_data(
        backup_id: uuid.UUID,
        workspace_id: uuid.UUID,
        key_reference: KeyReference,
    ) -> bytes:
        return (
            f"atlas-backup-v1:{backup_id}:{workspace_id}:"
            f"{key_reference.resource}:{key_reference.version}"
        ).encode()
