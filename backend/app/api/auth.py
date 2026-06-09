import secrets
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.security import SessionSigner, TokenCipher, generate_oauth_state
from app.db.mongo import get_mongo_database
from app.models.user import GmailWatchState, OAuthTokenMetadata
from app.repositories.users import UsersRepository
from app.services.google_oauth import (
    GoogleOAuthError,
    GoogleOAuthService,
    OAuthConfigurationError,
)


OAUTH_STATE_COOKIE = "jobtracker_oauth_state"
SESSION_COOKIE = "jobtracker_session"
OAUTH_STATE_MAX_AGE_SECONDS = 10 * 60

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthStatusResponse(BaseModel):
    authenticated: bool
    connected: bool
    email: str | None = None
    monitored_email: str | None = None
    gmail_watch: GmailWatchState | None = None


def _settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", get_settings())


def _users_repository(request: Request) -> UsersRepository:
    override = getattr(request.app.state, "users_repository", None)
    if override is not None:
        return override
    return UsersRepository(get_mongo_database(request))


def _google_oauth_service(request: Request) -> GoogleOAuthService:
    override = getattr(request.app.state, "google_oauth_service", None)
    if override is not None:
        return override
    return GoogleOAuthService(_settings(request))


def _token_cipher(request: Request) -> TokenCipher:
    settings = _settings(request)
    secret = settings.token_encryption_key or settings.session_secret_key
    return TokenCipher(secret)


def _session_signer(request: Request) -> SessionSigner:
    return SessionSigner(_settings(request).session_secret_key)


@router.get("/google/start")
async def start_google_oauth(request: Request) -> RedirectResponse:
    settings = _settings(request)
    service = _google_oauth_service(request)
    state = generate_oauth_state()

    try:
        authorization_url = service.authorization_url(state)
    except OAuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    response = RedirectResponse(authorization_url)
    _set_cookie(
        response,
        settings=settings,
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
    )
    return response


@router.get("/google/callback")
async def google_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = _settings(request)
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if error or not code or not state or not expected_state:
        return _frontend_redirect(settings, "error", clear_state=True)

    if not secrets.compare_digest(state, expected_state):
        return _frontend_redirect(settings, "error", clear_state=True)

    service = _google_oauth_service(request)
    try:
        tokens = await service.exchange_code(code)
        profile = await service.fetch_profile(tokens.access_token)
    except (GoogleOAuthError, OAuthConfigurationError):
        return _frontend_redirect(settings, "error", clear_state=True)

    encrypted_refresh_token = (
        _token_cipher(request).encrypt(tokens.refresh_token)
        if tokens.refresh_token is not None
        else None
    )
    token_metadata = OAuthTokenMetadata(
        refresh_token_encrypted=encrypted_refresh_token,
        access_token_expires_at=tokens.access_token_expires_at,
        scopes=tokens.scopes,
        token_type=tokens.token_type,
    )
    user = await _users_repository(request).upsert_google_user(profile, token_metadata)
    if user.id is None:
        raise HTTPException(status_code=500, detail="User record did not include an id.")

    response = _frontend_redirect(settings, "connected", clear_state=True)
    session_token = _session_signer(request).create_session(
        user_id=user.id,
        email=user.email,
        max_age_seconds=settings.session_cookie_max_age_seconds,
    )
    _set_cookie(
        response,
        settings=settings,
        key=SESSION_COOKIE,
        value=session_token,
        max_age=settings.session_cookie_max_age_seconds,
    )
    return response


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(request: Request) -> AuthStatusResponse:
    session = _session_signer(request).verify_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        return AuthStatusResponse(authenticated=False, connected=False)

    user = await _users_repository(request).get_by_id(session.user_id)
    if user is None:
        return AuthStatusResponse(authenticated=False, connected=False)

    return AuthStatusResponse(
        authenticated=True,
        connected=user.oauth.refresh_token_encrypted is not None,
        email=user.email,
        monitored_email=user.monitored_email,
        gmail_watch=user.gmail_watch,
    )


@router.post("/logout", response_model=AuthStatusResponse)
async def logout(request: Request, response: Response) -> AuthStatusResponse:
    settings = _settings(request)
    _delete_cookie(response, settings=settings, key=SESSION_COOKIE)
    return AuthStatusResponse(authenticated=False, connected=False)


def _frontend_redirect(
    settings: Settings,
    auth_status: str,
    *,
    clear_state: bool = False,
) -> RedirectResponse:
    response = RedirectResponse(_status_redirect_url(settings.frontend_app_url, auth_status))
    if clear_state:
        _delete_cookie(response, settings=settings, key=OAUTH_STATE_COOKIE)
    return response


def _status_redirect_url(frontend_app_url: str, auth_status: str) -> str:
    parts = urlsplit(frontend_app_url)
    query = urlencode({"auth": auth_status})
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, ""))


def _set_cookie(
    response: RedirectResponse,
    *,
    settings: Settings,
    key: str,
    value: str,
    max_age: int,
) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )


def _delete_cookie(response: Response, *, settings: Settings, key: str) -> None:
    response.delete_cookie(
        key=key,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )
