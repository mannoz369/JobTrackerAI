import asyncio
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.models.email import EmailProcessingState, EmailRecord
from app.models.extraction import JobEmailExtraction
from app.services.email_extraction_worker import EmailExtractionWorker
from app.services.gemini import GeminiTransientError


class FakeEmailsRepository:
    def __init__(self, pending: list[EmailRecord]) -> None:
        self.pending = pending
        self.limit: int | None = None
        self.stored: list[tuple[str, JobEmailExtraction, EmailProcessingState, str]] = []
        self.failed: list[tuple[str, str, str | None]] = []
        self.deferred: list[tuple[str, str, str | None]] = []

    async def list_pending_extraction(self, limit: int) -> list[EmailRecord]:
        self.limit = limit
        return self.pending[:limit]

    async def store_extraction_result(
        self,
        email_id: str,
        extraction: JobEmailExtraction,
        processing_state: EmailProcessingState,
        *,
        model_name: str,
    ) -> None:
        self.stored.append((email_id, extraction, processing_state, model_name))

    async def mark_extraction_failed(
        self,
        email_id: str,
        error: str,
        *,
        model_name: str | None = None,
    ) -> None:
        self.failed.append((email_id, error, model_name))

    async def defer_extraction(
        self,
        email_id: str,
        error: str,
        *,
        model_name: str | None = None,
    ) -> None:
        self.deferred.append((email_id, error, model_name))


class FakeGeminiService:
    model_name = "gemini-2.5-flash"

    def __init__(
        self,
        responses: dict[str, JobEmailExtraction | Exception],
    ) -> None:
        self.responses = responses

    async def extract_email(self, email: EmailRecord) -> JobEmailExtraction:
        response = self.responses[email.gmail_message_id]
        if isinstance(response, Exception):
            raise response
        return response


def make_email(message_id: str, *, email_id: str | None = None) -> EmailRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return EmailRecord(
        _id=email_id or message_id,
        user_id="user_123",
        gmail_message_id=message_id,
        sender="Recruiting <jobs@example.com>",
        subject="Application update",
        processing_state="pending_extraction",
        created_at=now,
        updated_at=now,
    )


def extraction_payload(**overrides: Any) -> JobEmailExtraction:
    payload: dict[str, Any] = {
        "isJobRelated": True,
        "company": "Acme",
        "role": "Backend Engineer",
        "jobId": "ACME-42",
        "location": "Remote",
        "emailType": "ApplicationConfirmation",
        "statusSignal": "Applied",
        "dates": [],
        "senderDomain": "jobs.acme.example",
        "confidence": 0.91,
        "evidence": [
            {
                "field": "statusSignal",
                "snippet": "Thank you for applying.",
            }
        ],
        "ambiguousIndicators": [],
        "uniqueKeywords": ["ACME-42"],
        "reviewReason": None,
    }
    payload.update(overrides)
    return JobEmailExtraction.model_validate(payload)


def test_process_pending_stores_extracted_non_job_and_review_states() -> None:
    async def run() -> None:
        emails = [
            make_email("message-1", email_id="email_1"),
            make_email("message-2", email_id="email_2"),
            make_email("message-3", email_id="email_3"),
        ]
        repository = FakeEmailsRepository(emails)
        gemini_service = FakeGeminiService(
            {
                "message-1": extraction_payload(),
                "message-2": extraction_payload(
                    isJobRelated=False,
                    company=None,
                    role=None,
                    jobId=None,
                    location=None,
                    emailType="Other",
                    statusSignal="Other",
                    confidence=0.95,
                    uniqueKeywords=[],
                ),
                "message-3": extraction_payload(
                    confidence=0.61,
                    ambiguousIndicators=["role missing"],
                    reviewReason="Missing role.",
                ),
            }
        )
        worker = EmailExtractionWorker(
            Settings(email_extraction_batch_size=5),
            repository,  # type: ignore[arg-type]
            gemini_service=gemini_service,  # type: ignore[arg-type]
        )

        result = await worker.process_pending()

        assert repository.limit == 5
        assert result.processed == 3
        assert result.extracted == 1
        assert result.non_job == 1
        assert result.needs_review == 1
        assert result.failed == 0
        assert [(email_id, state) for email_id, _, state, _ in repository.stored] == [
            ("email_1", "extracted"),
            ("email_2", "non_job"),
            ("email_3", "needs_review"),
        ]

    asyncio.run(run())


def test_process_email_marks_extraction_failure_without_crashing() -> None:
    async def run() -> None:
        email = make_email("message-1", email_id="email_1")
        repository = FakeEmailsRepository([email])
        worker = EmailExtractionWorker(
            Settings(),
            repository,  # type: ignore[arg-type]
            gemini_service=FakeGeminiService(
                {"message-1": RuntimeError("invalid model JSON")}
            ),  # type: ignore[arg-type]
        )

        state = await worker.process_email(email)

        assert state == "extraction_failed"
        assert repository.stored == []
        assert repository.failed == [
            ("email_1", "invalid model JSON", "gemini-2.5-flash")
        ]

    asyncio.run(run())


def test_process_email_defers_transient_gemini_failure() -> None:
    async def run() -> None:
        email = make_email("message-1", email_id="email_1")
        repository = FakeEmailsRepository([email])
        worker = EmailExtractionWorker(
            Settings(),
            repository,  # type: ignore[arg-type]
            gemini_service=FakeGeminiService(
                {"message-1": GeminiTransientError("Gemini request failed with status 429.")}
            ),  # type: ignore[arg-type]
        )

        state = await worker.process_email(email)

        assert state == "deferred"
        assert repository.stored == []
        assert repository.failed == []
        assert repository.deferred == [
            (
                "email_1",
                "Gemini request failed with status 429.",
                "gemini-2.5-flash",
            )
        ]

    asyncio.run(run())
