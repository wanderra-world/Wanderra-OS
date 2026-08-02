"""Typed deterministic H3-04 knowledge and timeline contracts."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.documents.contracts import Classification


class KnowledgeError(ValueError):
    """Raised when provenance, typing, or projection integrity would be weakened."""


class KnowledgeAuthorizationError(PermissionError):
    """Raised before unauthorized knowledge or timeline access."""


class ClaimValueType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    INSTANT = "instant"
    UUID = "uuid"


class ClaimStatus(StrEnum):
    ACTIVE = "active"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class ReviewState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


_PREDICATE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_CLASSIFICATION_RANK = {
    Classification.PUBLIC: 0,
    Classification.INTERNAL: 1,
    Classification.CONFIDENTIAL: 2,
    Classification.RESTRICTED: 3,
}


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise KnowledgeError(f"{name} must be timezone-aware")
    return value


def _reference(value: str, name: str, limit: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise KnowledgeError(f"{name} is invalid")
    return normalized


def canonical_value(value_type: ClaimValueType, value: object) -> str:
    kind = ClaimValueType(value_type)
    if kind is ClaimValueType.TEXT:
        if not isinstance(value, str):
            raise KnowledgeError("text claim value must be a string")
        return _reference(value, "claim value", 4096)
    if kind is ClaimValueType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise KnowledgeError("integer claim value is invalid")
        return str(value)
    if kind is ClaimValueType.DECIMAL:
        if isinstance(value, bool):
            raise KnowledgeError("decimal claim value is invalid")
        try:
            decimal = Decimal(str(value))
        except Exception as exc:
            raise KnowledgeError("decimal claim value is invalid") from exc
        if not decimal.is_finite():
            raise KnowledgeError("decimal claim value must be finite")
        return format(decimal.normalize(), "f")
    if kind is ClaimValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise KnowledgeError("boolean claim value is invalid")
        return "true" if value else "false"
    if kind is ClaimValueType.INSTANT:
        if not isinstance(value, datetime):
            raise KnowledgeError("instant claim value is invalid")
        return _aware(value, "claim instant").isoformat()
    if kind is ClaimValueType.UUID:
        try:
            return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
        except ValueError as exc:
            raise KnowledgeError("UUID claim value is invalid") from exc
    raise KnowledgeError("unsupported claim value type")


def canonical_claim_digest(
    *,
    subject_resource_id: uuid.UUID,
    predicate: str,
    value_type: ClaimValueType,
    canonical_value: str,
) -> str:
    payload = json.dumps(
        {
            "subject_resource_id": str(subject_resource_id),
            "predicate": predicate,
            "value_type": ClaimValueType(value_type).value,
            "value": canonical_value,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ClaimCreate:
    claim_id: uuid.UUID
    subject_resource_id: uuid.UUID
    predicate: str
    value_type: ClaimValueType
    value: object = field(repr=False)
    confidence: float
    extractor_key: str
    extractor_version: str
    classification: Classification
    policy_version: int
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        predicate = self.predicate.strip()
        if not _PREDICATE.fullmatch(predicate):
            raise KnowledgeError("claim predicate is invalid")
        object.__setattr__(self, "predicate", predicate)
        object.__setattr__(self, "value_type", ClaimValueType(self.value_type))
        object.__setattr__(self, "classification", Classification(self.classification))
        if not 0 <= self.confidence <= 1:
            raise KnowledgeError("claim confidence must be between zero and one")
        object.__setattr__(self, "extractor_key", _reference(self.extractor_key, "extractor", 96))
        object.__setattr__(
            self, "extractor_version", _reference(self.extractor_version, "extractor version", 64)
        )
        if self.policy_version < 1:
            raise KnowledgeError("policy version must be positive")
        if self.valid_from is not None:
            _aware(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _aware(self.valid_to, "valid_to")
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to <= self.valid_from:
                raise KnowledgeError("claim validity interval is invalid")
        canonical_value(self.value_type, self.value)

    @property
    def canonical_value(self) -> str:
        return canonical_value(self.value_type, self.value)

    @property
    def identity_digest(self) -> str:
        return canonical_claim_digest(
            subject_resource_id=self.subject_resource_id,
            predicate=self.predicate,
            value_type=self.value_type,
            canonical_value=self.canonical_value,
        )

    def derivation_digest(self, evidence: tuple[ClaimEvidence, ...]) -> str:
        if not evidence:
            raise KnowledgeError("a knowledge claim requires evidence")
        payload = {
            "identity_digest": self.identity_digest,
            "extractor_key": self.extractor_key,
            "extractor_version": self.extractor_version,
            "policy_version": self.policy_version,
            "evidence": sorted(
                (
                    {
                        "source_version_id": str(item.source_version_id),
                        "source_chunk_id": str(item.source_chunk_id)
                        if item.source_chunk_id
                        else None,
                        "source_hash": item.source_hash,
                        "span_start": item.span_start,
                        "span_end": item.span_end,
                        "classification": item.classification.value,
                        "policy_version": item.policy_version,
                    }
                    for item in evidence
                ),
                key=lambda item: json.dumps(item, sort_keys=True),
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    evidence_id: uuid.UUID
    source_version_id: uuid.UUID
    source_chunk_id: uuid.UUID | None
    source_hash: str
    span_start: int
    span_end: int
    classification: Classification
    policy_version: int

    def __post_init__(self) -> None:
        if len(self.source_hash) != 64:
            raise KnowledgeError("source hash is invalid")
        if self.span_start < 0 or self.span_end <= self.span_start:
            raise KnowledgeError("source span is invalid")
        object.__setattr__(self, "classification", Classification(self.classification))
        if self.policy_version < 1:
            raise KnowledgeError("evidence policy version must be positive")


@dataclass(frozen=True, slots=True)
class ContradictionCreate:
    relation_id: uuid.UUID
    claim_id: uuid.UUID
    conflicting_claim_id: uuid.UUID
    relation_type: str
    reason: str

    def __post_init__(self) -> None:
        if self.claim_id == self.conflicting_claim_id:
            raise KnowledgeError("a claim cannot conflict with itself")
        if self.relation_type not in {"contradicts", "supersedes"}:
            raise KnowledgeError("claim relation type is invalid")
        object.__setattr__(self, "reason", _reference(self.reason, "relation reason", 256))


@dataclass(frozen=True, slots=True)
class TimelineInput:
    source_event_id: uuid.UUID
    source_event_type: str
    source_sequence: int
    occurred_at: datetime
    resource_id: uuid.UUID | None
    source_claim_id: uuid.UUID | None
    title: str
    visibility: str
    classification: Classification
    policy_version: int

    def __post_init__(self) -> None:
        event_type = _reference(self.source_event_type, "source event type", 128)
        if event_type.startswith("audit."):
            raise KnowledgeError("audit events cannot be timeline projection storage")
        object.__setattr__(self, "source_event_type", event_type)
        if self.source_sequence < 1:
            raise KnowledgeError("source sequence must be positive")
        _aware(self.occurred_at, "occurred_at")
        object.__setattr__(self, "title", _reference(self.title, "timeline title", 512))
        if self.visibility not in {"workspace", "restricted"}:
            raise KnowledgeError("timeline visibility is invalid")
        object.__setattr__(self, "classification", Classification(self.classification))
        if self.policy_version < 1:
            raise KnowledgeError("timeline policy version must be positive")


def effective_classification(values: Iterable[Classification]) -> Classification:
    classifications = tuple(Classification(value) for value in values)
    if not classifications:
        raise KnowledgeError("at least one source classification is required")
    return max(classifications, key=_CLASSIFICATION_RANK.__getitem__)


def rebuild_timeline(values: Iterable[TimelineInput]) -> tuple[TimelineInput, ...]:
    by_source: dict[uuid.UUID, TimelineInput] = {}
    for value in values:
        prior = by_source.get(value.source_event_id)
        if prior is not None and prior != value:
            raise KnowledgeError("timeline source replay changed input")
        by_source[value.source_event_id] = value
    return tuple(
        sorted(
            by_source.values(),
            key=lambda value: (value.occurred_at, value.source_sequence, value.source_event_id),
        )
    )


def checkpoint_digest(values: Iterable[TimelineInput]) -> str:
    ordered = rebuild_timeline(values)
    payload = [
        {
            "source_event_id": str(value.source_event_id),
            "source_event_type": value.source_event_type,
            "source_sequence": value.source_sequence,
            "occurred_at": value.occurred_at.isoformat(),
            "resource_id": str(value.resource_id) if value.resource_id else None,
            "source_claim_id": str(value.source_claim_id) if value.source_claim_id else None,
            "title": value.title,
            "visibility": value.visibility,
            "classification": value.classification.value,
            "policy_version": value.policy_version,
        }
        for value in ordered
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
