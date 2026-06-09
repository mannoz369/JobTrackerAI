import asyncio
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.models.application import ApplicationRecord
from app.models.email import EmailRecord
from app.models.extraction import JobEmailExtraction
from app.services.application_matching import (
    ApplicationMatchingService,
    LlmApplicationMatchResponse,
)


class FakeApplicationsRepository:
    def __init__(self, applications: list[ApplicationRecord]) -> None:
        self.applications = applications

    async def list_by_job_id(
        self,
        user_id: str,
        job_id: str,
    ) -> list[ApplicationRecord]:
        normalized = job_id.strip().lower()
        return [
            application
            for application in self.applications
            if application.user_id == user_id
            and application.normalized_job_id == normalized
        ]

    async def list_by_company_and_role(
        self,
        user_id: str,
        company: str,
        role: str,
    ) -> list[ApplicationRecord]:
        normalized_company = company.strip().lower()
        normalized_role = role.strip().lower()
        return [
            application
            for application in self.applications
            if application.user_id == user_id
            and application.normalized_company == normalized_company
            and application.normalized_role == normalized_role
        ]

    async def list_candidates(
        self,
        user_id: str,
        *,
        company: str | None = None,
        keywords: list[str] | None = None,
        limit: int = 10,
    ) -> list[ApplicationRecord]:
        return [
            application
            for application in self.applications
            if application.user_id == user_id
        ][:limit]


class FakeLlmMatcher:
    async def match_application(
        self,
        email: EmailRecord,
        extraction: JobEmailExtraction,
        candidates: list[ApplicationRecord],
    ) -> LlmApplicationMatchResponse:
        return LlmApplicationMatchResponse(
            applicationId="app_2",
            confidence=0.87,
            explanation="The email mentions the Cloud Infrastructure team keyword.",
        )


def application_record(**overrides: Any) -> ApplicationRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload: dict[str, Any] = {
        "_id": "app_1",
        "user_id": "user_123",
        "company_id": "company_1",
        "company_name": "Acme",
        "role": "Backend Engineer",
        "job_id": "ACME-42",
        "location": "Remote",
        "current_status": "Applied",
        "normalized_keywords": ["remote", "python", "acme-42"],
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return ApplicationRecord.model_validate(payload)


def extraction_payload(**overrides: Any) -> JobEmailExtraction:
    payload: dict[str, Any] = {
        "isJobRelated": True,
        "company": "Acme",
        "role": "Backend Engineer",
        "jobId": "ACME-42",
        "location": "Remote",
        "emailType": "StatusUpdate",
        "statusSignal": "Interview",
        "dates": [],
        "senderDomain": "jobs.acme.example",
        "confidence": 0.91,
        "evidence": [
            {
                "field": "statusSignal",
                "snippet": "We would like to interview you.",
            }
        ],
        "ambiguousIndicators": [],
        "uniqueKeywords": ["ACME-42", "Python"],
        "reviewReason": None,
    }
    payload.update(overrides)
    return JobEmailExtraction.model_validate(payload)


def email_record(extraction: JobEmailExtraction) -> EmailRecord:
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    return EmailRecord(
        _id="email_1",
        user_id="user_123",
        gmail_message_id="gmail-message-1",
        sender="Recruiting <jobs@jobs.acme.example>",
        subject="Application update",
        processing_state="extracted",
        extraction=extraction,
        created_at=now,
        updated_at=now,
    )


def test_matching_uses_exact_job_id_first() -> None:
    async def run() -> None:
        service = ApplicationMatchingService(
            Settings(),
            FakeApplicationsRepository([application_record()]),  # type: ignore[arg-type]
        )

        result = await service.match_email(email_record(extraction_payload()))

        assert result.decision == "matched"
        assert result.method == "job_id"
        assert result.application_id == "app_1"
        assert result.confidence == 1.0

    asyncio.run(run())


def test_matching_routes_duplicate_company_role_to_ambiguous() -> None:
    async def run() -> None:
        service = ApplicationMatchingService(
            Settings(),
            FakeApplicationsRepository(
                [
                    application_record(_id="app_1", job_id=None),
                    application_record(_id="app_2", job_id=None),
                ]
            ),  # type: ignore[arg-type]
        )

        result = await service.match_email(
            email_record(extraction_payload(jobId=None, uniqueKeywords=[]))
        )

        assert result.decision == "ambiguous"
        assert result.method == "company_role"
        assert result.candidate_application_ids == ["app_1", "app_2"]

    asyncio.run(run())


def test_matching_uses_llm_for_keyword_candidates() -> None:
    async def run() -> None:
        applications = [
            application_record(
                _id="app_1",
                company_name="Oracle",
                role="Database Engineer",
                job_id=None,
                normalized_keywords=["database"],
            ),
            application_record(
                _id="app_2",
                company_name="Oracle",
                role="Cloud Engineer",
                job_id=None,
                normalized_keywords=["cloud infrastructure"],
            ),
        ]
        service = ApplicationMatchingService(
            Settings(),
            FakeApplicationsRepository(applications),  # type: ignore[arg-type]
            llm_matcher=FakeLlmMatcher(),
        )

        result = await service.match_email(
            email_record(
                extraction_payload(
                    company="Oracle",
                    role=None,
                    jobId=None,
                    uniqueKeywords=["Cloud Infrastructure"],
                )
            )
        )

        assert result.decision == "matched"
        assert result.method == "llm"
        assert result.application_id == "app_2"
        assert result.confidence == 0.87

    asyncio.run(run())
