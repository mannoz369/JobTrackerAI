from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EmailType = Literal[
    "ApplicationConfirmation",
    "StatusUpdate",
    "Interview",
    "Assessment",
    "Offer",
    "Rejection",
    "RecruiterOutreach",
    "Other",
]

StatusSignal = Literal[
    "Applied",
    "Reviewing",
    "Assessment",
    "Interview",
    "Offer",
    "Rejected",
    "Other",
]


class ExtractionEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    field: str = Field(min_length=1, max_length=64)
    snippet: str = Field(min_length=1, max_length=240)


class ExtractedDate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    label: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=120)
    iso_date: date | None = Field(default=None, alias="isoDate")

    @field_validator("iso_date", mode="before")
    @classmethod
    def datetime_strings_are_dates(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str) and "T" in value:
            candidate = value.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(candidate).date()
            except ValueError:
                return value
        return value


class JobEmailExtraction(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    is_job_related: bool = Field(alias="isJobRelated")
    company: str | None = Field(default=None, max_length=160)
    role: str | None = Field(default=None, max_length=180)
    job_id: str | None = Field(default=None, alias="jobId", max_length=120)
    location: str | None = Field(default=None, max_length=160)
    email_type: EmailType = Field(alias="emailType")
    status_signal: StatusSignal = Field(alias="statusSignal")
    dates: list[ExtractedDate] = Field(default_factory=list, max_length=8)
    sender_domain: str | None = Field(
        default=None,
        alias="senderDomain",
        max_length=255,
    )
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[ExtractionEvidence] = Field(default_factory=list, max_length=8)
    ambiguous_indicators: list[str] = Field(
        default_factory=list,
        alias="ambiguousIndicators",
        max_length=12,
    )
    unique_keywords: list[str] = Field(
        default_factory=list,
        alias="uniqueKeywords",
        max_length=30,
    )
    review_reason: str | None = Field(
        default=None,
        alias="reviewReason",
        max_length=240,
    )

    @field_validator("company", "role", "job_id", "location", "review_reason", mode="before")
    @classmethod
    def empty_strings_are_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("sender_domain", mode="before")
    @classmethod
    def normalize_sender_domain(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value

    @field_validator("ambiguous_indicators", "unique_keywords")
    @classmethod
    def dedupe_string_lists(cls, values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = " ".join(value.strip().split())
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped

    @model_validator(mode="after")
    def validate_non_job_classification(self) -> "JobEmailExtraction":
        if not self.is_job_related and (
            self.email_type != "Other" or self.status_signal != "Other"
        ):
            raise ValueError(
                "Non-job emails must use emailType='Other' and statusSignal='Other'."
            )
        return self

    def requires_review(self, confidence_threshold: float) -> bool:
        return (
            self.is_job_related
            and (
                self.confidence < confidence_threshold
                or bool(self.ambiguous_indicators)
                or bool(self.review_reason)
            )
        )


def job_email_extraction_json_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "isJobRelated": {
                "type": "boolean",
                "description": "Whether this email is about a job application or recruiting process.",
            },
            "company": {
                **nullable_string,
                "description": "Canonical company or employer name, or null when unknown.",
            },
            "role": {
                **nullable_string,
                "description": "Job title or role name, or null when unknown.",
            },
            "jobId": {
                **nullable_string,
                "description": "Requisition, posting, application, or job identifier, or null.",
            },
            "location": {
                **nullable_string,
                "description": "Work location, office, region, remote signal, or null.",
            },
            "emailType": {
                "type": "string",
                "enum": [
                    "ApplicationConfirmation",
                    "StatusUpdate",
                    "Interview",
                    "Assessment",
                    "Offer",
                    "Rejection",
                    "RecruiterOutreach",
                    "Other",
                ],
            },
            "statusSignal": {
                "type": "string",
                "enum": [
                    "Applied",
                    "Reviewing",
                    "Assessment",
                    "Interview",
                    "Offer",
                    "Rejected",
                    "Other",
                ],
            },
            "dates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "label": {"type": "string"},
                        "text": {"type": "string"},
                        "isoDate": {"type": ["string", "null"]},
                    },
                    "required": ["label", "text", "isoDate"],
                },
            },
            "senderDomain": {
                **nullable_string,
                "description": "Lowercase domain from the sender email address, or null.",
            },
            "confidence": {
                "type": "number",
                "description": "Overall extraction confidence from 0.0 to 1.0.",
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "field": {"type": "string"},
                        "snippet": {
                            "type": "string",
                            "description": "Short supporting snippet. Do not copy long raw email content.",
                        },
                    },
                    "required": ["field", "snippet"],
                },
            },
            "ambiguousIndicators": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Reasons this extraction may be ambiguous.",
            },
            "uniqueKeywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Useful matching hints: location, IDs, team, recruiter, domains, product names, or distinctive phrases.",
            },
            "reviewReason": {
                **nullable_string,
                "description": "Why a human should review this email, or null.",
            },
        },
        "required": [
            "isJobRelated",
            "company",
            "role",
            "jobId",
            "location",
            "emailType",
            "statusSignal",
            "dates",
            "senderDomain",
            "confidence",
            "evidence",
            "ambiguousIndicators",
            "uniqueKeywords",
            "reviewReason",
        ],
    }
