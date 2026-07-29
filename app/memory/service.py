"""Application service for creating and retrieving durable Atlas memory."""

import uuid

from app.memory.contracts import (
    ConversationRecord,
    ConversationSearchResult,
    EmbeddingProvider,
    MemoryRepository,
    ProjectRecord,
    SemanticSearchBackend,
    UserRecord,
)


class MemoryService:
    """Stable memory API shared by agents, API routes, and background workers."""

    def __init__(
        self,
        repository: MemoryRepository,
        embedding_provider: EmbeddingProvider,
        search_backend: SemanticSearchBackend,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.search_backend = search_backend

    async def create_user(self, email: str, display_name: str | None = None) -> UserRecord:
        return await self.repository.create_user(email, display_name)

    async def create_project(
        self, user_id: uuid.UUID, name: str, description: str | None = None
    ) -> ProjectRecord:
        return await self.repository.create_project(user_id, name, description)

    async def create_conversation(
        self, user_id: uuid.UUID, project_id: uuid.UUID | None = None, title: str | None = None
    ) -> ConversationRecord:
        return await self.repository.create_conversation(user_id, project_id, title)

    async def store_message(self, conversation_id: uuid.UUID, role: str, content: str) -> None:
        embedding = await self.embedding_provider.embed(content)
        await self.repository.add_message(conversation_id, role, content, embedding)

    async def search_conversations(
        self,
        user_id: uuid.UUID,
        query: str,
        *,
        project_id: uuid.UUID | None = None,
        limit: int = 10,
    ) -> list[ConversationSearchResult]:
        if limit < 1:
            return []

        query_embedding = await self.embedding_provider.embed(query)
        candidates = await self.repository.get_search_candidates(user_id, project_id)
        return await self.search_backend.search(query_embedding, candidates, limit)

    async def store_external_message(
        self, user_id: uuid.UUID, source: str, external_id: str, title: str, role: str, content: str
    ) -> None:
        embedding = await self.embedding_provider.embed(content)
        await self.repository.store_external_message(user_id, source, external_id, title, role, content, embedding)
