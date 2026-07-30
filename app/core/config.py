from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated configuration loaded from environment variables and `.env`."""

    app_name: str = "Wanderra OS"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://wanderra:change-me@db:5432/wanderra"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5"
    openai_embedding_model: str = "text-embedding-3-small"
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_client_secret_file: str = "secrets/google/client_secret.json"
    google_oauth_redirect_uri: str = "http://localhost:8000/api/v1/gmail/oauth/callback"
    gmail_credentials_encryption_key: SecretStr | None = None
    atlas_kms_provider: str | None = None
    atlas_kms_key_resource: str | None = None
    atlas_kms_key_version: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()
