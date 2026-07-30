"""Immutable contracts for H1-09 recovery and closure evidence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.encryption import KeyReference


class ClosureState(StrEnum):
    WRITES_FROZEN = "writes_frozen"
    RETENTION_BLOCKED = "retention_blocked"
    ERASING = "erasing"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorkspaceManifest:
    workspace_id: uuid.UUID
    schema_version: int
    created_at: datetime
    table_counts: dict[str, int]
    table_digests: dict[str, str]
    provider_reconciliation_required: bool = True


@dataclass(frozen=True, slots=True)
class BackupSnapshot:
    payload: bytes
    source_snapshot_at: datetime
    manifest: WorkspaceManifest


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    backup_id: uuid.UUID
    workspace_id: uuid.UUID
    ciphertext: bytes
    nonce: bytes
    wrapped_key: bytes
    key_reference: KeyReference
    checksum: str
    source_snapshot_at: datetime
    completed_at: datetime
    manifest: WorkspaceManifest


@dataclass(frozen=True, slots=True)
class RestoreEvidence:
    backup_id: uuid.UUID
    workspace_id: uuid.UUID
    restored_at: datetime
    recovery_point_seconds: int
    recovery_time_seconds: int
    counts_verified: bool
    digests_verified: bool
    rpo_met: bool
    rto_met: bool
    isolated_target: str


@dataclass(frozen=True, slots=True)
class ClosureResult:
    closure_id: uuid.UUID
    workspace_id: uuid.UUID
    state: ClosureState
    receipt_digest: str | None
    replayed: bool
    blocked_reason: str | None = None
