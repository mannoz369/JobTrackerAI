from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


BackfillJobStatus = Literal["pending", "running", "succeeded", "failed"]


class BackfillJobCreate(BaseModel):
    user_id: str
    start_date: date
    status: BackfillJobStatus = "pending"
    gmail_query: str
    page_token: str | None = None
    fetched_count: int = 0
    saved_count: int = 0
    duplicate_count: int = 0
    processed_count: int = 0
    extracted_count: int = 0
    non_job_count: int = 0
    needs_review_count: int = 0
    failed_count: int = 0
    matched_count: int = 0
    created_count: int = 0
    errors: list[str] = Field(default_factory=list)
    last_error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class BackfillJobRecord(BackfillJobCreate):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def stringify_mongo_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value)
