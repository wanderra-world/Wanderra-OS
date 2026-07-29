"""Provider-neutral contracts for Wanderra's memory system."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence


@dataclass(frozen=True)
class UserRecord:
    id: uuid.UUID
    email: str
    display_name: str | None


@dataclass(frozen=True)
class ProjectRecord:
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None


@dataclass(frozen=True)
class ConversationRecord:
    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    title: str | None


@dataclass(frozen=True)
class SearchableConversation:
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    project_id: uuid.UUID | None
    title: str | None
    content: str
    embedding: list[float]
    created_at: datetime


@dataclass(frozen=True)
class ConversationSearchResult:
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    project_id: uuid.UUID | None
    title: str | None
    content: str
    score: float
    created_at: datetime


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class SemanticSearchBackend(Protocol):
    async def search(
        self,
        query_embedding: list[float],
        candidates: Sequence[SearchableConversation],
        limit: int,
    ) -> list[ConversationSearchResult]: ...


class MemoryRepository(Protocol):
    async def create_user(self, email: str, display_name: str | None) -> UserRecord: ...

    async def create_project(
        self, user_id: uuid.UUID, name: str, description: str | None
    ) -> ProjectRecord: ...

    async def create_conversation(
        self, user_id: uuid.UUID, project_id: uuid.UUID | None, title: str | None
    ) -> ConversationRecord: ...

    async def add_message(
        self, conversation_id: uuid.UUID, role: str, content: str, embedding: list[float]
    ) -> None: ...

    async def get_search_candidates(
        self, user_id: uuid.UUID, project_id: uuid.UUID | None
    ) -> list[SearchableConversation]: ...

    async def store_external_message(
        self, user_id: uuid.UUID, source: str, external_id: str, title: str, role: str, content: str, embedding: list[float]
    ) -> None: ...
