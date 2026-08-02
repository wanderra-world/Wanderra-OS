"""Typed H3-03 contracts for document custody and governed derivation."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class CustodyError(ValueError):
    """Raised when custody, lineage, or governance would be weakened."""


class DocumentAuthorizationError(PermissionError):
    """Raised before unauthorized document access or mutation."""


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class MalwareVerdict(StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    ERROR = "error"


class CustodyStatus(StrEnum):
    QUARANTINED = "quarantined"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DELETED = "deleted"


class DeletionDisposition(StrEnum):
    BLOCKED_LEGAL_HOLD = "legal_hold"
    BLOCKED_RETENTION = "retention"
    ELIGIBLE = "eligible"


_CLASSIFICATION_RANK = {
    Classification.PUBLIC: 0,
    Classification.INTERNAL: 1,
    Classification.CONFIDENTIAL: 2,
    Classification.RESTRICTED: 3,
}


def _reference(value: str, name: str, limit: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise CustodyError(f"{name} is invalid")
    return normalized


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CustodyError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class DocumentCreate:
    document_id: uuid.UUID
    resource_id: uuid.UUID
    title: str
    classification: Classification
    classification_policy_version: int
    legal_hold: bool = False
    retain_until: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _reference(self.title, "document title", 512))
        object.__setattr__(self, "classification", Classification(self.classification))
        if self.classification_policy_version < 1:
            raise CustodyError("classification policy version must be positive")
        if self.retain_until is not None:
            _aware(self.retain_until, "retain_until")


@dataclass(frozen=True, slots=True)
class DocumentVersionCreate:
    version_id: uuid.UUID
    document_id: uuid.UUID
    content: bytes = field(repr=False)
    expected_sha256: str
    media_type: str
    classification: Classification
    classification_policy_version: int
    encryption_key_version: int
    source_external_reference_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not self.content:
            raise CustodyError("document content is empty")
        if len(self.content) > 52_428_800:
            raise CustodyError("document content exceeds the custody limit")
        object.__setattr__(self, "media_type", _reference(self.media_type, "media type", 255))
        object.__setattr__(self, "classification", Classification(self.classification))
        digest = hashlib.sha256(self.content).hexdigest()
        if self.expected_sha256 != digest:
            raise CustodyError("content hash does not match expected hash")
        if self.classification_policy_version < 1 or self.encryption_key_version < 1:
            raise CustodyError("policy and encryption key versions must be positive")

    @property
    def sha256(self) -> str:
        return self.expected_sha256

    @property
    def size_bytes(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    content_hash: str
    malware_verdict: MalwareVerdict
    media_type_verified: bool
    verified_at: datetime
    verifier_version: str

    def __post_init__(self) -> None:
        if len(self.content_hash) != 64:
            raise CustodyError("verification hash is invalid")
        object.__setattr__(self, "malware_verdict", MalwareVerdict(self.malware_verdict))
        _aware(self.verified_at, "verified_at")
        object.__setattr__(
            self,
            "verifier_version",
            _reference(self.verifier_version, "verifier version", 128),
        )


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    derivative_id: uuid.UUID
    version_id: uuid.UUID
    processor_key: str
    processor_version: str
    classification: Classification
    policy_version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "processor_key", _reference(self.processor_key, "processor", 96))
        object.__setattr__(
            self,
            "processor_version",
            _reference(self.processor_version, "processor version", 64),
        )
        object.__setattr__(self, "classification", Classification(self.classification))
        if self.policy_version < 1:
            raise CustodyError("derivative policy version must be positive")


@dataclass(frozen=True, slots=True)
class ChunkSpec:
    chunk_id: uuid.UUID
    source_version_id: uuid.UUID
    derivative_id: uuid.UUID
    position: int
    text: str = field(repr=False)
    content_hash: str
    classification: Classification
    policy_version: int


class ObjectStoragePort(Protocol):
    async def put_quarantined(self, key: str, content: bytes) -> None: ...
    async def promote(self, quarantine_key: str, object_key: str) -> None: ...
    async def read(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class ContentVerifierPort(Protocol):
    async def verify(self, content: bytes, media_type: str) -> VerificationEvidence: ...


class ExtractorPort(Protocol):
    async def extract(self, content: bytes, media_type: str) -> tuple[str, ...]: ...


class ExtractionJobPort(Protocol):
    async def enqueue_extraction(self, version_id: uuid.UUID, input_digest: str) -> uuid.UUID: ...


class DeletionJobPort(Protocol):
    async def enqueue_deletion(
        self, deletion_id: uuid.UUID, document_id: uuid.UUID
    ) -> uuid.UUID: ...


def require_extractable(evidence: VerificationEvidence, *, expected_hash: str) -> None:
    if evidence.content_hash != expected_hash:
        raise CustodyError("verification hash does not match custody hash")
    if evidence.malware_verdict is not MalwareVerdict.CLEAN:
        raise CustodyError("content is not malware-clean")
    if not evidence.media_type_verified:
        raise CustodyError("content type is not verified")


def require_derivative_classification(
    *, source: Classification | str, derivative: Classification | str
) -> None:
    source_value = Classification(source)
    derivative_value = Classification(derivative)
    if _CLASSIFICATION_RANK[derivative_value] < _CLASSIFICATION_RANK[source_value]:
        raise CustodyError("derivative classification downgrade is prohibited")


def derivative_digest(
    *, source_hash: str, processor_key: str, processor_version: str, policy_version: int
) -> str:
    payload = json.dumps(
        {
            "source_hash": source_hash,
            "processor_key": processor_key,
            "processor_version": processor_version,
            "policy_version": policy_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def build_chunks(
    *,
    source_version_id: uuid.UUID,
    derivative_id: uuid.UUID,
    texts: tuple[str, ...],
    classification: Classification,
    policy_version: int,
) -> tuple[ChunkSpec, ...]:
    chunks: list[ChunkSpec] = []
    for position, text in enumerate(texts):
        normalized = text.strip()
        if not normalized:
            continue
        chunks.append(
            ChunkSpec(
                chunk_id=uuid.uuid5(derivative_id, f"chunk:{position}"),
                source_version_id=source_version_id,
                derivative_id=derivative_id,
                position=position,
                text=normalized,
                content_hash=hashlib.sha256(normalized.encode()).hexdigest(),
                classification=classification,
                policy_version=policy_version,
            )
        )
    return tuple(chunks)


def deletion_disposition(
    *, now: datetime, legal_hold: bool, retain_until: datetime | None
) -> DeletionDisposition:
    _aware(now, "now")
    if legal_hold:
        return DeletionDisposition.BLOCKED_LEGAL_HOLD
    if retain_until is not None and _aware(retain_until, "retain_until") > now:
        return DeletionDisposition.BLOCKED_RETENTION
    return DeletionDisposition.ELIGIBLE
