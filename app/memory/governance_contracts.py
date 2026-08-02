"""Typed deterministic H3-05 governed-memory contracts."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.documents.contracts import Classification


class MemoryError(ValueError):
    """Raised when memory provenance or lifecycle governance would be weakened."""


class MemoryAuthorizationError(PermissionError):
    """Raised before unauthorized governed-memory access."""


class MemoryKind(StrEnum):
    PREFERENCE = "preference"
    DECISION = "decision"
    SUMMARY = "summary"
    WORKING_FACT = "working_fact"


class MemorySourceKind(StrEnum):
    DOCUMENT_VERSION = "document_version"
    KNOWLEDGE_CLAIM = "knowledge_claim"
    RESOURCE = "resource"
    MEMORY_ITEM = "memory_item"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    DELETED = "deleted"


class MemoryVisibility(StrEnum):
    PRIVATE = "private"
    WORKSPACE = "workspace"
    RESTRICTED = "restricted"


class MemoryFeedbackKind(StrEnum):
    HELPFUL = "helpful"
    INCORRECT = "incorrect"
    OUTDATED = "outdated"
    SENSITIVE = "sensitive"


class ModelRoute(StrEnum):
    STANDARD = "standard"
    PRIVATE = "private"


_CLASSIFICATION_RANK = {
    Classification.PUBLIC: 0,
    Classification.INTERNAL: 1,
    Classification.CONFIDENTIAL: 2,
    Classification.RESTRICTED: 3,
}


def _reference(value: str, name: str, limit: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise MemoryError(f"{name} is invalid")
    return normalized


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MemoryError(f"{name} must be timezone-aware")
    return value


def effective_classification(values: Iterable[Classification]) -> Classification:
    items = tuple(Classification(value) for value in values)
    if not items:
        raise MemoryError("at least one source classification is required")
    return max(items, key=_CLASSIFICATION_RANK.__getitem__)


@dataclass(frozen=True, slots=True)
class MemorySource:
    source_id: uuid.UUID
    source_kind: MemorySourceKind
    source_version: int
    source_digest: str
    classification: Classification
    policy_version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", MemorySourceKind(self.source_kind))
        object.__setattr__(self, "classification", Classification(self.classification))
        if self.source_version < 1 or self.policy_version < 1:
            raise MemoryError("source versions must be positive")
        if len(self.source_digest) != 64:
            raise MemoryError("source digest is invalid")


@dataclass(frozen=True, slots=True)
class MemoryCreate:
    memory_id: uuid.UUID
    memory_kind: MemoryKind
    content: str = field(repr=False)
    subject_resource_id: uuid.UUID | None
    owner_user_id: uuid.UUID
    visibility: MemoryVisibility
    confidence: float
    classification: Classification
    policy_version: int
    creation_method: str
    expires_at: datetime | None
    sources: tuple[MemorySource, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_kind", MemoryKind(self.memory_kind))
        object.__setattr__(self, "content", _reference(self.content, "memory content", 4096))
        object.__setattr__(self, "visibility", MemoryVisibility(self.visibility))
        object.__setattr__(self, "classification", Classification(self.classification))
        object.__setattr__(
            self, "creation_method", _reference(self.creation_method, "creation method", 64)
        )
        if not self.sources:
            raise MemoryError("memory requires at least one source")
        if len({(item.source_kind, item.source_id) for item in self.sources}) != len(self.sources):
            raise MemoryError("memory sources must be distinct")
        if not 0 <= self.confidence <= 1:
            raise MemoryError("memory confidence must be between zero and one")
        if self.policy_version < 1:
            raise MemoryError("policy version must be positive")
        if self.expires_at is not None:
            _aware(self.expires_at, "expires_at")
        source_classification = effective_classification(
            item.classification for item in self.sources
        )
        if _CLASSIFICATION_RANK[self.classification] < _CLASSIFICATION_RANK[source_classification]:
            raise MemoryError("memory classification downgrade is prohibited")

    @property
    def identity_digest(self) -> str:
        payload = {
            "kind": self.memory_kind.value,
            "content": self.content,
            "subject_resource_id": str(self.subject_resource_id)
            if self.subject_resource_id
            else None,
            "owner_user_id": str(self.owner_user_id),
            "visibility": self.visibility.value,
            "confidence_basis_points": round(self.confidence * 10000),
            "classification": self.classification.value,
            "policy_version": self.policy_version,
            "creation_method": self.creation_method,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "sources": sorted(
                (
                    {
                        "kind": item.source_kind.value,
                        "id": str(item.source_id),
                        "version": item.source_version,
                        "digest": item.source_digest,
                        "classification": item.classification.value,
                        "policy_version": item.policy_version,
                    }
                    for item in self.sources
                ),
                key=lambda value: json.dumps(value, sort_keys=True),
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsolidationCreate:
    memory_id: uuid.UUID
    input_memory_ids: tuple[uuid.UUID, ...]
    processor_key: str
    processor_version: str
    policy_version: int

    def __post_init__(self) -> None:
        if len(self.input_memory_ids) < 2 or len(set(self.input_memory_ids)) != len(
            self.input_memory_ids
        ):
            raise MemoryError("consolidation requires at least two distinct inputs")
        object.__setattr__(self, "input_memory_ids", tuple(sorted(self.input_memory_ids)))
        object.__setattr__(self, "processor_key", _reference(self.processor_key, "processor", 96))
        object.__setattr__(
            self,
            "processor_version",
            _reference(self.processor_version, "processor version", 64),
        )
        if self.policy_version < 1:
            raise MemoryError("policy version must be positive")

    @property
    def input_digest(self) -> str:
        payload = {
            "inputs": [str(value) for value in self.input_memory_ids],
            "processor_key": self.processor_key,
            "processor_version": self.processor_version,
            "policy_version": self.policy_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryFeedbackCreate:
    feedback_id: uuid.UUID
    memory_id: uuid.UUID
    kind: MemoryFeedbackKind
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", MemoryFeedbackKind(self.kind))
        object.__setattr__(self, "reason", _reference(self.reason, "feedback reason", 512))


def evaluate_status(
    status: MemoryStatus,
    expires_at: datetime | None,
    pinned: bool,
    now: datetime,
) -> MemoryStatus:
    current = MemoryStatus(status)
    _aware(now, "now")
    if expires_at is not None:
        _aware(expires_at, "expires_at")
    if current is not MemoryStatus.ACTIVE:
        return current
    if expires_at is not None and now >= expires_at and not pinned:
        return MemoryStatus.EXPIRED
    return current


def require_model_egress(classification: Classification, route: ModelRoute) -> None:
    value = Classification(classification)
    selected = ModelRoute(route)
    if value is Classification.RESTRICTED and selected is not ModelRoute.PRIVATE:
        raise MemoryError("memory egress route is not permitted")


def versioned_source_digest(kind: MemorySourceKind, source_id: uuid.UUID, version: int) -> str:
    if version < 1:
        raise MemoryError("source version must be positive")
    return hashlib.sha256(
        f"{MemorySourceKind(kind).value}:{source_id}:{version}".encode()
    ).hexdigest()
