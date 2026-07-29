"""Embedding implementations for the memory domain."""

from openai import AsyncOpenAI

from app.core.config import Settings, get_settings


class MemoryConfigurationError(RuntimeError):
    """Raised when a memory provider cannot access required configuration."""


class OpenAIEmbeddingProvider:
    """Creates semantic embeddings through the official OpenAI Python SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if self.settings.openai_api_key is None:
            raise MemoryConfigurationError("OPENAI_API_KEY must be configured for semantic memory.")
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key.get_secret_value())

    async def embed(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=text,
        )
        return response.data[0].embedding
