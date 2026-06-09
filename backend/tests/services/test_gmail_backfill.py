import asyncio
import base64
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.core.security import TokenCipher
from app.models.backfill import BackfillJobCreate, BackfillJobRecord
from app.models.email import EmailCreate, EmailRecord
from app.models.extraction import JobEmailExtraction
from app.models.user import GmailWatchState, OAuthTokenMetadata, UserRecord
from app.services.gmail_api import GmailMessageListResponse
from app.services.gmail_backfill import GmailBackfillService
from app.services.google_oauth import OAuthTokens


NOW = datetime(2026, 1, 5, tzinfo=timezone.utc)


class FakeUsersRepository:
    def __init__(self, user: UserRecord) -> None:
        self.user = user

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return self.user if self.user.id == user_id else None


class FakeBackfillJobsRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, BackfillJobRecord] = {}

    async def get_active_for_user(self, user_id: str) -> BackfillJobRecord | None:
        for job in self.jobs.values():
            if job.user_id == user_id and job.status in {"pending", "running"}:
                return job
        return None

    async def create_job(self, job: BackfillJobCreate) -> BackfillJobRecord:
        record = BackfillJobRecord.model_validate(
            {
                "_id": f"job_{len(self.jobs) + 1}",
                **job.model_dump(mode="python"),
                "created_at": NOW,
                "updated_at": NOW,
            }
        )
        self.jobs[record.id or ""] = record
        return record

    async def get_by_id(self, job_id: str) -> BackfillJobRecord | None:
        return self.jobs.get(job_id)

    async def get_for_user(
        self,
        user_id: str,
        job_id: str,
    ) -> BackfillJobRecord | None:
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def mark_running(self, job_id: str) -> BackfillJobRecord | None:
        return self._update(
            job_id,
            status="running",
            started_at=NOW,
            completed_at=None,
            last_error=None,
        )

    async def reset_for_retry(
        self,
        job_id: str,
        *,
        gmail_query: str | None = None,
    ) -> BackfillJobRecord | None:
        changes: dict[str, Any] = {
            "status": "pending",
            "completed_at": None,
            "last_error": None,
        }
        if gmail_query is not None:
            changes["gmail_query"] = gmail_query
            changes["page_token"] = None
        return self._update(job_id, **changes)

    async def update_progress(
        self,
        job_id: str,
        *,
        page_token: str | None,
        increments: dict[str, int],
        error: str | None = None,
    ) -> BackfillJobRecord | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        update: dict[str, Any] = {"page_token": page_token, "updated_at": NOW}
        for key, value in increments.items():
            update[key] = getattr(job, key) + value
        if error is not None:
            update["last_error"] = error
            update["errors"] = [*job.errors, error]
        return self._update(job_id, **update)

    async def mark_succeeded(self, job_id: str) -> BackfillJobRecord | None:
        return self._update(
            job_id,
            status="succeeded",
            page_token=None,
            completed_at=NOW,
            last_error=None,
        )

    async def mark_failed(
        self,
        job_id: str,
        error: str,
    ) -> BackfillJobRecord | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        return self._update(
            job_id,
            status="failed",
            completed_at=NOW,
            last_error=error,
            errors=[*job.errors, error],
        )

    def _update(self, job_id: str, **changes: Any) -> BackfillJobRecord | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        updated = job.model_copy(update={**changes, "updated_at": NOW})
        self.jobs[job_id] = updated
        return updated


class FakeEmailsRepository:
    def __init__(self) -> None:
        self.by_message_id: dict[str, EmailRecord] = {
            "existing-message": email_record(
                _id="email_existing",
                gmail_message_id="existing-message",
                processing_state="matched",
            )
        }
        self.by_id: dict[str, EmailRecord] = {
            email.id or "": email for email in self.by_message_id.values()
        }
        self.saved: list[EmailCreate] = []

    async def get_by_user_and_message_id(
        self,
        user_id: str,
        gmail_message_id: str,
    ) -> EmailRecord | None:
        email = self.by_message_id.get(gmail_message_id)
        if email is None or email.user_id != user_id:
            return None
        return email

    async def upsert_email(self, email: EmailCreate) -> EmailRecord:
        self.saved.append(email)
        record = email_record(
            _id=f"email_{len(self.saved)}",
            gmail_message_id=email.gmail_message_id,
            subject=email.subject,
            processing_state=email.processing_state,
        )
        self.by_message_id[email.gmail_message_id] = record
        self.by_id[record.id or ""] = record
        return record

    async def get_for_user(
        self,
        user_id: str,
        email_id: str,
    ) -> EmailRecord | None:
        email = self.by_id.get(email_id)
        if email is None or email.user_id != user_id:
            return None
        return email

    def update_email(self, email: EmailRecord) -> None:
        self.by_id[email.id or ""] = email
        self.by_message_id[email.gmail_message_id] = email


class FakeGmailApiClient:
    def __init__(self) -> None:
        self.list_calls: list[tuple[str, str, str | None, int]] = []
        self.get_calls: list[tuple[str, str]] = []

    async def list_messages(
        self,
        access_token: str,
        *,
        query: str,
        page_token: str | None = None,
        max_results: int = 25,
    ) -> GmailMessageListResponse:
        self.list_calls.append((access_token, query, page_token, max_results))
        if page_token is None:
            return GmailMessageListResponse(
                message_ids=["existing-message", "new-message"],
                next_page_token="page-2",
            )
        return GmailMessageListResponse(message_ids=[], next_page_token=None)

    async def get_message(self, access_token: str, message_id: str) -> dict[str, Any]:
        self.get_calls.append((access_token, message_id))
        return gmail_message(message_id)


class FlakyGmailApiClient(FakeGmailApiClient):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    async def list_messages(
        self,
        access_token: str,
        *,
        query: str,
        page_token: str | None = None,
        max_results: int = 25,
    ) -> GmailMessageListResponse:
        self.list_calls.append((access_token, query, page_token, max_results))
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise TimeoutError("ReadTimeout")
        return GmailMessageListResponse(message_ids=[], next_page_token=None)


class FakeGoogleOAuthService:
    def __init__(self) -> None:
        self.refresh_tokens: list[str] = []

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        self.refresh_tokens.append(refresh_token)
        return OAuthTokens(
            access_token="access-token",
            refresh_token=None,
            access_token_expires_at=NOW + timedelta(hours=1),
            scopes=[],
            token_type="Bearer",
        )


class FakeExtractionWorker:
    def __init__(self, emails: FakeEmailsRepository) -> None:
        self.emails = emails
        self.processed: list[str] = []

    async def process_email(self, email: EmailRecord) -> str:
        self.processed.append(email.gmail_message_id)
        updated = email.model_copy(
            update={
                "processing_state": "extracted",
                "extraction": extraction_payload(),
                "updated_at": NOW,
            }
        )
        self.emails.update_email(updated)
        return "extracted"


class DeferredExtractionWorker:
    def __init__(self, emails: FakeEmailsRepository) -> None:
        self.emails = emails
        self.processed: list[str] = []

    async def process_email(self, email: EmailRecord) -> str:
        self.processed.append(email.gmail_message_id)
        updated = email.model_copy(
            update={
                "processing_state": "pending_extraction",
                "extraction_error": "Gemini request failed with status 429.",
                "updated_at": NOW,
            }
        )
        self.emails.update_email(updated)
        return "deferred"


class FakeApplicationStatusService:
    def __init__(self) -> None:
        self.processed: list[str] = []

    async def process_email(self, email: EmailRecord) -> SimpleNamespace:
        self.processed.append(email.gmail_message_id)
        return SimpleNamespace(action="application_created")


def make_user(encrypted_refresh_token: str) -> UserRecord:
    return UserRecord(
        _id="user_123",
        google_sub="google-sub-123",
        email="person@example.com",
        email_verified=True,
        monitored_email="person@example.com",
        oauth=OAuthTokenMetadata(refresh_token_encrypted=encrypted_refresh_token),
        gmail_watch=GmailWatchState(),
        created_at=NOW,
        updated_at=NOW,
    )


def email_record(**overrides: Any) -> EmailRecord:
    payload: dict[str, Any] = {
        "_id": "email_1",
        "user_id": "user_123",
        "gmail_message_id": "message-1",
        "sender": "Recruiter <jobs@example.com>",
        "subject": "Application update",
        "processing_state": "pending_extraction",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return EmailRecord.model_validate(payload)


def extraction_payload() -> JobEmailExtraction:
    return JobEmailExtraction.model_validate(
        {
            "isJobRelated": True,
            "company": "Acme",
            "role": "Backend Engineer",
            "jobId": "ACME-42",
            "location": "Remote",
            "emailType": "ApplicationConfirmation",
            "statusSignal": "Applied",
            "dates": [],
            "senderDomain": "jobs.acme.example",
            "confidence": 0.95,
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
    )


def encoded_body(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def gmail_message(message_id: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "snippet": "Thanks for applying",
        "internalDate": "1767225600000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Recruiter <jobs@example.com>"},
                {"name": "Subject", "value": "Application update"},
            ],
            "body": {"data": encoded_body("Thanks for applying.")},
        },
    }


def test_backfill_fetches_search_pages_dedupes_and_processes_new_email() -> None:
    async def run() -> None:
        settings = Settings(gmail_backfill_page_size=2)
        cipher = TokenCipher(settings.session_secret_key)
        user = make_user(cipher.encrypt("refresh-token"))
        users = FakeUsersRepository(user)
        jobs = FakeBackfillJobsRepository()
        emails = FakeEmailsRepository()
        gmail = FakeGmailApiClient()
        oauth = FakeGoogleOAuthService()
        extraction_worker = FakeExtractionWorker(emails)
        status_service = FakeApplicationStatusService()
        service = GmailBackfillService(
            settings,
            users,  # type: ignore[arg-type]
            jobs,  # type: ignore[arg-type]
            emails,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            gmail_api_client=gmail,  # type: ignore[arg-type]
            google_oauth_service=oauth,  # type: ignore[arg-type]
            token_cipher=cipher,
            extraction_worker=extraction_worker,  # type: ignore[arg-type]
            application_status_service=status_service,  # type: ignore[arg-type]
        )

        job = await service.create_job_for_user(user, date(2026, 1, 1))
        result = await service.run_job(job.id or "")

        assert result is not None
        assert result.status == "succeeded"
        assert result.gmail_query == (
            "after:2025/12/31 (application OR applied OR interview OR "
            "assessment OR offer OR rejected OR rejection OR recruiter OR hiring "
            "OR job OR career OR careers)"
        )
        assert result.fetched_count == 2
        assert result.saved_count == 1
        assert result.duplicate_count == 1
        assert result.processed_count == 1
        assert result.extracted_count == 1
        assert result.created_count == 1
        assert oauth.refresh_tokens == ["refresh-token"]
        assert gmail.list_calls == [
            ("access-token", result.gmail_query, None, 2),
            ("access-token", result.gmail_query, "page-2", 2),
        ]
        assert gmail.get_calls == [("access-token", "new-message")]
        assert extraction_worker.processed == ["new-message"]
        assert status_service.processed == ["new-message"]

    asyncio.run(run())


def test_backfill_retries_transient_gmail_search_timeout() -> None:
    async def run() -> None:
        settings = Settings(
            gmail_backfill_page_size=2,
            gmail_backfill_api_max_retries=2,
            gmail_backfill_api_retry_backoff_seconds=0,
        )
        cipher = TokenCipher(settings.session_secret_key)
        user = make_user(cipher.encrypt("refresh-token"))
        users = FakeUsersRepository(user)
        jobs = FakeBackfillJobsRepository()
        emails = FakeEmailsRepository()
        gmail = FlakyGmailApiClient()
        service = GmailBackfillService(
            settings,
            users,  # type: ignore[arg-type]
            jobs,  # type: ignore[arg-type]
            emails,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            gmail_api_client=gmail,  # type: ignore[arg-type]
            google_oauth_service=FakeGoogleOAuthService(),  # type: ignore[arg-type]
            token_cipher=cipher,
            extraction_worker=FakeExtractionWorker(emails),  # type: ignore[arg-type]
            application_status_service=FakeApplicationStatusService(),  # type: ignore[arg-type]
        )

        job = await service.create_job_for_user(user, date(2026, 1, 1))
        result = await service.run_job(job.id or "")

        assert result is not None
        assert result.status == "succeeded"
        assert len(gmail.list_calls) == 2
        assert result.failed_count == 0

    asyncio.run(run())


def test_backfill_pauses_on_deferred_extraction_without_advancing_page() -> None:
    async def run() -> None:
        settings = Settings(gmail_backfill_page_size=2)
        cipher = TokenCipher(settings.session_secret_key)
        user = make_user(cipher.encrypt("refresh-token"))
        users = FakeUsersRepository(user)
        jobs = FakeBackfillJobsRepository()
        emails = FakeEmailsRepository()
        gmail = FakeGmailApiClient()
        extraction_worker = DeferredExtractionWorker(emails)
        service = GmailBackfillService(
            settings,
            users,  # type: ignore[arg-type]
            jobs,  # type: ignore[arg-type]
            emails,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            gmail_api_client=gmail,  # type: ignore[arg-type]
            google_oauth_service=FakeGoogleOAuthService(),  # type: ignore[arg-type]
            token_cipher=cipher,
            extraction_worker=extraction_worker,  # type: ignore[arg-type]
            application_status_service=FakeApplicationStatusService(),  # type: ignore[arg-type]
        )

        job = await service.create_job_for_user(user, date(2026, 1, 1))
        result = await service.run_job(job.id or "")

        assert result is not None
        assert result.status == "failed"
        assert result.page_token is None
        assert result.fetched_count == 2
        assert result.saved_count == 1
        assert result.duplicate_count == 1
        assert result.processed_count == 1
        assert result.failed_count == 1
        assert result.last_error is not None
        assert "temporarily unavailable" in result.last_error
        assert extraction_worker.processed == ["new-message"]

    asyncio.run(run())


def test_backfill_reprocesses_retryable_extraction_failures() -> None:
    async def run() -> None:
        settings = Settings(gmail_backfill_page_size=2)
        cipher = TokenCipher(settings.session_secret_key)
        user = make_user(cipher.encrypt("refresh-token"))
        users = FakeUsersRepository(user)
        jobs = FakeBackfillJobsRepository()
        emails = FakeEmailsRepository()
        retryable_existing = email_record(
            _id="email_existing",
            gmail_message_id="existing-message",
            processing_state="extraction_failed",
            extraction_error="Gemini request failed with status 429.",
        )
        emails.update_email(retryable_existing)
        extraction_worker = FakeExtractionWorker(emails)
        status_service = FakeApplicationStatusService()
        service = GmailBackfillService(
            settings,
            users,  # type: ignore[arg-type]
            jobs,  # type: ignore[arg-type]
            emails,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            gmail_api_client=FakeGmailApiClient(),  # type: ignore[arg-type]
            google_oauth_service=FakeGoogleOAuthService(),  # type: ignore[arg-type]
            token_cipher=cipher,
            extraction_worker=extraction_worker,  # type: ignore[arg-type]
            application_status_service=status_service,  # type: ignore[arg-type]
        )

        job = await service.create_job_for_user(user, date(2026, 1, 1))
        result = await service.run_job(job.id or "")

        assert result is not None
        assert result.status == "succeeded"
        assert result.duplicate_count == 1
        assert result.processed_count == 2
        assert result.extracted_count == 2
        assert extraction_worker.processed == ["existing-message", "new-message"]
        assert status_service.processed == ["existing-message", "new-message"]

    asyncio.run(run())
