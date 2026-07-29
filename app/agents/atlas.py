"""Atlas, Wanderra OS's first conversational AI agent."""

from openai import AsyncOpenAI

from app.core.config import Settings, get_settings


class AtlasConfigurationError(RuntimeError):
    """Raised when Atlas cannot access its required configuration."""


class AtlasAgent:
    """Conversational agent powered by the official OpenAI Python SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

        if self.settings.openai_api_key is None:
            raise AtlasConfigurationError("OPENAI_API_KEY must be configured for Atlas.")

        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key.get_secret_value())

    async def chat(self, prompt: str) -> str:
        """Send a user prompt to OpenAI and return Atlas's text response."""
        response = await self.client.responses.create(
            model=self.settings.openai_model,
            input=prompt,
        )
        return response.output_text

