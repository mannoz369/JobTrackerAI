from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.application import ApplicationStatus
from app.models.extraction import ExtractionEvidence


StatusUpdateSource = Literal["email", "manual", "system"]


class StatusUpdateCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    email_id: str | None = None
    previous_status: ApplicationStatus | None = None
    new_status: ApplicationStatus
    source: StatusUpdateSource = "email"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    explanation: str | None = Field(default=None, max_length=1000)
    match_method: str | None = Field(default=None, max_length=64)
    evidence: list[ExtractionEvidence] = Field(default_factory=list, max_length=12)

    @field_validator(
        "email_id",
        "previous_status",
        "explanation",
        "match_method",
        mode="before",
    )
    @classmethod
    def empty_strings_are_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class StatusUpdateRecord(StatusUpdateCreate):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: str | None = Field(default=None, alias="_id")
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def stringify_mongo_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value)
