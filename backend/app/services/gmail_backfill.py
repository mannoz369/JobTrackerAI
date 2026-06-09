import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, TypeVar

from app.core.config import Settings
from app.core.security import TokenCipher
from app.models.backfill import BackfillJobCreate, BackfillJobRecord
from app.models.email import EmailRecord
from app.models.user import UserRecord
from app.repositories.applications import ApplicationsRepository
from app.repositories.backfill_jobs import BackfillJobsRepository
from app.repositories.companies import CompaniesRepository
from app.repositories.emails import EmailsRepository
from app.repositories.status_updates import StatusUpdatesRepository
from app.repositories.users import UsersRepository
from app.services.application_status import ApplicationStatusService
from app.services.email_extraction_worker import EmailExtractionWorker
from app.services.gmail_api import GmailApiClient
from app.services.gmail_sync import normalize_gmail_message
from app.services.gemini import GeminiTransientError
from app.services.google_oauth import GoogleOAuthService


class GmailBackfillError(RuntimeError):
    pass


class BackfillAlreadyRunningError(GmailBackfillError):
    pass


class BackfillTransientDependencyError(GmailBackfillError):
    pass


T = TypeVar("T")


JOB_SEARCH_TERMS: tuple[str, ...] = (
    "application",
    "applied",
    "interview",
    "assessment",
    "offer",
    "rejected",
    "rejection",
    "recruiter",
    "hiring",
    "job",
    "career",
    "careers",
)


@dataclass
class BackfillProcessingCounts:
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
    errors: list[str] = field(default_factory=list)
    pause_error: str | None = None

    def as_increments(self) -> dict[str, int]:
        return {
            "fetched_count": self.fetched_count,
            "saved_count": self.saved_count,
            "duplicate_count": self.duplicate_count,
            "processed_count": self.processed_count,
            "extracted_count": self.extracted_count,
            "non_job_count": self.non_job_count,
            "needs_review_count": self.needs_review_count,
            "failed_count": self.failed_count,
            "matched_count": self.matched_count,
            "created_count": self.created_count,
        }

    def add_error(self, exc: Exception) -> None:
        message = str(exc).strip() or exc.__class__.__name__
        self.errors.append(message)


class GmailBackfillService:
    def __init__(
        self,
        settings: Settings,
        users_repository: UsersRepository,
        backfill_jobs_repository: BackfillJobsRepository,
        emails_repository: EmailsRepository,
        applications_repository: ApplicationsRepository,
        companies_repository: CompaniesRepository,
        status_updates_repository: StatusUpdatesRepository,
        *,
        gmail_api_client: GmailApiClient | None = None,
        google_oauth_service: GoogleOAuthService | None = None,
        token_cipher: TokenCipher | None = None,
        extraction_worker: EmailExtractionWorker | None = None,
        application_status_service: ApplicationStatusService | None = None,
    ) -> None:
        self._settings = settings
        self._users_repository = users_repository
        self._backfill_jobs_repository = backfill_jobs_repository
        self._emails_repository = emails_repository
        self._gmail_api_client = gmail_api_client or GmailApiClient(settings)
        self._google_oauth_service = google_oauth_service or GoogleOAuthService(settings)
        self._token_cipher = token_cipher or TokenCipher(
            settings.token_encryption_key or settings.session_secret_key
        )
        self._extraction_worker = extraction_worker or EmailExtractionWorker(
            settings,
            emails_repository,
        )
        self._application_status_service = (
            application_status_service
            or ApplicationStatusService(
                settings,
                applications_repository,
                companies_repository,
                status_updates_repository,
                emails_repository,
            )
        )

    async def create_job_for_user(
        self,
        user: UserRecord,
        start_date: date,
    ) -> BackfillJobRecord:
        user_id = self._user_id(user)
        self._require_refresh_token(user)
        active_job = await self._backfill_jobs_repository.get_active_for_user(user_id)
        if active_job is not None:
            raise BackfillAlreadyRunningError("A backfill job is already running.")

        return await self._backfill_jobs_repository.create_job(
            BackfillJobCreate(
                user_id=user_id,
                start_date=start_date,
                gmail_query=self.gmail_query_for_start_date(start_date),
            )
        )

    async def retry_job_for_user(
        self,
        user: UserRecord,
        job_id: str,
    ) -> BackfillJobRecord:
        user_id = self._user_id(user)
        job = await self._backfill_jobs_repository.get_for_user(user_id, job_id)
        if job is None:
            raise GmailBackfillError("Backfill job was not found.")
        if job.status not in {"pending", "running", "failed"}:
            raise GmailBackfillError("Only incomplete backfill jobs can be retried.")

        active_job = await self._backfill_jobs_repository.get_active_for_user(user_id)
        if active_job is not None and active_job.id != job.id:
            raise BackfillAlreadyRunningError("A backfill job is already running.")

        refreshed_query = self.gmail_query_for_start_date(job.start_date)
        reset_query = refreshed_query if refreshed_query != job.gmail_query else None
        reset = await self._backfill_jobs_repository.reset_for_retry(
            job_id,
            gmail_query=reset_query,
        )
        if reset is None:
            raise GmailBackfillError("Backfill job was not found.")
        return reset

    async def run_job(self, job_id: str) -> BackfillJobRecord | None:
        job = await self._backfill_jobs_repository.get_by_id(job_id)
        if job is None:
            return None

        try:
            user = await self._load_user(job.user_id)
            refresh_token = self._decrypt_refresh_token(user)
            tokens = await self._google_oauth_service.refresh_access_token(refresh_token)
            running_job = await self._backfill_jobs_repository.mark_running(job_id)
            if running_job is None:
                return None
            job = running_job

            page_token = job.page_token
            while True:
                current_page_token = page_token
                response = await self._with_gmail_retries(
                    lambda: self._gmail_api_client.list_messages(
                        tokens.access_token,
                        query=job.gmail_query,
                        page_token=current_page_token,
                        max_results=self._settings.gmail_backfill_page_size,
                    ),
                    operation_name="Gmail message search",
                )
                counts = await self._process_message_ids(
                    job,
                    user,
                    tokens.access_token,
                    response.message_ids,
                )
                next_page_token = response.next_page_token
                progress_page_token = (
                    current_page_token if counts.pause_error else next_page_token
                )
                progress_error = counts.errors[0] if counts.errors else None
                if counts.pause_error:
                    progress_error = None
                await self._backfill_jobs_repository.update_progress(
                    job_id,
                    page_token=progress_page_token,
                    increments=counts.as_increments(),
                    error=progress_error,
                )
                if counts.pause_error is not None:
                    return await self._backfill_jobs_repository.mark_failed(
                        job_id,
                        counts.pause_error,
                    )
                page_token = next_page_token
                if page_token is None:
                    return await self._backfill_jobs_repository.mark_succeeded(job_id)

        except Exception as exc:
            return await self._backfill_jobs_repository.mark_failed(
                job_id,
                self._safe_error_message(exc),
            )

    async def _process_message_ids(
        self,
        job: BackfillJobRecord,
        user: UserRecord,
        access_token: str,
        message_ids: list[str],
    ) -> BackfillProcessingCounts:
        counts = BackfillProcessingCounts(fetched_count=len(message_ids))
        user_id = self._user_id(user)

        for message_id in message_ids:
            try:
                existing = await self._emails_repository.get_by_user_and_message_id(
                    user_id,
                    message_id,
                )
                if existing is not None:
                    counts.duplicate_count += 1
                    await self._process_email_if_needed(existing, counts)
                    continue

                message = await self._with_gmail_retries(
                    lambda: self._gmail_api_client.get_message(
                        access_token,
                        message_id,
                    ),
                    operation_name=f"Gmail message fetch {message_id}",
                )
                email = normalize_gmail_message(
                    user_id=user_id,
                    message=message,
                    source_history_id=f"backfill:{job.id}",
                )
                saved = await self._emails_repository.upsert_email(email)
                counts.saved_count += 1
                await self._process_email_if_needed(saved, counts)
            except BackfillTransientDependencyError as exc:
                counts.failed_count += 1
                counts.pause_error = self._safe_error_message(exc)
                counts.errors.append(counts.pause_error)
                break
            except Exception as exc:
                counts.failed_count += 1
                counts.add_error(exc)

        return counts

    async def _process_email_if_needed(
        self,
        email: EmailRecord,
        counts: BackfillProcessingCounts,
    ) -> None:
        if email.id is None:
            counts.failed_count += 1
            counts.errors.append("Persisted email was missing an id.")
            return

        email_for_status: EmailRecord | None = None
        if email.processing_state == "pending_extraction" or (
            self._is_retryable_extraction_failure(email)
        ):
            counts.processed_count += 1
            extraction_state = await self._extraction_worker.process_email(email)
            if extraction_state == "extracted":
                counts.extracted_count += 1
                email_for_status = await self._emails_repository.get_for_user(
                    email.user_id,
                    email.id,
                )
            elif extraction_state == "non_job":
                counts.non_job_count += 1
                return
            elif extraction_state == "needs_review":
                counts.needs_review_count += 1
                return
            elif extraction_state == "deferred":
                deferred_email = await self._emails_repository.get_for_user(
                    email.user_id,
                    email.id,
                )
                raise BackfillTransientDependencyError(
                    self._deferred_extraction_message(deferred_email or email)
                )
            else:
                counts.failed_count += 1
                return
        elif email.processing_state == "extracted":
            counts.processed_count += 1
            email_for_status = email
        else:
            return

        if email_for_status is None:
            counts.failed_count += 1
            counts.errors.append("Email disappeared after extraction.")
            return

        try:
            status_result = await self._application_status_service.process_email(
                email_for_status
            )
        except GeminiTransientError as exc:
            raise BackfillTransientDependencyError(
                "Gemini matching is temporarily unavailable; backfill paused. "
                f"Retry later. Last error: {self._safe_error_message(exc)}"
            ) from exc
        if status_result.action in {"status_updated", "already_processed"}:
            counts.matched_count += 1
        elif status_result.action == "application_created":
            counts.created_count += 1
        elif status_result.action == "needs_review":
            counts.needs_review_count += 1
        elif status_result.action == "ignored":
            counts.non_job_count += 1

    async def _load_user(self, user_id: str) -> UserRecord:
        user = await self._users_repository.get_by_id(user_id)
        if user is None:
            raise GmailBackfillError("Backfill user was not found.")
        return user

    def _decrypt_refresh_token(self, user: UserRecord) -> str:
        encrypted_refresh_token = self._require_refresh_token(user)
        return self._token_cipher.decrypt(encrypted_refresh_token)

    @staticmethod
    def _require_refresh_token(user: UserRecord) -> str:
        encrypted_refresh_token = user.oauth.refresh_token_encrypted
        if not encrypted_refresh_token:
            raise GmailBackfillError("User does not have a refresh token.")
        return encrypted_refresh_token

    @staticmethod
    def _user_id(user: UserRecord) -> str:
        if user.id is None:
            raise GmailBackfillError("User record did not include an id.")
        return user.id

    @staticmethod
    def gmail_query_for_start_date(start_date: date) -> str:
        inclusive_anchor = start_date - timedelta(days=1)
        terms = " OR ".join(JOB_SEARCH_TERMS)
        return f"after:{inclusive_anchor:%Y/%m/%d} ({terms})"

    @staticmethod
    def default_start_date_for_user(user: UserRecord) -> date:
        connection_time = user.oauth.last_refreshed_at or user.created_at
        if connection_time.tzinfo is None:
            connection_time = connection_time.replace(tzinfo=timezone.utc)
        return connection_time.astimezone(timezone.utc).date()

    @staticmethod
    def _is_retryable_extraction_failure(email: EmailRecord) -> bool:
        if email.processing_state != "extraction_failed" or not email.extraction_error:
            return False
        error = email.extraction_error.lower()
        return any(
            marker in error
            for marker in (
                "status 429",
                "status 500",
                "status 502",
                "status 503",
                "status 504",
                "did not complete",
                "timeout",
                "temporarily",
            )
        )

    @staticmethod
    def _deferred_extraction_message(email: EmailRecord) -> str:
        error = email.extraction_error or "temporary Gemini extraction failure"
        return (
            "Gemini extraction is temporarily unavailable; backfill paused. "
            f"Retry later. Last error: {error}"
        )

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__

    async def _with_gmail_retries(
        self,
        request_factory: Callable[[], Awaitable[T]],
        *,
        operation_name: str,
    ) -> T:
        attempts = max(1, self._settings.gmail_backfill_api_max_retries)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await request_factory()
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(
                    self._settings.gmail_backfill_api_retry_backoff_seconds * attempt
                )

        assert last_error is not None
        raise GmailBackfillError(
            f"{operation_name} failed after {attempts} attempts: "
            f"{self._safe_error_message(last_error)}"
        ) from last_error
