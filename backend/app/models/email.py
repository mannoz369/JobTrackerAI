from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.extraction import JobEmailExtraction


EmailProcessingState = Literal[
    "pending_extraction",
    "extracted",
    "non_job",
    "needs_review",
    "matched",
    "extraction_failed",
    "ignored",
    "failed",
]


class EmailCreate(BaseModel):
    user_id: str
    gmail_message_id: str
    thread_id: str | None = None
    sender: str | None = None
    recipients: list[str] = Field(default_factory=list)
    subject: str | None = None
    received_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    snippet: str | None = None
    body_text: str | None = None
    processing_state: EmailProcessingState = "pending_extraction"
    source_history_id: str | None = None


class EmailRecord(EmailCreate):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    extraction: JobEmailExtraction | None = None
    extraction_model: str | None = None
    extracted_at: datetime | None = None
    extraction_error: str | None = None
    extraction_attempts: int = 0
    application_id: str | None = None
    status_update_id: str | None = None
    matching_result: dict[str, Any] | None = None
    application_review_reason: str | None = None
    matched_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def stringify_mongo_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value)
