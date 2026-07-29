import uuid
from datetime import UTC, datetime

from app.memory.contracts import (
    ConversationRecord,
    ProjectRecord,
    SearchableConversation,
    UserRecord,
)
from app.memory.search import CosineSimilaritySearchBackend
from app.memory.service import MemoryService


class DeterministicEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "travel" in text.lower() or "flight" in text.lower():
            return [1.0, 0.0]
        return [0.0, 1.0]


class InMemoryRepository:
    def __init__(self) -> None:
        self.user_id = uuid.uuid4()
        self.conversation_id = uuid.uuid4()
        self.messages: list[SearchableConversation] = []

    async def create_user(self, email: str, display_name: str | None) -> UserRecord:
        return UserRecord(id=self.user_id, email=email, display_name=display_name)

    async def create_project(
        self, user_id: uuid.UUID, name: str, description: str | None
    ) -> ProjectRecord:
        return ProjectRecord(id=uuid.uuid4(), user_id=user_id, name=name, description=description)

    async def create_conversation(
        self, user_id: uuid.UUID, project_id: uuid.UUID | None, title: str | None
    ) -> ConversationRecord:
        return ConversationRecord(
            id=self.conversation_id, user_id=user_id, project_id=project_id, title=title
        )

    async def add_message(
        self, conversation_id: uuid.UUID, role: str, content: str, embedding: list[float]
    ) -> None:
        self.messages.append(
            SearchableConversation(
                message_id=uuid.uuid4(),
                conversation_id=conversation_id,
                project_id=None,
                title="Summer trip",
                content=content,
                embedding=embedding,
                created_at=datetime.now(UTC),
            )
        )

    async def get_search_candidates(
        self, user_id: uuid.UUID, project_id: uuid.UUID | None
    ) -> list[SearchableConversation]:
        return self.messages


async def test_memory_service_stores_and_semantically_ranks_conversations() -> None:
    repository = InMemoryRepository()
    service = MemoryService(
        repository=repository,
        embedding_provider=DeterministicEmbeddingProvider(),
        search_backend=CosineSimilaritySearchBackend(),
    )
    user = await service.create_user("atlas@example.com", "Atlas User")
    conversation = await service.create_conversation(user.id, title="Summer trip")

    await service.store_message(conversation.id, "user", "Find flights to Stockholm")
    await service.store_message(conversation.id, "assistant", "Your hotel is reserved")

    results = await service.search_conversations(user.id, "travel plans")

    assert len(results) == 2
    assert results[0].content == "Find flights to Stockholm"
    assert results[0].score > results[1].score


async def test_memory_service_returns_no_results_for_a_non_positive_limit() -> None:
    service = MemoryService(
        repository=InMemoryRepository(),
        embedding_provider=DeterministicEmbeddingProvider(),
        search_backend=CosineSimilaritySearchBackend(),
    )

    assert await service.search_conversations(uuid.uuid4(), "travel", limit=0) == []
