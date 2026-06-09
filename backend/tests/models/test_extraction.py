import pytest
from pydantic import ValidationError

from app.models.extraction import JobEmailExtraction, job_email_extraction_json_schema


def valid_payload() -> dict[str, object]:
    return {
        "isJobRelated": True,
        "company": "Oracle",
        "role": "Senior Software Engineer",
        "jobId": "REQ-123",
        "location": "Austin, TX",
        "emailType": "Interview",
        "statusSignal": "Interview",
        "dates": [
            {
                "label": "interview",
                "text": "January 12, 2026",
                "isoDate": "2026-01-12",
            }
        ],
        "senderDomain": "Careers.Oracle.com",
        "confidence": 0.91,
        "evidence": [
            {
                "field": "statusSignal",
                "snippet": "We would like to schedule an interview.",
            }
        ],
        "ambiguousIndicators": [],
        "uniqueKeywords": [
            "REQ-123",
            "Oracle Cloud",
            "req-123",
            "Hiring Team",
        ],
        "reviewReason": None,
    }


def test_extraction_accepts_gemini_aliases_and_normalizes_matching_hints() -> None:
    extraction = JobEmailExtraction.model_validate(valid_payload())

    assert extraction.company == "Oracle"
    assert extraction.job_id == "REQ-123"
    assert extraction.sender_domain == "careers.oracle.com"
    assert extraction.unique_keywords == ["REQ-123", "Oracle Cloud", "Hiring Team"]
    assert extraction.dates[0].iso_date.isoformat() == "2026-01-12"
    assert extraction.model_dump(by_alias=True)["uniqueKeywords"] == [
        "REQ-123",
        "Oracle Cloud",
        "Hiring Team",
    ]


def test_extraction_accepts_datetime_string_for_date_only_field() -> None:
    payload = valid_payload()
    payload["dates"] = [
        {
            "label": "received",
            "text": "2026-01-12T09:30:00",
            "isoDate": "2026-01-12T09:30:00",
        }
    ]

    extraction = JobEmailExtraction.model_validate(payload)

    assert extraction.dates[0].iso_date.isoformat() == "2026-01-12"


def test_extraction_rejects_unknown_fields() -> None:
    payload = valid_payload()
    payload["rawEmailBody"] = "Do not accept extra LLM fields."

    with pytest.raises(ValidationError):
        JobEmailExtraction.model_validate(payload)


def test_extraction_rejects_inconsistent_non_job_classification() -> None:
    payload = valid_payload()
    payload.update(
        {
            "isJobRelated": False,
            "emailType": "RecruiterOutreach",
            "statusSignal": "Reviewing",
        }
    )

    with pytest.raises(ValidationError):
        JobEmailExtraction.model_validate(payload)


def test_extraction_marks_low_confidence_or_ambiguous_job_email_for_review() -> None:
    payload = valid_payload()
    payload["confidence"] = 0.62
    extraction = JobEmailExtraction.model_validate(payload)

    assert extraction.requires_review(0.7) is True


def test_gemini_schema_uses_required_camel_case_contract() -> None:
    schema = job_email_extraction_json_schema()

    assert schema["additionalProperties"] is False
    assert "uniqueKeywords" in schema["required"]
    assert schema["properties"]["emailType"]["enum"] == [
        "ApplicationConfirmation",
        "StatusUpdate",
        "Interview",
        "Assessment",
        "Offer",
        "Rejection",
        "RecruiterOutreach",
        "Other",
    ]
