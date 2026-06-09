from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient

from app.api.auth import OAUTH_STATE_COOKIE, SESSION_COOKIE
from app.core.config import Settings
from app.main import create_app
from app.models.user import GmailWatchState, GoogleUserProfile, OAuthTokenMetadata, UserRecord
from app.services.google_oauth import OAuthTokens


class FakeGoogleOAuthService:
    def __init__(self) -> None:
        self.authorization_state: str | None = None
        self.exchanged_code: str | None = None

    def authorization_url(self, state: str) -> str:
        self.authorization_state = state
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        self.exchanged_code = code
        return OAuthTokens(
            access_token="google-access-token",
            refresh_token="google-refresh-token",
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["openid", "email", "https://www.googleapis.com/auth/gmail.readonly"],
            token_type="Bearer",
        )

    async def fetch_profile(self, access_token: str) -> GoogleUserProfile:
        assert access_token == "google-access-token"
        return GoogleUserProfile(
            google_sub="google-sub-123",
            email="person@example.com",
            email_verified=True,
            name="Person Example",
        )


class FakeUsersRepository:
    def __init__(self) -> None:
        self.saved_token_metadata: OAuthTokenMetadata | None = None
        self.user: UserRecord | None = None

    async def upsert_google_user(
        self,
        profile: GoogleUserProfile,
        token_metadata: OAuthTokenMetadata,
    ) -> UserRecord:
        self.saved_token_metadata = token_metadata
        self.user = UserRecord(
            _id="user_123",
            google_sub=profile.google_sub,
            email=profile.email,
            email_verified=profile.email_verified,
            monitored_email=profile.email,
            name=profile.name,
            picture=profile.picture,
            oauth=token_metadata,
            gmail_watch=GmailWatchState(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        return self.user

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        if self.user is not None and self.user.id == user_id:
            return self.user
        return None


def make_client() -> tuple[TestClient, FakeGoogleOAuthService, FakeUsersRepository]:
    settings = Settings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        google_redirect_uri="http://testserver/auth/google/callback",
        frontend_app_url="http://localhost:3000",
        session_secret_key="session-secret-for-tests",
        token_encryption_key="token-secret-for-tests",
    )
    app = create_app(settings)
    oauth_service = FakeGoogleOAuthService()
    users_repository = FakeUsersRepository()
    app.state.google_oauth_service = oauth_service
    app.state.users_repository = users_repository
    return TestClient(app), oauth_service, users_repository


def test_google_oauth_start_redirects_and_sets_state_cookie() -> None:
    client, oauth_service, _ = make_client()

    response = client.get("/auth/google/start", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert client.cookies.get(OAUTH_STATE_COOKIE) == oauth_service.authorization_state
    assert client.cookies.get(OAUTH_STATE_COOKIE) is not None


def test_google_oauth_callback_rejects_invalid_state() -> None:
    client, _, users_repository = make_client()
    client.get("/auth/google/start", follow_redirects=False)

    response = client.get(
        "/auth/google/callback?code=auth-code&state=wrong-state",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:3000/?auth=error"
    assert client.cookies.get(SESSION_COOKIE) is None
    assert users_repository.saved_token_metadata is None


def test_google_oauth_callback_stores_encrypted_token_and_creates_session() -> None:
    client, oauth_service, users_repository = make_client()
    client.get("/auth/google/start", follow_redirects=False)
    state = client.cookies.get(OAUTH_STATE_COOKIE)

    response = client.get(
        f"/auth/google/callback?code=auth-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:3000/?auth=connected"
    assert oauth_service.exchanged_code == "auth-code"
    assert client.cookies.get(SESSION_COOKIE) is not None
    assert users_repository.saved_token_metadata is not None
    encrypted_refresh_token = users_repository.saved_token_metadata.refresh_token_encrypted
    assert encrypted_refresh_token is not None
    assert encrypted_refresh_token != "google-refresh-token"
    assert "google-refresh-token" not in response.text


def test_auth_status_returns_connection_metadata_without_tokens() -> None:
    client, _, _ = make_client()
    client.get("/auth/google/start", follow_redirects=False)
    state = client.cookies.get(OAUTH_STATE_COOKIE)
    client.get(f"/auth/google/callback?code=auth-code&state={state}", follow_redirects=False)

    response = client.get("/auth/status")

    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["authenticated"] is True
    assert payload["connected"] is True
    assert payload["email"] == "person@example.com"
    assert payload["monitored_email"] == "person@example.com"
    assert "access_token" not in str(payload)
    assert "refresh_token" not in str(payload)


def test_logout_clears_session_cookie() -> None:
    client, _, _ = make_client()
    client.get("/auth/google/start", follow_redirects=False)
    state = client.cookies.get(OAUTH_STATE_COOKIE)
    client.get(f"/auth/google/callback?code=auth-code&state={state}", follow_redirects=False)

    response = client.post("/auth/logout", follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": False,
        "connected": False,
        "email": None,
        "monitored_email": None,
        "gmail_watch": None,
    }
    assert client.cookies.get(SESSION_COOKIE) is None
