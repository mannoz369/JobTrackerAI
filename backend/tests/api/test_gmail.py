from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.core.config import Settings
from app.core.security import SessionSigner
from app.main import create_app
from app.models.user import GmailWatchState, OAuthTokenMetadata, UserRecord


class FakeUsersRepository:
    def __init__(self, user: UserRecord | None) -> None:
        self.user = user
        self.loaded_user_id: str | None = None

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        self.loaded_user_id = user_id
        if self.user is not None and self.user.id == user_id:
            return self.user
        return None


class FakeGmailWatchService:
    def __init__(self) -> None:
        self.registered_user_id: str | None = None

    async def register_watch(self, user: UserRecord) -> GmailWatchState:
        self.registered_user_id = user.id
        return GmailWatchState(
            status="registered",
            history_id="history-123",
            expiration=datetime(2026, 1, 2, tzinfo=timezone.utc),
            topic_name="projects/project-1/topics/gmail",
            last_registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def make_user() -> UserRecord:
    now = datetime.now(timezone.utc)
    return UserRecord(
        _id="user_123",
        google_sub="google-sub-123",
        email="person@example.com",
        email_verified=True,
        monitored_email="person@example.com",
        oauth=OAuthTokenMetadata(refresh_token_encrypted="encrypted-refresh-token"),
        gmail_watch=GmailWatchState(),
        created_at=now,
        updated_at=now,
    )


def make_client(
    user: UserRecord | None,
) -> tuple[TestClient, FakeUsersRepository, FakeGmailWatchService, Settings]:
    settings = Settings(session_secret_key="session-secret-for-tests")
    app = create_app(settings)
    users_repository = FakeUsersRepository(user)
    gmail_watch_service = FakeGmailWatchService()
    app.state.users_repository = users_repository
    app.state.gmail_watch_service = gmail_watch_service
    return TestClient(app), users_repository, gmail_watch_service, settings


def test_register_gmail_watch_requires_session() -> None:
    client, _, gmail_watch_service, _ = make_client(make_user())

    response = client.post("/gmail/watch/register")

    assert response.status_code == 401
    assert gmail_watch_service.registered_user_id is None


def test_register_gmail_watch_registers_watch_for_authenticated_user() -> None:
    user = make_user()
    client, users_repository, gmail_watch_service, settings = make_client(user)
    session_token = SessionSigner(settings.session_secret_key).create_session(
        user_id="user_123",
        email="person@example.com",
        max_age_seconds=3600,
    )
    client.cookies.set(SESSION_COOKIE, session_token)

    response = client.post("/gmail/watch/register")

    assert response.status_code == 200
    assert users_repository.loaded_user_id == "user_123"
    assert gmail_watch_service.registered_user_id == "user_123"
    assert response.json() == {
        "status": "registered",
        "history_id": "history-123",
        "expiration": "2026-01-02T00:00:00Z",
        "topic_name": "projects/project-1/topics/gmail",
        "last_registered_at": "2026-01-01T00:00:00Z",
    }
