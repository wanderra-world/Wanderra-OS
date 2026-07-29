"""Search backends for semantic memory."""

import math
from collections.abc import Sequence

from app.memory.contracts import (
    ConversationSearchResult,
    SearchableConversation,
)


class CosineSimilaritySearchBackend:
    """Durable baseline search using stored embeddings and cosine similarity.

    A vector database adapter can implement the same `SemanticSearchBackend` protocol
    without changing `MemoryService` or its callers.
    """

    async def search(
        self,
        query_embedding: list[float],
        candidates: Sequence[SearchableConversation],
        limit: int,
    ) -> list[ConversationSearchResult]:
        results = [
            ConversationSearchResult(
                conversation_id=candidate.conversation_id,
                message_id=candidate.message_id,
                project_id=candidate.project_id,
                title=candidate.title,
                content=candidate.content,
                score=self._cosine_similarity(query_embedding, candidate.embedding),
                created_at=candidate.created_at,
            )
            for candidate in candidates
        ]
        return sorted(results, key=lambda result: result.score, reverse=True)[:limit]

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left or not right:
            return 0.0

        denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
            sum(value * value for value in right)
        )
        if denominator == 0:
            return 0.0
        return sum(left_value * right_value for left_value, right_value in zip(left, right)) / denominator
