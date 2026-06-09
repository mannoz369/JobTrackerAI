from functools import lru_cache
import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "JobTracker API"
    environment: str = "local"
    mongodb_uri: str | None = None
    mongodb_database: str = "jobtracker"
    cors_origins: list[str] = ["http://localhost:3000"]
    frontend_app_url: str = "http://localhost:3000"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    google_cloud_project: str | None = None
    gmail_pubsub_topic: str | None = None
    gmail_pubsub_subscription: str | None = None
    gmail_pubsub_verification_token: str | None = None
    gmail_watch_label_ids: list[str] = ["INBOX"]
    gmail_watch_renewal_window_seconds: int = 60 * 60 * 24
    gmail_backfill_page_size: int = 25
    gmail_backfill_api_max_retries: int = 3
    gmail_backfill_api_retry_backoff_seconds: float = 1.0
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 20.0
    gemini_max_retries: int = 2
    gemini_retry_backoff_seconds: float = 0.25
    email_extraction_batch_size: int = 10
    email_extraction_review_confidence_threshold: float = 0.7
    email_extraction_max_body_chars: int = 6000
    application_match_confidence_threshold: float = 0.82
    application_match_ambiguity_margin: float = 0.08
    application_autocreate_confidence_threshold: float = 0.9
    session_secret_key: str = "dev-session-secret-change-me"
    session_cookie_max_age_seconds: int = 60 * 60 * 24 * 14
    token_encryption_key: str | None = None
    auth_cookie_secure: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            if value.startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("gmail_watch_label_ids", mode="before")
    @classmethod
    def parse_gmail_watch_label_ids(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            if value.startswith("["):
                return json.loads(value)
            return [label.strip() for label in value.split(",") if label.strip()]
        return value

    @field_validator(
        "mongodb_uri",
        "google_client_id",
        "google_client_secret",
        "token_encryption_key",
        "google_cloud_project",
        "gmail_pubsub_topic",
        "gmail_pubsub_subscription",
        "gmail_pubsub_verification_token",
        "gemini_api_key",
        mode="before",
    )
    @classmethod
    def empty_strings_are_unset(cls, value: str | None) -> str | None:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
