"""Provider-neutral contracts and deterministic policies for H3-06."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class SearchError(ValueError):
    pass


class SearchAuthorizationError(PermissionError):
    pass


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ModelRoute(StrEnum):
    NONE = "none"
    PUBLIC = "public"
    PRIVATE = "private"


class SourceKind(StrEnum):
    RESOURCE = "resource"
    DOCUMENT_VERSION = "document_version"
    DOCUMENT_CHUNK = "document_chunk"
    KNOWLEDGE_CLAIM = "knowledge_claim"
    MEMORY_ITEM = "memory_item"


@dataclass(frozen=True)
class SearchDocumentInput:
    source_kind: SourceKind | str
    source_id: uuid.UUID
    source_version: int
    source_digest: str
    title: str
    content: str
    classification: Classification
    visibility: str
    policy_version: int
    resource_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    chunker_version: str = "none"

    def __post_init__(self) -> None:
        if self.source_version < 1 or self.policy_version < 1:
            raise ValueError("source and policy versions must be positive")
        if len(self.source_digest) != 64:
            raise ValueError("source digest must be SHA-256")
        if self.visibility not in {"private", "workspace", "restricted"}:
            raise ValueError("unsupported visibility")

    def identity_digest(self) -> str:
        payload = {
            "chunker_version": self.chunker_version,
            "classification": self.classification.value,
            "content": self.content,
            "policy_version": self.policy_version,
            "source_digest": self.source_digest,
            "source_id": str(self.source_id),
            "source_kind": str(self.source_kind),
            "source_version": self.source_version,
            "title": self.title,
            "visibility": self.visibility,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class SearchQuery:
    text: str
    limit: int = 10
    source_kinds: frozenset[SourceKind] = frozenset()
    classifications: frozenset[Classification] = frozenset()
    resource_ids: frozenset[uuid.UUID] = frozenset()
    graph_root_id: uuid.UUID | None = None
    graph_depth: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("search limit must be between 1 and 100")
        if not 0 <= self.graph_depth <= 2:
            raise ValueError("graph expansion depth must be between 0 and 2")


class EmbeddingPort(Protocol):
    model_key: str
    model_version: str
    dimensions: int

    async def embed(self, text: str) -> Sequence[float]: ...


@dataclass(frozen=True)
class Citation:
    source_id: uuid.UUID
    source_version: int
    source_digest: str
    policy_version: int
    index_version: str


@dataclass(frozen=True)
class ContextFragment:
    document_id: uuid.UUID
    content: str
    citation: Citation
    classification: Classification
    untrusted: bool = True


@dataclass(frozen=True)
class ContextPolicy:
    max_tokens: int = 8192
    max_fragments: int = 20
    model_route: ModelRoute = ModelRoute.NONE

    def __post_init__(self) -> None:
        if not 1 <= self.max_tokens <= 8192 or not 1 <= self.max_fragments <= 20:
            raise ValueError("context budget exceeds the approved H3-06 maximum")


@dataclass(frozen=True)
class AssembledContext:
    fragments: tuple[ContextFragment, ...]
    classification: Classification
    token_count: int
    truncated: bool


def reciprocal_rank_fusion(
    *, lexical: Sequence[uuid.UUID], vector: Sequence[uuid.UUID], exact_ids: frozenset[uuid.UUID]
) -> tuple[tuple[uuid.UUID, float], ...]:
    scores: dict[uuid.UUID, float] = {}
    for values in (lexical, vector):
        for rank, item_id in enumerate(values, 1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (60 + rank)
    for item_id in exact_ids:
        scores[item_id] = scores.get(item_id, 0.0) + 1.0
    return tuple(sorted(scores.items(), key=lambda item: (-item[1], str(item[0]))))


def assemble_context(
    *, results: Sequence[Mapping[str, object]], policy: ContextPolicy
) -> AssembledContext:
    order = list(Classification)
    fragments: list[ContextFragment] = []
    used = 0
    truncated = False
    effective = Classification.PUBLIC
    for result in results:
        if len(fragments) >= policy.max_fragments:
            truncated = True
            break
        classification = Classification(str(result["classification"]))
        effective = max((effective, classification), key=order.index)
        content = str(result["content"])
        tokens = max(1, (len(content) + 3) // 4)
        if used + tokens > policy.max_tokens:
            truncated = True
            continue
        fragments.append(
            ContextFragment(
                document_id=uuid.UUID(str(result["document_id"])),
                content=content,
                citation=Citation(
                    source_id=uuid.UUID(str(result["source_id"])),
                    source_version=int(result["source_version"]),
                    source_digest=str(result["source_digest"]),
                    policy_version=int(result["policy_version"]),
                    index_version=str(result["index_version"]),
                ),
                classification=classification,
            )
        )
        used += tokens
    if effective is Classification.RESTRICTED and policy.model_route is not ModelRoute.PRIVATE:
        raise SearchError("restricted context requires the private model route")
    return AssembledContext(tuple(fragments), effective, used, truncated)
