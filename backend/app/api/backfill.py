from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.dependencies import (
    applications_repository,
    backfill_jobs_repository,
    companies_repository,
    emails_repository,
    require_current_user,
    settings,
    status_updates_repository,
    users_repository,
)
from app.models.backfill import BackfillJobRecord, BackfillJobStatus
from app.models.user import UserRecord
from app.services.gmail_backfill import (
    BackfillAlreadyRunningError,
    GmailBackfillError,
    GmailBackfillService,
)


router = APIRouter(prefix="/backfill", tags=["backfill"])


class BackfillJobResponse(BaseModel):
    id: str
    user_id: str
    start_date: date
    status: BackfillJobStatus
    gmail_query: str
    page_token: str | None = None
    fetched_count: int
    saved_count: int
    duplicate_count: int
    processed_count: int
    extracted_count: int
    non_job_count: int
    needs_review_count: int
    failed_count: int
    matched_count: int
    created_count: int
    errors: list[str] = Field(default_factory=list)
    last_error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, job: BackfillJobRecord) -> "BackfillJobResponse":
        if job.id is None:
            raise ValueError("Persisted backfill job is missing an id.")
        return cls(
            id=job.id,
            user_id=job.user_id,
            start_date=job.start_date,
            status=job.status,
            gmail_query=job.gmail_query,
            page_token=job.page_token,
            fetched_count=job.fetched_count,
            saved_count=job.saved_count,
            duplicate_count=job.duplicate_count,
            processed_count=job.processed_count,
            extracted_count=job.extracted_count,
            non_job_count=job.non_job_count,
            needs_review_count=job.needs_review_count,
            failed_count=job.failed_count,
            matched_count=job.matched_count,
            created_count=job.created_count,
            errors=job.errors,
            last_error=job.last_error,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class BackfillStatusResponse(BaseModel):
    default_start_date: date
    active_job: BackfillJobResponse | None = None
    latest_job: BackfillJobResponse | None = None


class StartBackfillRequest(BaseModel):
    start_date: date


@router.get("/status", response_model=BackfillStatusResponse)
async def backfill_status(request: Request) -> BackfillStatusResponse:
    user = await require_current_user(request)
    user_id = _user_id(user)
    repository = backfill_jobs_repository(request)
    active_job = await repository.get_active_for_user(user_id)
    latest_job = await repository.get_latest_for_user(user_id)
    return BackfillStatusResponse(
        default_start_date=GmailBackfillService.default_start_date_for_user(user),
        active_job=BackfillJobResponse.from_record(active_job)
        if active_job is not None
        else None,
        latest_job=BackfillJobResponse.from_record(latest_job)
        if latest_job is not None
        else None,
    )


@router.get("/jobs/{job_id}", response_model=BackfillJobResponse)
async def get_backfill_job(job_id: str, request: Request) -> BackfillJobResponse:
    user_id = _user_id(await require_current_user(request))
    job = await backfill_jobs_repository(request).get_for_user(user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Backfill job not found.")
    return BackfillJobResponse.from_record(job)


@router.post("/jobs", response_model=BackfillJobResponse, status_code=201)
async def start_backfill_job(
    body: StartBackfillRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> BackfillJobResponse:
    _validate_start_date(body.start_date)
    user = await require_current_user(request)
    service = _gmail_backfill_service(request)
    try:
        job = await service.create_job_for_user(user, body.start_date)
    except BackfillAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GmailBackfillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(service.run_job, job.id)
    return BackfillJobResponse.from_record(job)


@router.post("/jobs/{job_id}/retry", response_model=BackfillJobResponse)
async def retry_backfill_job(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> BackfillJobResponse:
    user = await require_current_user(request)
    service = _gmail_backfill_service(request)
    try:
        job = await service.retry_job_for_user(user, job_id)
    except BackfillAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GmailBackfillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(service.run_job, job.id)
    return BackfillJobResponse.from_record(job)


def _gmail_backfill_service(request: Request) -> GmailBackfillService:
    override = getattr(request.app.state, "gmail_backfill_service", None)
    if override is not None:
        return override
    return GmailBackfillService(
        settings(request),
        users_repository(request),
        backfill_jobs_repository(request),
        emails_repository(request),
        applications_repository(request),
        companies_repository(request),
        status_updates_repository(request),
    )


def _validate_start_date(start_date: date) -> None:
    if start_date > datetime.now(timezone.utc).date():
        raise HTTPException(status_code=422, detail="Start date cannot be in the future.")


def _user_id(user: UserRecord) -> str:
    if user.id is None:
        raise HTTPException(status_code=500, detail="Authenticated user has no id.")
    return user.id
