"""Application configuration."""

from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    app_name: str = "pdfReader"
    environment: str = "local"
    app_database_url: str | None = None
    database_url: str
    redis_url: str
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    auth_session_ttl_days: int = 30
    storage_backend: str = "local"
    storage_root: str = "storage"
    storage_bucket: str | None = None
    storage_key_prefix: str = "documents"
    log_level: str = "INFO"
    ingestion_queue_name: str = "ingestion_jobs"
    ingestion_event_channel: str = "ingestion_events"
    ingestion_max_attempts: int = 3
    max_upload_size_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 100
    max_session_question_chars: int = 4000
    session_inactivity_timeout_minutes: int = 60
    session_cleanup_interval_seconds: int = 60
    gemini_api_key: SecretStr | None = None
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

    @model_validator(mode="after")
    def validate_runtime_settings(self) -> "Settings":
        """Validate environment combinations that matter in deployed runtimes."""

        if self.app_database_url:
            self.database_url = self.app_database_url
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif self.database_url.startswith("postgresql://") and "+psycopg" not in self.database_url.split("://", 1)[0]:
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if self.storage_backend not in {"local", "s3"}:
            raise ValueError("STORAGE_BACKEND must be 'local' or 's3'.")
        if self.storage_backend == "s3" and not self.storage_bucket:
            raise ValueError("STORAGE_BUCKET is required when STORAGE_BACKEND=s3.")
        if self.environment == "production" and self.gemini_api_key is None:
            raise ValueError("GEMINI_API_KEY is required when ENVIRONMENT=production.")
        if self.max_upload_size_bytes <= 0:
            raise ValueError("MAX_UPLOAD_SIZE_BYTES must be greater than 0.")
        if self.auth_session_ttl_days <= 0:
            raise ValueError("AUTH_SESSION_TTL_DAYS must be greater than 0.")
        if self.max_pdf_pages <= 0:
            raise ValueError("MAX_PDF_PAGES must be greater than 0.")
        if self.max_session_question_chars <= 0:
            raise ValueError("MAX_SESSION_QUESTION_CHARS must be greater than 0.")
        if self.session_inactivity_timeout_minutes <= 0:
            raise ValueError("SESSION_INACTIVITY_TIMEOUT_MINUTES must be greater than 0.")
        if self.session_cleanup_interval_seconds <= 0:
            raise ValueError("SESSION_CLEANUP_INTERVAL_SECONDS must be greater than 0.")
        return self

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        """Return normalized CORS origins from the comma-separated env value."""

        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
