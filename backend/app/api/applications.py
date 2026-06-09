from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.dependencies import (
    applications_repository,
    companies_repository,
    emails_repository,
    require_current_user,
    settings,
    status_updates_repository,
)
from app.models.application import ApplicationRecord, ApplicationStatus
from app.models.extraction import ExtractionEvidence
from app.models.status_update import StatusUpdateRecord, StatusUpdateSource
from app.models.user import UserRecord
from app.services.application_status import ApplicationStatusService


PRIMARY_STATUSES: tuple[ApplicationStatus, ...] = (
    "Applied",
    "Reviewing",
    "Assessment",
    "Interview",
    "Rejected",
    "Offer",
)

router = APIRouter(prefix="/applications", tags=["applications"])


class ApplicationSummary(BaseModel):
    id: str
    company_id: str | None = None
    company_name: str
    role: str
    job_id: str | None = None
    location: str | None = None
    current_status: ApplicationStatus
    source_email_id: str | None = None
    confidence: float | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, application: ApplicationRecord) -> "ApplicationSummary":
        if application.id is None:
            raise ValueError("Persisted application is missing an id.")
        return cls(
            id=application.id,
            company_id=application.company_id,
            company_name=application.company_name,
            role=application.role,
            job_id=application.job_id,
            location=application.location,
            current_status=application.current_status,
            source_email_id=application.source_email_id,
            confidence=application.confidence,
            notes=application.notes,
            created_at=application.created_at,
            updated_at=application.updated_at,
        )


class StatusCount(BaseModel):
    status: ApplicationStatus
    count: int


class ApplicationsOverviewResponse(BaseModel):
    total: int
    review_queue_count: int
    status_counts: list[StatusCount]
    recent_applications: list[ApplicationSummary]


class CompanyApplicationGroup(BaseModel):
    company_id: str | None = None
    company_name: str
    application_count: int
    status_counts: list[StatusCount]
    applications: list[ApplicationSummary]


class StatusUpdateResponse(BaseModel):
    id: str
    email_id: str | None = None
    previous_status: ApplicationStatus | None = None
    new_status: ApplicationStatus
    source: StatusUpdateSource
    confidence: float | None = None
    explanation: str | None = None
    match_method: str | None = None
    evidence: list[ExtractionEvidence] = Field(default_factory=list)
    created_at: datetime

    @classmethod
    def from_record(cls, status_update: StatusUpdateRecord) -> "StatusUpdateResponse":
        if status_update.id is None:
            raise ValueError("Persisted status update is missing an id.")
        return cls(
            id=status_update.id,
            email_id=status_update.email_id,
            previous_status=status_update.previous_status,
            new_status=status_update.new_status,
            source=status_update.source,
            confidence=status_update.confidence,
            explanation=status_update.explanation,
            match_method=status_update.match_method,
            evidence=status_update.evidence,
            created_at=status_update.created_at,
        )


class ApplicationDetailResponse(BaseModel):
    application: ApplicationSummary
    timeline: list[StatusUpdateResponse]


class StatusEditRequest(BaseModel):
    status: ApplicationStatus
    explanation: str | None = Field(default=None, max_length=1000)


class StatusEditResponse(BaseModel):
    application: ApplicationSummary
    status_update_id: str


class DeleteApplicationResponse(BaseModel):
    id: str
    deleted: bool
    deleted_status_updates: int
    relinked_review_emails: int


@router.get("/overview", response_model=ApplicationsOverviewResponse)
async def application_overview(request: Request) -> ApplicationsOverviewResponse:
    user_id = _user_id(await require_current_user(request))
    applications = applications_repository(request)
    emails = emails_repository(request)

    status_counts = await applications.count_by_status(user_id)
    recent_applications = await applications.list_for_user(user_id, limit=6)
    review_queue_count = await emails.count_needs_review(user_id)

    return ApplicationsOverviewResponse(
        total=sum(status_counts.values()),
        review_queue_count=review_queue_count,
        status_counts=_status_count_response(status_counts),
        recent_applications=[
            ApplicationSummary.from_record(application)
            for application in recent_applications
        ],
    )


@router.get("", response_model=list[ApplicationSummary])
async def list_applications(
    request: Request,
    status: list[ApplicationStatus] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ApplicationSummary]:
    user_id = _user_id(await require_current_user(request))
    applications = await applications_repository(request).list_for_user(
        user_id,
        statuses=status,
        limit=limit,
    )
    return [ApplicationSummary.from_record(application) for application in applications]


@router.get("/company-groups", response_model=list[CompanyApplicationGroup])
async def company_groups(request: Request) -> list[CompanyApplicationGroup]:
    user_id = _user_id(await require_current_user(request))
    applications = await applications_repository(request).list_for_user(
        user_id,
        limit=500,
    )
    grouped: dict[str, list[ApplicationRecord]] = defaultdict(list)
    for application in applications:
        key = application.company_id or application.company_name
        grouped[key].append(application)

    groups = []
    for records in grouped.values():
        status_counts: dict[ApplicationStatus, int] = defaultdict(int)
        for record in records:
            status_counts[record.current_status] += 1
        first = records[0]
        groups.append(
            CompanyApplicationGroup(
                company_id=first.company_id,
                company_name=first.company_name,
                application_count=len(records),
                status_counts=_status_count_response(status_counts),
                applications=[
                    ApplicationSummary.from_record(record)
                    for record in sorted(
                        records,
                        key=lambda item: item.updated_at,
                        reverse=True,
                    )
                ],
            )
        )

    return sorted(groups, key=lambda group: group.company_name.lower())


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
async def application_detail(
    application_id: str,
    request: Request,
) -> ApplicationDetailResponse:
    user_id = _user_id(await require_current_user(request))
    applications = applications_repository(request)
    application = await applications.get_for_user(user_id, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    timeline = await status_updates_repository(request).list_for_application(
        user_id,
        application_id,
        limit=100,
    )
    return ApplicationDetailResponse(
        application=ApplicationSummary.from_record(application),
        timeline=[StatusUpdateResponse.from_record(update) for update in timeline],
    )


@router.patch("/{application_id}/status", response_model=StatusEditResponse)
async def edit_application_status(
    application_id: str,
    body: StatusEditRequest,
    request: Request,
) -> StatusEditResponse:
    user_id = _user_id(await require_current_user(request))
    service = ApplicationStatusService(
        settings(request),
        applications_repository(request),
        companies_repository(request),
        status_updates_repository(request),
        emails_repository(request),
    )
    result = await service.record_manual_status_update(
        user_id,
        application_id,
        body.status,
        explanation=body.explanation or "Manual dashboard status edit.",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return StatusEditResponse(
        application=ApplicationSummary.from_record(result.application),
        status_update_id=result.status_update_id,
    )


@router.delete("/{application_id}", response_model=DeleteApplicationResponse)
async def delete_application(
    application_id: str,
    request: Request,
) -> DeleteApplicationResponse:
    user_id = _user_id(await require_current_user(request))
    applications = applications_repository(request)
    application = await applications.get_for_user(user_id, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    relinked_emails = await emails_repository(request).clear_application_links_for_user(
        user_id,
        application_id,
    )
    deleted_status_updates = await status_updates_repository(
        request
    ).delete_for_application(user_id, application_id)
    deleted = await applications.delete_for_user(user_id, application_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Application not found.")

    return DeleteApplicationResponse(
        id=application_id,
        deleted=True,
        deleted_status_updates=deleted_status_updates,
        relinked_review_emails=relinked_emails,
    )


def _status_count_response(
    counts: dict[ApplicationStatus, int],
) -> list[StatusCount]:
    ordered_statuses = list(PRIMARY_STATUSES)
    for status in counts:
        if status not in ordered_statuses:
            ordered_statuses.append(status)
    return [
        StatusCount(status=status, count=counts.get(status, 0))
        for status in ordered_statuses
    ]


def _user_id(user: UserRecord) -> str:
    if user.id is None:
        raise HTTPException(status_code=500, detail="Authenticated user has no id.")
    return user.id
