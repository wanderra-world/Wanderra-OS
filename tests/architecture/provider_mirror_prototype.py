"""Disposable H0 prototype for provider mirrors, authority, and conflicts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ProviderMirrorError(ValueError):
    """Raised when provider synchronization would violate an H0 invariant."""


class ProviderPreconditionFailed(ProviderMirrorError):
    """Raised when an external resource changed before an Atlas write."""


class AuthorityPolicy(StrEnum):
    PROVIDER_AUTHORITATIVE = "provider_authoritative"
    ATLAS_AUTHORITATIVE = "atlas_authoritative"
    USER_RESOLVED = "user_resolved"
    MERGEABLE = "mergeable"


class SyncState(StrEnum):
    SYNCED = "synced"
    CONFLICT = "conflict"
    TOMBSTONED = "tombstoned"
    DELETED = "deleted"


class ConflictReason(StrEnum):
    AMBIGUOUS_INBOUND = "ambiguous_inbound"
    PROVIDER_VERSION_REUSED = "provider_version_reused"
    PRECONDITION_FAILED = "precondition_failed"
    POST_WRITE_VERIFICATION_FAILED = "post_write_verification_failed"


@dataclass(frozen=True, slots=True)
class Conflict:
    reason: ConflictReason
    atlas_hash: str
    provider_hash: str
    detected_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderMirror:
    id: UUID
    workspace_id: UUID
    connection_id: UUID
    resource_type: str
    external_id: str
    canonical_reference: UUID | None
    provider_version: str
    provider_updated_at: datetime
    normalized_hash: str
    raw_payload_reference: str
    authority: AuthorityPolicy
    sync_state: SyncState
    tombstone: bool = False
    conflict: Conflict | None = None

    @property
    def unique_key(self) -> tuple[UUID, UUID, str, str]:
        return (
            self.workspace_id,
            self.connection_id,
            self.resource_type,
            self.external_id,
        )


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    external_id: str
    version: str
    normalized_hash: str
    updated_at: datetime
    raw_payload_reference: str
    deleted: bool = False


class ProviderMirrorStore:
    """In-memory evidence store enforcing the normative provider unique key."""

    def __init__(self) -> None:
        self._mirrors: dict[UUID, ProviderMirror] = {}
        self._keys: dict[tuple[UUID, UUID, str, str], UUID] = {}

    def add(self, mirror: ProviderMirror) -> None:
        if mirror.unique_key in self._keys:
            raise ProviderMirrorError("provider mirror unique key already exists")
        if not mirror.raw_payload_reference.strip():
            raise ProviderMirrorError("governed raw-payload reference is required")
        self._mirrors[mirror.id] = mirror
        self._keys[mirror.unique_key] = mirror.id

    def get(self, mirror_id: UUID) -> ProviderMirror:
        return self._mirrors[mirror_id]

    def save(self, mirror: ProviderMirror) -> None:
        if mirror.id not in self._mirrors:
            raise ProviderMirrorError("provider mirror does not exist")
        self._mirrors[mirror.id] = mirror

    def all(self) -> tuple[ProviderMirror, ...]:
        return tuple(self._mirrors.values())


class ProviderMirrorService:
    """Authority-aware synchronization without destructive last-write-wins."""

    def __init__(
        self,
        store: ProviderMirrorStore,
        provider: MockGoogleProvider,
    ) -> None:
        self._store = store
        self._provider = provider

    def apply_inbound(
        self,
        mirror_id: UUID,
        snapshot: ProviderSnapshot,
        *,
        now: datetime,
        merged_hash: str | None = None,
    ) -> ProviderMirror:
        mirror = self._store.get(mirror_id)
        if snapshot.external_id != mirror.external_id:
            raise ProviderMirrorError("provider external identity does not match")
        if snapshot.deleted:
            tombstone = replace(
                mirror,
                provider_version=snapshot.version,
                provider_updated_at=snapshot.updated_at,
                raw_payload_reference=snapshot.raw_payload_reference,
                sync_state=SyncState.TOMBSTONED,
                tombstone=True,
                conflict=None,
            )
            self._store.save(tombstone)
            return tombstone
        if (
            snapshot.version == mirror.provider_version
            and snapshot.normalized_hash == mirror.normalized_hash
        ):
            return mirror
        if snapshot.version == mirror.provider_version:
            return self._save_conflict(
                mirror,
                snapshot,
                ConflictReason.PROVIDER_VERSION_REUSED,
                now,
            )
        if mirror.authority is AuthorityPolicy.PROVIDER_AUTHORITATIVE:
            synchronized = replace(
                mirror,
                provider_version=snapshot.version,
                provider_updated_at=snapshot.updated_at,
                normalized_hash=snapshot.normalized_hash,
                raw_payload_reference=snapshot.raw_payload_reference,
                sync_state=SyncState.SYNCED,
                conflict=None,
            )
            self._store.save(synchronized)
            return synchronized
        if mirror.authority is AuthorityPolicy.MERGEABLE and merged_hash is not None:
            merged = replace(
                mirror,
                provider_version=snapshot.version,
                provider_updated_at=snapshot.updated_at,
                normalized_hash=merged_hash,
                raw_payload_reference=snapshot.raw_payload_reference,
                sync_state=SyncState.SYNCED,
                conflict=None,
            )
            self._store.save(merged)
            return merged
        return self._save_conflict(
            mirror,
            snapshot,
            ConflictReason.AMBIGUOUS_INBOUND,
            now,
        )

    def promote(
        self,
        mirror_id: UUID,
        *,
        canonical_reference: UUID,
        approved: bool,
    ) -> ProviderMirror:
        if not approved:
            raise ProviderMirrorError("mirror promotion requires approved command")
        promoted = replace(
            self._store.get(mirror_id),
            canonical_reference=canonical_reference,
        )
        self._store.save(promoted)
        return promoted

    def write_outbound(
        self,
        mirror_id: UUID,
        *,
        normalized_hash: str,
        idempotency_key: str,
        now: datetime,
    ) -> ProviderMirror:
        mirror = self._store.get(mirror_id)
        if mirror.authority is AuthorityPolicy.PROVIDER_AUTHORITATIVE:
            raise ProviderMirrorError("provider-authoritative resource rejects Atlas write")
        if not idempotency_key.strip():
            raise ProviderMirrorError("outbound write requires idempotency key")
        try:
            written = self._provider.update(
                mirror.external_id,
                normalized_hash=normalized_hash,
                expected_version=mirror.provider_version,
                idempotency_key=idempotency_key,
                now=now,
            )
        except ProviderPreconditionFailed:
            current = self._provider.fetch(mirror.external_id)
            return self._save_conflict(
                mirror,
                current,
                ConflictReason.PRECONDITION_FAILED,
                now,
                atlas_hash=normalized_hash,
            )

        verified = self._provider.fetch(mirror.external_id)
        if (
            verified.version != written.version
            or verified.normalized_hash != normalized_hash
        ):
            return self._save_conflict(
                mirror,
                verified,
                ConflictReason.POST_WRITE_VERIFICATION_FAILED,
                now,
                atlas_hash=normalized_hash,
            )
        synchronized = replace(
            mirror,
            provider_version=verified.version,
            provider_updated_at=verified.updated_at,
            normalized_hash=normalized_hash,
            raw_payload_reference=verified.raw_payload_reference,
            sync_state=SyncState.SYNCED,
            conflict=None,
        )
        self._store.save(synchronized)
        return synchronized

    def delete_atlas_evidence(
        self,
        mirror_id: UUID,
        *,
        authorized: bool,
        policy_allows: bool,
        provider_action_verified: bool,
    ) -> ProviderMirror:
        if not authorized or not policy_allows or not provider_action_verified:
            raise ProviderMirrorError(
                "Atlas deletion requires authorization, policy, and verification"
            )
        deleted = replace(
            self._store.get(mirror_id),
            canonical_reference=None,
            sync_state=SyncState.DELETED,
        )
        self._store.save(deleted)
        return deleted

    def _save_conflict(
        self,
        mirror: ProviderMirror,
        snapshot: ProviderSnapshot,
        reason: ConflictReason,
        now: datetime,
        *,
        atlas_hash: str | None = None,
    ) -> ProviderMirror:
        conflicted = replace(
            mirror,
            provider_version=snapshot.version,
            provider_updated_at=snapshot.updated_at,
            raw_payload_reference=snapshot.raw_payload_reference,
            sync_state=SyncState.CONFLICT,
            conflict=Conflict(
                reason=reason,
                atlas_hash=atlas_hash or mirror.normalized_hash,
                provider_hash=snapshot.normalized_hash,
                detected_at=now,
            ),
        )
        self._store.save(conflicted)
        return conflicted


class MockGoogleProvider:
    """Google-style version/precondition adapter used only by H0 tests."""

    def __init__(self, snapshots: tuple[ProviderSnapshot, ...]) -> None:
        self._resources = {snapshot.external_id: snapshot for snapshot in snapshots}
        self._outcomes: dict[
            str,
            tuple[tuple[str, str, str], ProviderSnapshot],
        ] = {}
        self.update_calls = 0
        self.drift_after_write = False

    def fetch(self, external_id: str) -> ProviderSnapshot:
        return self._resources[external_id]

    def simulate_external_change(self, snapshot: ProviderSnapshot) -> None:
        if snapshot.external_id not in self._resources:
            raise ProviderMirrorError("provider resource does not exist")
        self._resources[snapshot.external_id] = snapshot

    def update(
        self,
        external_id: str,
        *,
        normalized_hash: str,
        expected_version: str,
        idempotency_key: str,
        now: datetime,
    ) -> ProviderSnapshot:
        request = (external_id, normalized_hash, expected_version)
        prior = self._outcomes.get(idempotency_key)
        if prior is not None:
            if prior[0] != request:
                raise ProviderMirrorError("idempotency key was reused with changed input")
            return prior[1]

        current = self.fetch(external_id)
        if current.version != expected_version:
            raise ProviderPreconditionFailed("provider precondition failed")
        self.update_calls += 1
        version = str(int(current.version) + 1)
        written = replace(
            current,
            version=version,
            normalized_hash=normalized_hash,
            updated_at=now,
            raw_payload_reference=f"raw/{external_id}/{version}",
        )
        self._resources[external_id] = written
        self._outcomes[idempotency_key] = (request, written)
        if self.drift_after_write:
            self._resources[external_id] = replace(
                written,
                version=str(int(version) + 1),
                normalized_hash="concurrent-provider-value",
            )
        return written


def new_mirror(
    snapshot: ProviderSnapshot,
    *,
    authority: AuthorityPolicy,
    workspace_id: UUID | None = None,
    connection_id: UUID | None = None,
) -> ProviderMirror:
    """Create one unpromoted mirror for an inbound provider resource."""

    return ProviderMirror(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        connection_id=connection_id or uuid4(),
        resource_type="file",
        external_id=snapshot.external_id,
        canonical_reference=None,
        provider_version=snapshot.version,
        provider_updated_at=snapshot.updated_at,
        normalized_hash=snapshot.normalized_hash,
        raw_payload_reference=snapshot.raw_payload_reference,
        authority=authority,
        sync_state=SyncState.SYNCED,
    )
