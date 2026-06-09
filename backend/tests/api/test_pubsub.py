import base64
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.user import GmailWatchState, OAuthTokenMetadata, UserRecord


class FakeUsersRepository:
    def __init__(self, user: UserRecord | None) -> None:
        self.user = user
        self.lookup_email: str | None = None

    async def get_by_monitored_email(self, monitored_email: str) -> UserRecord | None:
        self.lookup_email = monitored_email
        return self.user


class FakeGmailSyncService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def sync_user_history(
        self,
        user: UserRecord,
        notification_history_id: str | None = None,
    ) -> None:
        assert user.id is not None
        assert notification_history_id is not None
        self.calls.append((user.id, notification_history_id))


def make_user() -> UserRecord:
    now = datetime.now(timezone.utc)
    return UserRecord(
        _id="user_123",
        google_sub="google-sub-123",
        email="person@example.com",
        email_verified=True,
        monitored_email="person@example.com",
        oauth=OAuthTokenMetadata(refresh_token_encrypted="encrypted-refresh-token"),
        gmail_watch=GmailWatchState(history_id="history-1"),
        created_at=now,
        updated_at=now,
    )


def make_client(
    user: UserRecord | None = None,
) -> tuple[TestClient, FakeUsersRepository, FakeGmailSyncService]:
    settings = Settings(
        gmail_pubsub_subscription="projects/project-1/subscriptions/gmail",
        gmail_pubsub_verification_token="push-token",
    )
    app = create_app(settings)
    users_repository = FakeUsersRepository(user)
    gmail_sync_service = FakeGmailSyncService()
    app.state.users_repository = users_repository
    app.state.gmail_sync_service = gmail_sync_service
    return TestClient(app), users_repository, gmail_sync_service


def gmail_push_payload(
    *,
    email_address: str = "Person@Example.com",
    history_id: str = "history-99",
    subscription: str = "projects/project-1/subscriptions/gmail",
) -> dict[str, object]:
    data = base64.urlsafe_b64encode(
        json.dumps(
            {
                "emailAddress": email_address,
                "historyId": history_id,
            }
        ).encode("utf-8")
    ).decode("ascii")
    return {
        "message": {
            "data": data,
            "messageId": "pubsub-message-1",
        },
        "subscription": subscription,
    }


def test_gmail_pubsub_webhook_acknowledges_and_schedules_sync() -> None:
    client, users_repository, gmail_sync_service = make_client(make_user())

    response = client.post(
        "/pubsub/gmail?token=push-token",
        json=gmail_push_payload(),
    )

    assert response.status_code == 204
    assert users_repository.lookup_email == "person@example.com"
    assert gmail_sync_service.calls == [("user_123", "history-99")]


def test_gmail_pubsub_webhook_acknowledges_unknown_users_without_sync() -> None:
    client, users_repository, gmail_sync_service = make_client(None)

    response = client.post(
        "/pubsub/gmail?token=push-token",
        json=gmail_push_payload(),
    )

    assert response.status_code == 204
    assert users_repository.lookup_email == "person@example.com"
    assert gmail_sync_service.calls == []


def test_gmail_pubsub_webhook_rejects_invalid_push_payload() -> None:
    client, _, gmail_sync_service = make_client(make_user())

    response = client.post(
        "/pubsub/gmail?token=push-token",
        json={"message": {"data": "not-base64"}},
    )

    assert response.status_code == 400
    assert gmail_sync_service.calls == []


def test_gmail_pubsub_webhook_rejects_subscription_mismatch() -> None:
    client, _, gmail_sync_service = make_client(make_user())

    response = client.post(
        "/pubsub/gmail?token=push-token",
        json=gmail_push_payload(subscription="projects/project-1/subscriptions/other"),
    )

    assert response.status_code == 400
    assert gmail_sync_service.calls == []
