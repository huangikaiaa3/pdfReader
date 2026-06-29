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
    ingestion_max_attempts: int = 3
    gemini_api_key: str | None = None
    embedding_model: str = "gemini-embedding-2"
    embedding_output_dimensionality: int = 768
    generation_model: str = "gemini-2.5-flash"
    answer_citation_count: int = 2
    retrieval_weak_match_max_distance: float = 0.4

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
