from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.core.config import Settings
from app.core.security import SessionSigner
from app.main import create_app
from app.models.backfill import BackfillJobRecord
from app.models.user import GmailWatchState, OAuthTokenMetadata, UserRecord


NOW = datetime(2026, 1, 5, tzinfo=timezone.utc)


class FakeUsersRepository:
    def __init__(self, user: UserRecord) -> None:
        self.user = user

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return self.user if self.user.id == user_id else None


class FakeBackfillJobsRepository:
    def __init__(self, latest_job: BackfillJobRecord | None = None) -> None:
        self.latest_job = latest_job

    async def get_active_for_user(self, user_id: str) -> BackfillJobRecord | None:
        if (
            self.latest_job is not None
            and self.latest_job.user_id == user_id
            and self.latest_job.status in {"pending", "running"}
        ):
            return self.latest_job
        return None

    async def get_latest_for_user(self, user_id: str) -> BackfillJobRecord | None:
        if self.latest_job is not None and self.latest_job.user_id == user_id:
            return self.latest_job
        return None

    async def get_for_user(
        self,
        user_id: str,
        job_id: str,
    ) -> BackfillJobRecord | None:
        if (
            self.latest_job is not None
            and self.latest_job.user_id == user_id
            and self.latest_job.id == job_id
        ):
            return self.latest_job
        return None


class FakeGmailBackfillService:
    def __init__(self, job: BackfillJobRecord) -> None:
        self.job = job
        self.created_start_dates: list[date] = []
        self.run_calls: list[str] = []

    async def create_job_for_user(
        self,
        user: UserRecord,
        start_date: date,
    ) -> BackfillJobRecord:
        self.created_start_dates.append(start_date)
        return self.job

    async def retry_job_for_user(
        self,
        user: UserRecord,
        job_id: str,
    ) -> BackfillJobRecord:
        self.retried_job_id = job_id
        return self.job

    async def run_job(self, job_id: str) -> None:
        self.run_calls.append(job_id)


def make_user() -> UserRecord:
    return UserRecord(
        _id="user_123",
        google_sub="google-sub-123",
        email="person@example.com",
        email_verified=True,
        monitored_email="person@example.com",
        oauth=OAuthTokenMetadata(
            refresh_token_encrypted="encrypted-refresh-token",
            last_refreshed_at=datetime(2026, 1, 4, 14, 30, tzinfo=timezone.utc),
        ),
        gmail_watch=GmailWatchState(),
        created_at=NOW,
        updated_at=NOW,
    )


def backfill_job(**overrides: object) -> BackfillJobRecord:
    payload = {
        "_id": "job_1",
        "user_id": "user_123",
        "start_date": date(2026, 1, 1),
        "status": "succeeded",
        "gmail_query": "after:2025/12/31",
        "fetched_count": 4,
        "saved_count": 2,
        "duplicate_count": 1,
        "processed_count": 2,
        "extracted_count": 2,
        "non_job_count": 0,
        "needs_review_count": 1,
        "failed_count": 0,
        "matched_count": 1,
        "created_count": 1,
        "errors": [],
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return BackfillJobRecord.model_validate(payload)


def make_client(
    *,
    latest_job: BackfillJobRecord | None = None,
    gmail_backfill_service: FakeGmailBackfillService | None = None,
) -> tuple[TestClient, FakeGmailBackfillService | None, Settings]:
    settings = Settings(session_secret_key="session-secret-for-tests")
    app = create_app(settings)
    app.state.users_repository = FakeUsersRepository(make_user())
    app.state.backfill_jobs_repository = FakeBackfillJobsRepository(latest_job)
    if gmail_backfill_service is not None:
        app.state.gmail_backfill_service = gmail_backfill_service
    client = TestClient(app)
    session_token = SessionSigner(settings.session_secret_key).create_session(
        user_id="user_123",
        email="person@example.com",
        max_age_seconds=3600,
    )
    client.cookies.set(SESSION_COOKIE, session_token)
    return client, gmail_backfill_service, settings


def test_backfill_status_requires_session() -> None:
    settings = Settings(session_secret_key="session-secret-for-tests")
    client = TestClient(create_app(settings))

    response = client.get("/backfill/status")

    assert response.status_code == 401


def test_backfill_status_returns_default_date_and_latest_job() -> None:
    client, _, _ = make_client(latest_job=backfill_job())

    response = client.get("/backfill/status")

    assert response.status_code == 200
    assert response.json()["default_start_date"] == "2026-01-04"
    assert response.json()["active_job"] is None
    assert response.json()["latest_job"]["id"] == "job_1"
    assert response.json()["latest_job"]["fetched_count"] == 4


def test_start_backfill_creates_job_and_schedules_background_run() -> None:
    service = FakeGmailBackfillService(backfill_job(status="pending"))
    client, gmail_backfill_service, _ = make_client(
        latest_job=None,
        gmail_backfill_service=service,
    )

    response = client.post("/backfill/jobs", json={"start_date": "2026-01-01"})

    assert response.status_code == 201
    assert response.json()["id"] == "job_1"
    assert gmail_backfill_service is not None
    assert gmail_backfill_service.created_start_dates == [date(2026, 1, 1)]
    assert gmail_backfill_service.run_calls == ["job_1"]


def test_retry_backfill_schedules_background_run() -> None:
    service = FakeGmailBackfillService(backfill_job(status="pending"))
    client, gmail_backfill_service, _ = make_client(
        latest_job=backfill_job(status="pending"),
        gmail_backfill_service=service,
    )

    response = client.post("/backfill/jobs/job_1/retry")

    assert response.status_code == 200
    assert response.json()["id"] == "job_1"
    assert gmail_backfill_service is not None
    assert gmail_backfill_service.retried_job_id == "job_1"
    assert gmail_backfill_service.run_calls == ["job_1"]
