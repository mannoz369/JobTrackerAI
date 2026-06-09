import asyncio
import base64
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import Settings
from app.core.security import TokenCipher
from app.models.email import EmailCreate
from app.models.user import GmailWatchState, OAuthTokenMetadata, UserRecord
from app.services.gmail_api import GmailHistoryResponse
from app.services.gmail_sync import GmailSyncService
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
    def __init__(self, message: dict[str, Any]) -> None:
        self.message = message
        self.list_history_calls: list[tuple[str, str]] = []
        self.get_message_calls: list[tuple[str, str]] = []

    async def list_history(
        self,
        access_token: str,
        start_history_id: str,
    ) -> GmailHistoryResponse:
        self.list_history_calls.append((access_token, start_history_id))
        return GmailHistoryResponse(
            history=[
                {
                    "messagesAdded": [
                        {"message": {"id": "message-1"}},
                        {"message": {"id": "message-1"}},
                    ]
                }
            ],
            history_id="history-12",
        )

    async def get_message(self, access_token: str, message_id: str) -> dict[str, Any]:
        self.get_message_calls.append((access_token, message_id))
        return self.message


class FakeUsersRepository:
    def __init__(self) -> None:
        self.updated_history: list[tuple[str, str]] = []

    async def update_last_processed_history_id(
        self,
        user_id: str,
        history_id: str,
    ) -> UserRecord | None:
        self.updated_history.append((user_id, history_id))
        return None


class FakeEmailsRepository:
    def __init__(self) -> None:
        self.saved: list[EmailCreate] = []

    async def upsert_email(self, email: EmailCreate) -> None:
        self.saved.append(email)


def make_user(
    encrypted_refresh_token: str,
    *,
    history_id: str | None = "history-10",
) -> UserRecord:
    now = datetime.now(timezone.utc)
    return UserRecord(
        _id="user_123",
        google_sub="google-sub-123",
        email="person@example.com",
        email_verified=True,
        monitored_email="person@example.com",
        oauth=OAuthTokenMetadata(refresh_token_encrypted=encrypted_refresh_token),
        gmail_watch=GmailWatchState(history_id=history_id),
        created_at=now,
        updated_at=now,
    )


def make_settings() -> Settings:
    return Settings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        session_secret_key="session-secret-for-tests",
    )


def encoded_body(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def gmail_message() -> dict[str, Any]:
    return {
        "id": "message-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX", "IMPORTANT"],
        "snippet": "Thanks for applying",
        "internalDate": "1767225600000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Recruiter <recruiter@example.com>"},
                {"name": "To", "value": "Person <person@example.com>"},
                {"name": "Cc", "value": "Hiring <hiring@example.com>"},
                {"name": "Subject", "value": "Application update"},
                {"name": "Date", "value": "Fri, 02 Jan 2026 10:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": encoded_body(
                            " Thanks for applying. \r\n\r\n We will follow up soon. "
                        )
                    },
                }
            ],
        },
    }


def test_sync_user_history_fetches_messages_and_saves_normalized_email() -> None:
    async def run() -> None:
        settings = make_settings()
        cipher = TokenCipher(settings.session_secret_key)
        users_repository = FakeUsersRepository()
        emails_repository = FakeEmailsRepository()
        oauth_service = FakeGoogleOAuthService()
        gmail_api_client = FakeGmailApiClient(gmail_message())
        user = make_user(cipher.encrypt("refresh-token"))

        service = GmailSyncService(
            settings,
            users_repository,  # type: ignore[arg-type]
            emails_repository,  # type: ignore[arg-type]
            gmail_api_client=gmail_api_client,  # type: ignore[arg-type]
            google_oauth_service=oauth_service,  # type: ignore[arg-type]
            token_cipher=cipher,
        )
        result = await service.sync_user_history(user, "history-99")

        assert oauth_service.refresh_token == "refresh-token"
        assert gmail_api_client.list_history_calls == [("access-token", "history-10")]
        assert gmail_api_client.get_message_calls == [("access-token", "message-1")]
        assert result.changed_message_ids == ["message-1"]
        assert result.saved_message_ids == ["message-1"]
        assert users_repository.updated_history == [("user_123", "history-99")]
        assert len(emails_repository.saved) == 1

        saved = emails_repository.saved[0]
        assert saved.user_id == "user_123"
        assert saved.gmail_message_id == "message-1"
        assert saved.thread_id == "thread-1"
        assert saved.sender == "Recruiter <recruiter@example.com>"
        assert saved.recipients == ["person@example.com", "hiring@example.com"]
        assert saved.subject == "Application update"
        assert saved.labels == ["INBOX", "IMPORTANT"]
        assert saved.snippet == "Thanks for applying"
        assert saved.body_text == "Thanks for applying.\nWe will follow up soon."
        assert saved.source_history_id == "history-99"

    asyncio.run(run())


def test_sync_user_history_without_start_history_advances_cursor_only() -> None:
    async def run() -> None:
        settings = make_settings()
        cipher = TokenCipher(settings.session_secret_key)
        users_repository = FakeUsersRepository()
        emails_repository = FakeEmailsRepository()
        gmail_api_client = FakeGmailApiClient(gmail_message())
        user = make_user(cipher.encrypt("refresh-token"), history_id=None)

        service = GmailSyncService(
            settings,
            users_repository,  # type: ignore[arg-type]
            emails_repository,  # type: ignore[arg-type]
            gmail_api_client=gmail_api_client,  # type: ignore[arg-type]
            google_oauth_service=FakeGoogleOAuthService(),  # type: ignore[arg-type]
            token_cipher=cipher,
        )
        result = await service.sync_user_history(user, "history-99")

        assert result.changed_message_ids == []
        assert result.saved_message_ids == []
        assert gmail_api_client.list_history_calls == []
        assert emails_repository.saved == []
        assert users_repository.updated_history == [("user_123", "history-99")]

    asyncio.run(run())
