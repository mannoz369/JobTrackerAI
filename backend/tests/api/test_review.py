from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.api.auth import SESSION_COOKIE
from app.core.config import Settings
from app.core.security import SessionSigner
from app.main import create_app
from app.models.application import ApplicationCreate, ApplicationRecord
from app.models.company import CompanyRecord
from app.models.email import EmailProcessingState, EmailRecord
from app.models.extraction import JobEmailExtraction
from app.models.status_update import StatusUpdateCreate, StatusUpdateRecord
from app.models.user import GmailWatchState, OAuthTokenMetadata, UserRecord


NOW = datetime(2026, 1, 5, tzinfo=timezone.utc)


class FakeUsersRepository:
    def __init__(self, user: UserRecord) -> None:
        self.user = user

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return self.user if self.user.id == user_id else None


class FakeApplicationsRepository:
    def __init__(self) -> None:
        self.applications = {
            "app_1": application_record(_id="app_1", current_status="Applied"),
            "app_2": application_record(
                _id="app_2",
                company_name="Acme",
                role="Data Engineer",
                current_status="Reviewing",
            ),
        }
        self.created: list[ApplicationCreate] = []
        self.raise_duplicate_on_create = False

    async def list_by_ids(
        self,
        user_id: str,
        application_ids: list[str],
    ) -> list[ApplicationRecord]:
        return [
            self.applications[application_id]
            for application_id in application_ids
            if application_id in self.applications
            and self.applications[application_id].user_id == user_id
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
            for application in self.applications.values()
            if application.user_id == user_id
            and (company is None or application.company_name == company)
        ][:limit]

    async def get_for_user(
        self,
        user_id: str,
        application_id: str,
    ) -> ApplicationRecord | None:
        application = self.applications.get(application_id)
        if application is None or application.user_id != user_id:
            return None
        return application

    async def update_current_status_for_user(
        self,
        user_id: str,
        application_id: str,
        status: str,
    ) -> ApplicationRecord | None:
        application = await self.get_for_user(user_id, application_id)
        if application is None:
            return None
        updated = application.model_copy(
            update={"current_status": status, "updated_at": NOW}
        )
        self.applications[application_id] = updated
        return updated

    async def create_application(
        self,
        application: ApplicationCreate,
    ) -> ApplicationRecord:
        if self.raise_duplicate_on_create:
            raise DuplicateKeyError("duplicate job id")
        self.created.append(application)
        record = ApplicationRecord.model_validate(
            {
                "_id": f"app_{len(self.applications) + 1}",
                **application.model_dump(mode="python"),
                "created_at": NOW,
                "updated_at": NOW,
            }
        )
        self.applications[record.id or ""] = record
        return record


class FakeEmailsRepository:
    def __init__(self) -> None:
        self.emails = {
            "email_1": email_record(),
            "email_2": email_record(
                _id="email_2",
                subject="Recruiter newsletter",
                processing_state="needs_review",
                matching_result=None,
            ),
        }
        self.stored: list[tuple[str, EmailProcessingState, dict[str, Any]]] = []

    async def list_needs_review(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[EmailRecord]:
        return [
            email
            for email in self.emails.values()
            if email.user_id == user_id and email.processing_state == "needs_review"
        ][:limit]

    async def get_for_user(
        self,
        user_id: str,
        email_id: str,
    ) -> EmailRecord | None:
        email = self.emails.get(email_id)
        if email is None or email.user_id != user_id:
            return None
        return email

    async def store_application_match_result_for_user(
        self,
        user_id: str,
        email_id: str,
        processing_state: EmailProcessingState,
        **kwargs: Any,
    ) -> EmailRecord | None:
        email = await self.get_for_user(user_id, email_id)
        if email is None:
            return None
        self.stored.append((email_id, processing_state, kwargs))
        updated = email.model_copy(
            update={
                "processing_state": processing_state,
                "application_id": kwargs.get("application_id"),
                "status_update_id": kwargs.get("status_update_id"),
                "matching_result": kwargs.get("matching_result"),
                "application_review_reason": kwargs.get("review_reason"),
                "updated_at": NOW,
            }
        )
        self.emails[email_id] = updated
        return updated


class FakeCompaniesRepository:
    async def upsert_company(
        self,
        user_id: str,
        name: str,
        *,
        domains: list[str] | None = None,
    ) -> CompanyRecord:
        return CompanyRecord.model_validate(
            {
                "_id": "company_1",
                "user_id": user_id,
                "name": name,
                "domains": domains or [],
                "created_at": NOW,
                "updated_at": NOW,
            }
        )


class FakeStatusUpdatesRepository:
    def __init__(self) -> None:
        self.created: list[StatusUpdateRecord] = []

    async def create_status_update(
        self,
        status_update: StatusUpdateCreate,
    ) -> StatusUpdateRecord:
        record = StatusUpdateRecord.model_validate(
            {
                "_id": f"status_update_{len(self.created) + 1}",
                **status_update.model_dump(mode="python"),
                "created_at": NOW,
            }
        )
        self.created.append(record)
        return record


def make_client() -> tuple[
    TestClient,
    FakeApplicationsRepository,
    FakeEmailsRepository,
    FakeStatusUpdatesRepository,
]:
    settings = Settings(session_secret_key="session-secret-for-tests")
    app = create_app(settings)
    applications = FakeApplicationsRepository()
    emails = FakeEmailsRepository()
    status_updates = FakeStatusUpdatesRepository()
    app.state.users_repository = FakeUsersRepository(make_user())
    app.state.applications_repository = applications
    app.state.emails_repository = emails
    app.state.companies_repository = FakeCompaniesRepository()
    app.state.status_updates_repository = status_updates
    client = TestClient(app)
    session_token = SessionSigner(settings.session_secret_key).create_session(
        user_id="user_123",
        email="person@example.com",
        max_age_seconds=3600,
    )
    client.cookies.set(SESSION_COOKIE, session_token)
    return client, applications, emails, status_updates


def make_user() -> UserRecord:
    return UserRecord(
        _id="user_123",
        google_sub="google-sub-123",
        email="person@example.com",
        email_verified=True,
        monitored_email="person@example.com",
        oauth=OAuthTokenMetadata(refresh_token_encrypted="encrypted-refresh-token"),
        gmail_watch=GmailWatchState(),
        created_at=NOW,
        updated_at=NOW,
    )


def application_record(**overrides: Any) -> ApplicationRecord:
    payload = {
        "_id": "app_1",
        "user_id": "user_123",
        "company_id": "company_1",
        "company_name": "Acme",
        "role": "Backend Engineer",
        "current_status": "Applied",
        "normalized_keywords": ["remote", "acme-42"],
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return ApplicationRecord.model_validate(payload)


def extraction(**overrides: Any) -> JobEmailExtraction:
    payload = {
        "isJobRelated": True,
        "company": "Acme",
        "role": "Backend Engineer",
        "jobId": "ACME-42",
        "location": "Remote",
        "emailType": "Interview",
        "statusSignal": "Interview",
        "dates": [],
        "senderDomain": "jobs.acme.example",
        "confidence": 0.68,
        "evidence": [
            {
                "field": "statusSignal",
                "snippet": "Schedule a technical interview.",
            }
        ],
        "ambiguousIndicators": ["Two Acme applications are active."],
        "uniqueKeywords": ["ACME-42"],
        "reviewReason": "Two Acme applications are active.",
    }
    payload.update(overrides)
    return JobEmailExtraction.model_validate(payload)


def email_record(**overrides: Any) -> EmailRecord:
    payload = {
        "_id": "email_1",
        "user_id": "user_123",
        "gmail_message_id": "gmail-message-1",
        "sender": "Recruiting <jobs@acme.example>",
        "subject": "Interview update",
        "snippet": "Schedule a technical interview.",
        "received_at": NOW,
        "processing_state": "needs_review",
        "extraction": extraction(),
        "matching_result": {
            "decision": "ambiguous",
            "confidence": 0.68,
            "explanation": "Two applications are plausible.",
            "method": "keyword",
            "application_id": "app_1",
            "candidate_application_ids": ["app_1", "app_2"],
        },
        "application_review_reason": "Two applications are plausible.",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return EmailRecord.model_validate(payload)


def test_review_queue_returns_candidate_applications() -> None:
    client, _, _, _ = make_client()

    response = client.get("/review/queue")

    assert response.status_code == 200
    payload = response.json()
    first = payload[0]
    assert first["email_id"] == "email_1"
    assert first["review_reason"] == "Two applications are plausible."
    assert [candidate["id"] for candidate in first["candidates"]] == [
        "app_1",
        "app_2",
    ]
    assert first["matching_result"]["confidence"] == 0.68


def test_map_review_email_updates_application_and_marks_email_matched() -> None:
    client, applications, emails, status_updates = make_client()

    response = client.post(
        "/review/email_1/map",
        json={"application_id": "app_1", "status": "Interview"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "mapped"
    assert payload["application"]["current_status"] == "Interview"
    assert applications.applications["app_1"].current_status == "Interview"
    assert status_updates.created[0].email_id == "email_1"
    assert status_updates.created[0].source == "manual"
    assert emails.stored[0][1] == "matched"
    assert emails.emails["email_1"].processing_state == "matched"


def test_create_application_from_review_uses_extracted_details() -> None:
    client, applications, emails, status_updates = make_client()

    response = client.post("/review/email_1/create-application", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "created"
    assert payload["application"]["company_name"] == "Acme"
    assert applications.created[0].normalized_keywords == [
        "acme-42",
        "remote",
        "jobs.acme.example",
    ]
    assert status_updates.created[0].previous_status is None
    assert emails.emails["email_1"].processing_state == "matched"


def test_create_application_from_review_allows_missing_company_and_role() -> None:
    client, applications, emails, status_updates = make_client()
    emails.emails["email_1"] = email_record(
        extraction=extraction(
            company=None,
            role=None,
            jobId=None,
            senderDomain=None,
            uniqueKeywords=[],
        ),
        sender="Recruiting <jobs@unknown.example>",
    )

    response = client.post("/review/email_1/create-application", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "created"
    assert payload["application"]["company_name"] == "unknown.example"
    assert payload["application"]["role"] == "Role not specified"
    assert applications.created[0].company_name == "unknown.example"
    assert applications.created[0].role == "Role not specified"
    assert status_updates.created[0].new_status == "Interview"
    assert emails.emails["email_1"].processing_state == "matched"


def test_create_application_from_review_reports_duplicate_job_id() -> None:
    client, applications, emails, _ = make_client()
    applications.raise_duplicate_on_create = True

    response = client.post("/review/email_1/create-application", json={})

    assert response.status_code == 409
    assert response.json() == {
        "detail": "An application with this job ID already exists. Map the email to the existing application instead."
    }
    assert emails.emails["email_1"].processing_state == "needs_review"


def test_dismiss_review_email_marks_it_ignored() -> None:
    client, _, emails, _ = make_client()

    response = client.post(
        "/review/email_1/dismiss",
        json={"reason": "Recruiter marketing email."},
    )

    assert response.status_code == 200
    assert response.json() == {
        "action": "dismissed",
        "email_id": "email_1",
        "application": None,
        "status_update_id": None,
    }
    assert emails.emails["email_1"].processing_state == "ignored"
