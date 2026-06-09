import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import Settings
from app.core.security import TokenCipher
from app.models.user import GmailWatchState, OAuthTokenMetadata, UserRecord
from app.services.gmail_api import GmailWatchRegistration
from app.services.gmail_watch import GmailWatchService
from app.services.google_oauth import OAuthTokens


class FakeGoogleOAuthService:
    def __init__(self) -> None:
        self.refresh_token: str | None = None

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        self.refresh_token = refresh_token
        return OAuthTokens(
            access_token="access-token",
            refresh_token=None,
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=[],
            token_type="Bearer",
        )


class FakeGmailApiClient:
    def __init__(self, expiration: datetime) -> None:
        self.expiration = expiration
        self.access_token: str | None = None

    async def watch_mailbox(self, access_token: str) -> GmailWatchRegistration:
        self.access_token = access_token
        return GmailWatchRegistration(
            history_id="history-123",
            expiration=self.expiration,
        )


class FakeUsersRepository:
    def __init__(self, users: list[UserRecord] | None = None) -> None:
        self.users = users or []
        self.renew_before: datetime | None = None
        self.updated: list[tuple[str, GmailWatchState]] = []

    async def update_gmail_watch_state(
        self,
        user_id: str,
        gmail_watch: GmailWatchState,
    ) -> UserRecord | None:
        self.updated.append((user_id, gmail_watch))
        return None

    async def list_users_needing_watch_renewal(
        self,
        renew_before: datetime,
    ) -> list[UserRecord]:
        self.renew_before = renew_before
        return self.users


def make_user(encrypted_refresh_token: str) -> UserRecord:
    return UserRecord(
        _id="user_123",
        google_sub="google-sub-123",
        email="person@example.com",
        email_verified=True,
        monitored_email="person@example.com",
        oauth=OAuthTokenMetadata(refresh_token_encrypted=encrypted_refresh_token),
        gmail_watch=GmailWatchState(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_settings() -> Settings:
    return Settings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        gmail_pubsub_topic="projects/project-1/topics/gmail",
        session_secret_key="session-secret-for-tests",
    )


def test_register_watch_refreshes_token_and_stores_watch_metadata() -> None:
    async def run() -> None:
        settings = make_settings()
        cipher = TokenCipher(settings.session_secret_key)
        user = make_user(cipher.encrypt("refresh-token"))
        expiration = datetime(2026, 1, 2, tzinfo=timezone.utc)
        users_repository = FakeUsersRepository()
        oauth_service = FakeGoogleOAuthService()
        gmail_api_client = FakeGmailApiClient(expiration)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)

        service = GmailWatchService(
            settings,
            users_repository,  # type: ignore[arg-type]
            gmail_api_client=gmail_api_client,  # type: ignore[arg-type]
            google_oauth_service=oauth_service,  # type: ignore[arg-type]
            token_cipher=cipher,
            now=lambda: now,
        )
        watch_state = await service.register_watch(user)

        assert oauth_service.refresh_token == "refresh-token"
        assert gmail_api_client.access_token == "access-token"
        assert watch_state.status == "registered"
        assert watch_state.history_id == "history-123"
        assert watch_state.expiration == expiration
        assert watch_state.topic_name == "projects/project-1/topics/gmail"
        assert watch_state.last_registered_at == now
        assert users_repository.updated == [("user_123", watch_state)]

    asyncio.run(run())


def test_renew_due_watches_uses_configured_renewal_window() -> None:
    async def run() -> None:
        settings = make_settings()
        settings.gmail_watch_renewal_window_seconds = 3600
        cipher = TokenCipher(settings.session_secret_key)
        user = make_user(cipher.encrypt("refresh-token"))
        users_repository = FakeUsersRepository([user])
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)

        service = GmailWatchService(
            settings,
            users_repository,  # type: ignore[arg-type]
            gmail_api_client=FakeGmailApiClient(now + timedelta(days=1)),  # type: ignore[arg-type]
            google_oauth_service=FakeGoogleOAuthService(),  # type: ignore[arg-type]
            token_cipher=cipher,
            now=lambda: now,
        )

        renewed = await service.renew_due_watches()

        assert len(renewed) == 1
        assert users_repository.renew_before == now + timedelta(hours=1)

    asyncio.run(run())
