import asyncio
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.models.application import ApplicationCreate, ApplicationRecord
from app.models.company import CompanyRecord
from app.models.email import EmailProcessingState, EmailRecord
from app.models.extraction import JobEmailExtraction
from app.models.status_update import StatusUpdateCreate, StatusUpdateRecord
from app.services.application_matching import ApplicationMatchResult
from app.services.application_status import ApplicationStatusService


class FakeApplicationsRepository:
    def __init__(
        self,
        applications: list[ApplicationRecord] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.applications = {application.id: application for application in applications or []}
        self.created: list[ApplicationCreate] = []
        self.events = events if events is not None else []

    async def get_by_id(self, application_id: str) -> ApplicationRecord | None:
        return self.applications.get(application_id)

    async def update_current_status(
        self,
        application_id: str,
        status: str,
    ) -> ApplicationRecord | None:
        self.events.append("application_update")
        application = self.applications.get(application_id)
        if application is None:
            return None
        updated = application.model_copy(
            update={
                "current_status": status,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.applications[application_id] = updated
        return updated

    async def create_application(
        self,
        application: ApplicationCreate,
    ) -> ApplicationRecord:
        self.created.append(application)
        now = datetime(2026, 1, 3, tzinfo=timezone.utc)
        record = ApplicationRecord.model_validate(
            {
                "_id": f"app_{len(self.created)}",
                **application.model_dump(mode="python"),
                "created_at": now,
                "updated_at": now,
            }
        )
        self.applications[record.id] = record
        return record


class FakeCompaniesRepository:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, list[str]]] = []

    async def upsert_company(
        self,
        user_id: str,
        name: str,
        *,
        domains: list[str] | None = None,
    ) -> CompanyRecord:
        self.created.append((user_id, name, domains or []))
        now = datetime(2026, 1, 3, tzinfo=timezone.utc)
        return CompanyRecord.model_validate(
            {
                "_id": "company_1",
                "user_id": user_id,
                "name": name,
                "domains": domains or [],
                "created_at": now,
                "updated_at": now,
            }
        )


class FakeStatusUpdatesRepository:
    def __init__(self, events: list[str] | None = None) -> None:
        self.updates: list[StatusUpdateRecord] = []
        self.events = events if events is not None else []

    async def get_by_email_id(
        self,
        user_id: str,
        email_id: str,
    ) -> StatusUpdateRecord | None:
        for update in self.updates:
            if update.user_id == user_id and update.email_id == email_id:
                return update
        return None

    async def create_status_update(
        self,
        status_update: StatusUpdateCreate,
    ) -> StatusUpdateRecord:
        self.events.append("status_update")
        record = StatusUpdateRecord.model_validate(
            {
                "_id": f"status_update_{len(self.updates) + 1}",
                **status_update.model_dump(mode="python"),
                "created_at": datetime(2026, 1, 3, tzinfo=timezone.utc),
            }
        )
        self.updates.append(record)
        return record


class FakeEmailsRepository:
    def __init__(self) -> None:
        self.stored: list[tuple[str, EmailProcessingState, dict[str, Any]]] = []

    async def store_application_match_result(
        self,
        email_id: str,
        processing_state: EmailProcessingState,
        **kwargs: Any,
    ) -> None:
        self.stored.append((email_id, processing_state, kwargs))


class FakeMatchingService:
    def __init__(self, result: ApplicationMatchResult) -> None:
        self.result = result

    async def match_email(self, email: EmailRecord) -> ApplicationMatchResult:
        return self.result


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
        "confidence": 0.93,
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


def test_matched_email_writes_history_before_mutating_current_status() -> None:
    async def run() -> None:
        events: list[str] = []
        applications = FakeApplicationsRepository([application_record()], events)
        status_updates = FakeStatusUpdatesRepository(events)
        emails = FakeEmailsRepository()
        service = ApplicationStatusService(
            Settings(),
            applications,  # type: ignore[arg-type]
            FakeCompaniesRepository(),  # type: ignore[arg-type]
            status_updates,  # type: ignore[arg-type]
            emails,  # type: ignore[arg-type]
            matching_service=FakeMatchingService(
                ApplicationMatchResult(
                    decision="matched",
                    confidence=1.0,
                    explanation="Exact job ID.",
                    method="job_id",
                    application_id="app_1",
                    candidate_application_ids=["app_1"],
                )
            ),  # type: ignore[arg-type]
        )

        result = await service.process_email(email_record(extraction_payload()))

        assert result.action == "status_updated"
        assert events == ["status_update", "application_update"]
        assert status_updates.updates[0].previous_status == "Applied"
        assert status_updates.updates[0].new_status == "Interview"
        assert applications.applications["app_1"].current_status == "Interview"
        assert emails.stored[0][1] == "matched"
        assert emails.stored[0][2]["application_id"] == "app_1"

    asyncio.run(run())


def test_high_confidence_application_confirmation_auto_creates_application() -> None:
    async def run() -> None:
        applications = FakeApplicationsRepository()
        companies = FakeCompaniesRepository()
        status_updates = FakeStatusUpdatesRepository()
        emails = FakeEmailsRepository()
        service = ApplicationStatusService(
            Settings(),
            applications,  # type: ignore[arg-type]
            companies,  # type: ignore[arg-type]
            status_updates,  # type: ignore[arg-type]
            emails,  # type: ignore[arg-type]
            matching_service=FakeMatchingService(
                ApplicationMatchResult(
                    decision="no_match",
                    confidence=0.0,
                    explanation="No existing application.",
                )
            ),  # type: ignore[arg-type]
        )

        result = await service.process_email(
            email_record(
                extraction_payload(
                    emailType="ApplicationConfirmation",
                    statusSignal="Applied",
                    confidence=0.96,
                )
            )
        )

        assert result.action == "application_created"
        assert companies.created == [
            ("user_123", "Acme", ["jobs.acme.example"])
        ]
        assert applications.created[0].current_status == "Applied"
        assert applications.created[0].normalized_keywords == [
            "acme-42",
            "python",
            "remote",
            "jobs.acme.example",
        ]
        assert status_updates.updates[0].previous_status is None
        assert status_updates.updates[0].new_status == "Applied"
        assert emails.stored[0][1] == "matched"

    asyncio.run(run())


def test_ambiguous_match_marks_email_for_review_without_status_change() -> None:
    async def run() -> None:
        applications = FakeApplicationsRepository([application_record()])
        status_updates = FakeStatusUpdatesRepository()
        emails = FakeEmailsRepository()
        service = ApplicationStatusService(
            Settings(),
            applications,  # type: ignore[arg-type]
            FakeCompaniesRepository(),  # type: ignore[arg-type]
            status_updates,  # type: ignore[arg-type]
            emails,  # type: ignore[arg-type]
            matching_service=FakeMatchingService(
                ApplicationMatchResult(
                    decision="ambiguous",
                    confidence=0.71,
                    explanation="Multiple Oracle applications are plausible.",
                    method="keyword",
                    application_id="app_1",
                    candidate_application_ids=["app_1", "app_2"],
                )
            ),  # type: ignore[arg-type]
        )

        result = await service.process_email(email_record(extraction_payload()))

        assert result.action == "needs_review"
        assert status_updates.updates == []
        assert applications.applications["app_1"].current_status == "Applied"
        assert emails.stored[0][1] == "needs_review"
        assert emails.stored[0][2]["review_reason"] == (
            "Multiple Oracle applications are plausible."
        )

    asyncio.run(run())
