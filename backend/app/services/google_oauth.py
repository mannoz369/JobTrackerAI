from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.models.user import GoogleUserProfile


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"
GMAIL_OAUTH_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class OAuthConfigurationError(RuntimeError):
    pass


class GoogleOAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    access_token_expires_at: datetime | None
    scopes: list[str]
    token_type: str | None


class GoogleOAuthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authorization_url(self, state: str) -> str:
        self._require_config()
        query = urlencode(
            {
                "client_id": self._settings.google_client_id,
                "redirect_uri": self._settings.google_redirect_uri,
                "response_type": "code",
                "scope": " ".join(GMAIL_OAUTH_SCOPES),
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
        )
        return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        self._require_config()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": self._settings.google_client_id,
                    "client_secret": self._settings.google_client_secret,
                    "redirect_uri": self._settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code >= 400:
            raise GoogleOAuthError("Google rejected the OAuth authorization code.")

        payload = response.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise GoogleOAuthError("Google token response did not include access_token.")

        expires_at = self._expires_at(payload)
        scopes = str(payload.get("scope") or " ".join(GMAIL_OAUTH_SCOPES)).split()
        return OAuthTokens(
            access_token=access_token,
            refresh_token=payload.get("refresh_token"),
            access_token_expires_at=expires_at,
            scopes=scopes,
            token_type=payload.get("token_type"),
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        self._require_config()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": self._settings.google_client_id,
                    "client_secret": self._settings.google_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code >= 400:
            raise GoogleOAuthError("Google rejected the OAuth refresh token.")

        payload = response.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise GoogleOAuthError("Google refresh response did not include access_token.")

        expires_at = self._expires_at(payload)
        scopes = str(payload.get("scope") or "").split()
        return OAuthTokens(
            access_token=access_token,
            refresh_token=None,
            access_token_expires_at=expires_at,
            scopes=scopes,
            token_type=payload.get("token_type"),
        )

    async def fetch_profile(self, access_token: str) -> GoogleUserProfile:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
        if response.status_code >= 400:
            raise GoogleOAuthError("Google userinfo request failed.")

        payload = response.json()
        subject = payload.get("sub")
        email = payload.get("email")
        if not subject or not email:
            raise GoogleOAuthError("Google profile response was missing identity data.")

        return GoogleUserProfile(
            google_sub=str(subject),
            email=str(email),
            email_verified=bool(payload.get("email_verified")),
            name=payload.get("name"),
            picture=payload.get("picture"),
        )

    def _require_config(self) -> None:
        if not self._settings.google_client_id or not self._settings.google_client_secret:
            raise OAuthConfigurationError("Google OAuth credentials are not configured.")

    @staticmethod
    def _expires_at(payload: dict[str, Any]) -> datetime | None:
        expires_in = payload.get("expires_in")
        if expires_in is None:
            return None
        try:
            seconds = int(expires_in)
        except (TypeError, ValueError):
            return None
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)
