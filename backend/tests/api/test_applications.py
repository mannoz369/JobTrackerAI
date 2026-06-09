from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from app.api.auth import SESSION_COOKIE
from app.core.config import Settings
from app.core.security import SessionSigner
from app.main import create_app
from app.models.application import ApplicationRecord
from app.models.status_update import StatusUpdateCreate, StatusUpdateRecord
from app.models.user import GmailWatchState, OAuthTokenMetadata, UserRecord


NOW = datetime(2026, 1, 4, tzinfo=timezone.utc)


class FakeUsersRepository:
    def __init__(self, user: UserRecord) -> None:
        self.user = user

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return self.user if self.user.id == user_id else None


class FakeApplicationsRepository:
    def __init__(self) -> None:
        self.applications = {
            "app_1": application_record(
                _id="app_1",
                company_name="Acme",
                role="Backend Engineer",
                current_status="Applied",
            ),
            "app_2": application_record(
                _id="app_2",
                company_name="BrightDesk",
                role="Platform Engineer",
                current_status="Interview",
            ),
            "other_app": application_record(
                _id="other_app",
                user_id="other_user",
                company_name="Hidden Co",
                role="Staff Engineer",
                current_status="Offer",
            ),
        }

    async def count_by_status(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for application in self.applications.values():
            if application.user_id != user_id:
                continue
            counts[application.current_status] = counts.get(application.current_status, 0) + 1
        return counts

    async def list_for_user(
        self,
        user_id: str,
        *,
        statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[ApplicationRecord]:
        records = [
            application
            for application in self.applications.values()
            if application.user_id == user_id
            and (not statuses or application.current_status in statuses)
        ]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)[:limit]

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

    async def delete_for_user(
        self,
        user_id: str,
        application_id: str,
    ) -> bool:
        application = await self.get_for_user(user_id, application_id)
        if application is None:
            return False
        del self.applications[application_id]
        return True


class FakeStatusUpdatesRepository:
    def __init__(self) -> None:
        self.created: list[StatusUpdateRecord] = []
        self.deleted_for_application: list[tuple[str, str]] = []

    async def list_for_application(
        self,
        user_id: str,
        application_id: str,
        *,
        limit: int = 50,
    ) -> list[StatusUpdateRecord]:
        return [
            update
            for update in self.created
            if update.user_id == user_id and update.application_id == application_id
        ][:limit]

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

    async def delete_for_application(
        self,
        user_id: str,
        application_id: str,
    ) -> int:
        self.deleted_for_application.append((user_id, application_id))
        before = len(self.created)
        self.created = [
            update
            for update in self.created
            if not (
                update.user_id == user_id
                and update.application_id == application_id
            )
        ]
        return before - len(self.created)


class FakeEmailsRepository:
    def __init__(self) -> None:
        self.cleared_application_ids: list[tuple[str, str]] = []

    async def count_needs_review(self, user_id: str) -> int:
        return 2 if user_id == "user_123" else 0

    async def clear_application_links_for_user(
        self,
        user_id: str,
        application_id: str,
    ) -> int:
        self.cleared_application_ids.append((user_id, application_id))
        return 2


class FakeCompaniesRepository:
    pass


def make_client() -> tuple[
    TestClient,
    FakeApplicationsRepository,
    FakeStatusUpdatesRepository,
    FakeEmailsRepository,
]:
    settings = Settings(session_secret_key="session-secret-for-tests")
    app = create_app(settings)
    applications = FakeApplicationsRepository()
    status_updates = FakeStatusUpdatesRepository()
    emails = FakeEmailsRepository()
    app.state.users_repository = FakeUsersRepository(make_user())
    app.state.applications_repository = applications
    app.state.status_updates_repository = status_updates
    app.state.emails_repository = emails
    app.state.companies_repository = FakeCompaniesRepository()
    client = TestClient(app)
    session_token = SessionSigner(settings.session_secret_key).create_session(
        user_id="user_123",
        email="person@example.com",
        max_age_seconds=3600,
    )
    client.cookies.set(SESSION_COOKIE, session_token)
    return client, applications, status_updates, emails


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
        "normalized_keywords": [],
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return ApplicationRecord.model_validate(payload)


def test_application_overview_requires_session() -> None:
    settings = Settings(session_secret_key="session-secret-for-tests")
    client = TestClient(create_app(settings))

    response = client.get("/applications/overview")

    assert response.status_code == 401


def test_application_overview_returns_scoped_primary_status_counts() -> None:
    client, _, _, _ = make_client()

    response = client.get("/applications/overview")

    assert response.status_code == 200
    payload = response.json()
    counts = {item["status"]: item["count"] for item in payload["status_counts"]}
    assert payload["total"] == 2
    assert payload["review_queue_count"] == 2
    assert counts == {
        "Applied": 1,
        "Reviewing": 0,
        "Assessment": 0,
        "Interview": 1,
        "Rejected": 0,
        "Offer": 0,
    }
    assert [item["id"] for item in payload["recent_applications"]] == [
        "app_1",
        "app_2",
    ]


def test_application_status_edit_writes_manual_history() -> None:
    client, applications, status_updates, _ = make_client()

    response = client.patch(
        "/applications/app_1/status",
        json={"status": "Interview", "explanation": "Recruiter scheduled a call."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["application"]["current_status"] == "Interview"
    assert applications.applications["app_1"].current_status == "Interview"
    assert len(status_updates.created) == 1
    assert status_updates.created[0].previous_status == "Applied"
    assert status_updates.created[0].new_status == "Interview"
    assert status_updates.created[0].source == "manual"


def test_delete_application_removes_owned_application_and_cleans_references() -> None:
    client, applications, status_updates, emails = make_client()
    status_updates.created = [
        StatusUpdateRecord.model_validate(
            {
                "_id": "status_update_1",
                "user_id": "user_123",
                "application_id": "app_1",
                "email_id": "email_1",
                "previous_status": None,
                "new_status": "Applied",
                "source": "manual",
                "created_at": NOW,
            }
        )
    ]

    response = client.delete("/applications/app_1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "app_1",
        "deleted": True,
        "deleted_status_updates": 1,
        "relinked_review_emails": 2,
    }
    assert "app_1" not in applications.applications
    assert emails.cleared_application_ids == [("user_123", "app_1")]
    assert status_updates.deleted_for_application == [("user_123", "app_1")]


def test_delete_application_does_not_delete_other_users_application() -> None:
    client, applications, _, emails = make_client()

    response = client.delete("/applications/other_app")

    assert response.status_code == 404
    assert "other_app" in applications.applications
    assert emails.cleared_application_ids == []
