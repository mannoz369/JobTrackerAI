from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi import Response as FastAPIResponse

from app.core.config import Settings, get_settings
from app.db.mongo import get_mongo_database
from app.repositories.emails import EmailsRepository
from app.repositories.users import UsersRepository
from app.services.gmail_sync import GmailSyncService
from app.services.pubsub import PubSubService, PubSubValidationError


router = APIRouter(prefix="/pubsub", tags=["pubsub"])


def _settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", get_settings())


def _users_repository(request: Request) -> UsersRepository:
    override = getattr(request.app.state, "users_repository", None)
    if override is not None:
        return override
    return UsersRepository(get_mongo_database(request))


def _emails_repository(request: Request) -> EmailsRepository:
    override = getattr(request.app.state, "emails_repository", None)
    if override is not None:
        return override
    return EmailsRepository(get_mongo_database(request))


def _pubsub_service(request: Request) -> PubSubService:
    override = getattr(request.app.state, "pubsub_service", None)
    if override is not None:
        return override
    return PubSubService(_settings(request))


def _gmail_sync_service(request: Request) -> GmailSyncService:
    override = getattr(request.app.state, "gmail_sync_service", None)
    if override is not None:
        return override
    return GmailSyncService(
        _settings(request),
        _users_repository(request),
        _emails_repository(request),
    )


@router.post("/gmail", status_code=204)
async def gmail_pubsub_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str | None = None,
) -> FastAPIResponse:
    try:
        payload: dict[str, Any] = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Request body was not JSON.") from exc

    try:
        notification = _pubsub_service(request).parse_gmail_notification(
            payload,
            verification_token=token,
        )
    except PubSubValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = await _users_repository(request).get_by_monitored_email(
        notification.email_address
    )
    if user is not None:
        background_tasks.add_task(
            _gmail_sync_service(request).sync_user_history,
            user,
            notification.history_id,
        )

    return FastAPIResponse(status_code=204)
