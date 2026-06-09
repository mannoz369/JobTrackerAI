from fastapi import HTTPException, Request

from app.api.auth import SESSION_COOKIE
from app.core.config import Settings, get_settings
from app.core.security import SessionSigner
from app.db.mongo import get_mongo_database
from app.models.user import UserRecord
from app.repositories.backfill_jobs import BackfillJobsRepository
from app.repositories.applications import ApplicationsRepository
from app.repositories.companies import CompaniesRepository
from app.repositories.emails import EmailsRepository
from app.repositories.status_updates import StatusUpdatesRepository
from app.repositories.users import UsersRepository


def settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", get_settings())


def users_repository(request: Request) -> UsersRepository:
    override = getattr(request.app.state, "users_repository", None)
    if override is not None:
        return override
    return UsersRepository(get_mongo_database(request))


def backfill_jobs_repository(request: Request) -> BackfillJobsRepository:
    override = getattr(request.app.state, "backfill_jobs_repository", None)
    if override is not None:
        return override
    return BackfillJobsRepository(get_mongo_database(request))


def applications_repository(request: Request) -> ApplicationsRepository:
    override = getattr(request.app.state, "applications_repository", None)
    if override is not None:
        return override
    return ApplicationsRepository(get_mongo_database(request))


def companies_repository(request: Request) -> CompaniesRepository:
    override = getattr(request.app.state, "companies_repository", None)
    if override is not None:
        return override
    return CompaniesRepository(get_mongo_database(request))


def emails_repository(request: Request) -> EmailsRepository:
    override = getattr(request.app.state, "emails_repository", None)
    if override is not None:
        return override
    return EmailsRepository(get_mongo_database(request))


def status_updates_repository(request: Request) -> StatusUpdatesRepository:
    override = getattr(request.app.state, "status_updates_repository", None)
    if override is not None:
        return override
    return StatusUpdatesRepository(get_mongo_database(request))


async def require_current_user(request: Request) -> UserRecord:
    signer = SessionSigner(settings(request).session_secret_key)
    session = signer.verify_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user = await users_repository(request).get_by_id(session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user
