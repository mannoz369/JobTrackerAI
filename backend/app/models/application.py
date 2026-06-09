from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ApplicationStatus = Literal[
    "Applied",
    "Reviewing",
    "Assessment",
    "Interview",
    "Offer",
    "Rejected",
    "Other",
]


def normalize_match_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().lower().split())
    return normalized or None


def normalize_keywords(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_match_text(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: str = Field(min_length=1)
    company_id: str | None = None
    company_name: str = Field(min_length=1, max_length=160)
    normalized_company: str | None = Field(default=None, max_length=160)
    role: str = Field(min_length=1, max_length=180)
    normalized_role: str | None = Field(default=None, max_length=180)
    job_id: str | None = Field(default=None, max_length=120)
    normalized_job_id: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=160)
    current_status: ApplicationStatus = "Applied"
    normalized_keywords: list[str] = Field(default_factory=list, max_length=60)
    source_email_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "company_id",
        "normalized_company",
        "normalized_role",
        "job_id",
        "normalized_job_id",
        "location",
        "source_email_id",
        "notes",
        mode="before",
    )
    @classmethod
    def empty_strings_are_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("normalized_keywords", mode="before")
    @classmethod
    def normalize_keyword_values(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, list):
            return normalize_keywords([str(item) for item in value])
        return value

    @model_validator(mode="after")
    def populate_normalized_fields(self) -> "ApplicationCreate":
        self.normalized_company = self.normalized_company or normalize_match_text(
            self.company_name
        )
        self.normalized_role = self.normalized_role or normalize_match_text(self.role)
        self.normalized_job_id = self.normalized_job_id or normalize_match_text(
            self.job_id
        )
        if self.normalized_company is None:
            raise ValueError("Application company must normalize to a non-empty value.")
        if self.normalized_role is None:
            raise ValueError("Application role must normalize to a non-empty value.")
        return self


class ApplicationRecord(ApplicationCreate):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: str | None = Field(default=None, alias="_id")
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def stringify_mongo_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value)
