"""Disposable H0 prototype for document object custody."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4


class CustodyError(ValueError):
    """Raised when a document custody invariant would be violated."""


class CustodyState(StrEnum):
    QUARANTINED = "quarantined"
    READABLE = "readable"
    REJECTED = "rejected"
    DELETED = "deleted"


class ScanResult(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StorageConfiguration:
    """Security properties required from the environment-selected storage port."""

    tls_enabled: bool
    managed_encryption: bool
    public_access: bool
    region: str
    backup_enabled: bool

    def validate(self) -> None:
        if not self.tls_enabled:
            raise CustodyError("object storage requires TLS")
        if not self.managed_encryption:
            raise CustodyError("object storage requires managed encryption")
        if self.public_access:
            raise CustodyError("public object storage is prohibited")
        if not self.region.strip():
            raise CustodyError("object storage region is required")
        if not self.backup_enabled:
            raise CustodyError("object storage backup policy is required")


class ObjectStoragePort(Protocol):
    """Provider-neutral object-storage boundary used by the custody service."""

    def put_immutable(self, key: str, content: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


class InMemoryObjectStorage:
    """Private test adapter with immutable object semantics."""

    def __init__(self, configuration: StorageConfiguration) -> None:
        configuration.validate()
        self.configuration = configuration
        self._objects: dict[str, bytes] = {}

    def put_immutable(self, key: str, content: bytes) -> None:
        if key in self._objects:
            if self._objects[key] != content:
                raise CustodyError("immutable object cannot be overwritten")
            return
        self._objects[key] = content

    def get(self, key: str) -> bytes:
        try:
            return self._objects[key]
        except KeyError as error:
            raise CustodyError("object is unavailable") from error

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def contains(self, key: str) -> bool:
        return key in self._objects


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    """Metadata and custody state; ordinary document content remains outside SQL."""

    id: UUID
    workspace_id: UUID
    object_key: str
    content_hash: str
    declared_mime: str
    created_at: datetime
    state: CustodyState
    detected_mime: str | None = None
    scanned_at: datetime | None = None
    promoted_at: datetime | None = None
    legal_hold: bool = False
    retain_until: datetime | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SignedAccess:
    """Short-lived access issued only after authorization."""

    url: str
    expires_at: datetime


class DocumentCustody:
    """Quarantine-first lifecycle over a provider-neutral storage port."""

    MAXIMUM_SIGNED_ACCESS = timedelta(minutes=5)
    ALLOWED_MIME_TYPES = frozenset(
        {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
        }
    )

    def __init__(
        self,
        *,
        workspace_id: UUID,
        storage: ObjectStoragePort,
        tenant_partition: str | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self._storage = storage
        self._tenant_partition = tenant_partition or secrets.token_urlsafe(24)
        self._versions: dict[UUID, DocumentVersion] = {}

    def quarantine(
        self,
        content: bytes,
        *,
        declared_mime: str,
        expected_hash: str,
        now: datetime,
    ) -> DocumentVersion:
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            raise CustodyError("uploaded content hash does not match")
        if declared_mime not in self.ALLOWED_MIME_TYPES:
            raise CustodyError("declared MIME type is not allowed")

        version_id = uuid4()
        object_key = f"tenant/{self._tenant_partition}/{actual_hash}"
        self._storage.put_immutable(object_key, content)
        version = DocumentVersion(
            id=version_id,
            workspace_id=self.workspace_id,
            object_key=object_key,
            content_hash=actual_hash,
            declared_mime=declared_mime,
            created_at=now,
            state=CustodyState.QUARANTINED,
        )
        self._versions[version_id] = version
        return version

    def promote(
        self,
        version_id: UUID,
        *,
        detected_mime: str,
        scan_result: ScanResult,
        now: datetime,
        metadata_commit_succeeds: bool = True,
    ) -> DocumentVersion:
        version = self._current(version_id)
        if version.state is not CustodyState.QUARANTINED:
            raise CustodyError("only quarantined content can be promoted")
        if scan_result is not ScanResult.CLEAN:
            rejected = replace(
                version,
                state=CustodyState.REJECTED,
                detected_mime=detected_mime,
                scanned_at=now,
            )
            self._versions[version_id] = rejected
            raise CustodyError("document did not pass malware scanning")
        if detected_mime != version.declared_mime:
            raise CustodyError("detected MIME type does not match declaration")
        content = self._storage.get(version.object_key)
        if hashlib.sha256(content).hexdigest() != version.content_hash:
            raise CustodyError("stored content hash verification failed")
        if not metadata_commit_succeeds:
            raise CustodyError("metadata promotion transaction failed")

        readable = replace(
            version,
            state=CustodyState.READABLE,
            detected_mime=detected_mime,
            scanned_at=now,
            promoted_at=now,
        )
        self._versions[version_id] = readable
        return readable

    def read(self, version_id: UUID, *, authorized: bool) -> bytes:
        version = self._current(version_id)
        if not authorized:
            raise CustodyError("document access is not authorized")
        if version.state is not CustodyState.READABLE:
            raise CustodyError("document version is not readable")
        return self._storage.get(version.object_key)

    def issue_signed_access(
        self,
        version_id: UUID,
        *,
        authorized: bool,
        now: datetime,
        ttl: timedelta,
    ) -> SignedAccess:
        self.read(version_id, authorized=authorized)
        if ttl <= timedelta(0) or ttl > self.MAXIMUM_SIGNED_ACCESS:
            raise CustodyError("signed access must be short-lived")
        token = secrets.token_urlsafe(24)
        return SignedAccess(
            url=f"https://objects.invalid/private/{token}",
            expires_at=now + ttl,
        )

    def set_governance(
        self,
        version_id: UUID,
        *,
        legal_hold: bool,
        retain_until: datetime | None,
    ) -> DocumentVersion:
        governed = replace(
            self._current(version_id),
            legal_hold=legal_hold,
            retain_until=retain_until,
        )
        self._versions[version_id] = governed
        return governed

    def delete(self, version_id: UUID, *, now: datetime) -> DocumentVersion:
        version = self._current(version_id)
        if version.legal_hold:
            raise CustodyError("legal hold prevents deletion")
        if version.retain_until is not None and now < version.retain_until:
            raise CustodyError("retention policy prevents deletion")
        deleted = replace(
            version,
            state=CustodyState.DELETED,
            deleted_at=now,
        )
        self._versions[version_id] = deleted
        self._delete_if_unreferenced(version.object_key)
        return deleted

    def expire_quarantine(
        self,
        *,
        now: datetime,
        maximum_age: timedelta,
    ) -> tuple[UUID, ...]:
        expired: list[UUID] = []
        for version_id, version in tuple(self._versions.items()):
            if (
                version.state in {CustodyState.QUARANTINED, CustodyState.REJECTED}
                and now - version.created_at >= maximum_age
            ):
                self._versions[version_id] = replace(
                    version,
                    state=CustodyState.DELETED,
                    deleted_at=now,
                )
                self._delete_if_unreferenced(version.object_key)
                expired.append(version_id)
        return tuple(expired)

    def current(self, version_id: UUID) -> DocumentVersion:
        return self._current(version_id)

    def _current(self, version_id: UUID) -> DocumentVersion:
        try:
            return self._versions[version_id]
        except KeyError as error:
            raise CustodyError("document version does not exist") from error

    def _delete_if_unreferenced(self, object_key: str) -> None:
        if any(
            version.object_key == object_key
            and version.state is not CustodyState.DELETED
            for version in self._versions.values()
        ):
            return
        self._storage.delete(object_key)
