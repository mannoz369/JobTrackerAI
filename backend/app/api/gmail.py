from fastapi import APIRouter, HTTPException, Request

from app.api.auth import SESSION_COOKIE
from app.core.config import Settings, get_settings
from app.core.security import SessionSigner
from app.db.mongo import get_mongo_database
from app.models.user import GmailWatchState
from app.repositories.users import UsersRepository
from app.services.gmail_api import GmailApiConfigurationError, GmailApiError
from app.services.gmail_watch import GmailWatchError, GmailWatchService
from app.services.google_oauth import GoogleOAuthError, OAuthConfigurationError


router = APIRouter(prefix="/gmail", tags=["gmail"])


def _settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", get_settings())


def _users_repository(request: Request) -> UsersRepository:
    override = getattr(request.app.state, "users_repository", None)
    if override is not None:
        return override
    return UsersRepository(get_mongo_database(request))


def _gmail_watch_service(request: Request) -> GmailWatchService:
    override = getattr(request.app.state, "gmail_watch_service", None)
    if override is not None:
        return override
    return GmailWatchService(_settings(request), _users_repository(request))


def _session_signer(request: Request) -> SessionSigner:
    return SessionSigner(_settings(request).session_secret_key)


@router.post("/watch/register", response_model=GmailWatchState)
async def register_gmail_watch(request: Request) -> GmailWatchState:
    session = _session_signer(request).verify_session(
        request.cookies.get(SESSION_COOKIE)
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user = await _users_repository(request).get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    try:
        return await _gmail_watch_service(request).register_watch(user)
    except (
        GmailApiConfigurationError,
        GmailApiError,
        GmailWatchError,
        GoogleOAuthError,
        OAuthConfigurationError,
    ) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
