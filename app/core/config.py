"""Application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    app_name: str = "pdfReader"
    environment: str = "local"
    database_url: str
    redis_url: str
    storage_root: str = "storage"
    ingestion_queue_name: str = "ingestion_jobs"
    ingestion_event_channel: str = "ingestion_events"
    gemini_api_key: str | None = None
    embedding_model: str = "gemini-embedding-2"
    embedding_output_dimensionality: int = 768

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
