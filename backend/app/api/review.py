from email.utils import parseaddr
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.api.applications import ApplicationSummary
from app.api.dependencies import (
    applications_repository,
    companies_repository,
    emails_repository,
    require_current_user,
    settings,
    status_updates_repository,
)
from app.models.application import (
    ApplicationCreate,
    ApplicationStatus,
    normalize_keywords,
)
from app.models.email import EmailRecord
from app.models.extraction import JobEmailExtraction
from app.models.status_update import StatusUpdateCreate
from app.models.user import UserRecord
from app.services.application_status import ApplicationStatusService


ReviewAction = Literal["mapped", "created", "dismissed"]
UNKNOWN_COMPANY_NAME = "Unknown company"
UNKNOWN_ROLE_NAME = "Role not specified"

router = APIRouter(prefix="/review", tags=["review"])


class ReviewQueueItem(BaseModel):
    email_id: str
    sender: str | None = None
    subject: str | None = None
    received_at: str | None = None
    snippet: str | None = None
    review_reason: str | None = None
    extraction: JobEmailExtraction | None = None
    matching_result: dict[str, Any] | None = None
    candidates: list[ApplicationSummary]


class MapReviewEmailRequest(BaseModel):
    application_id: str = Field(min_length=1)
    status: ApplicationStatus | None = None
    explanation: str | None = Field(default=None, max_length=1000)


class CreateApplicationFromReviewRequest(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=160)
    role: str | None = Field(default=None, min_length=1, max_length=180)
    job_id: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=160)
    status: ApplicationStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)
    explanation: str | None = Field(default=None, max_length=1000)


class DismissReviewEmailRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ReviewActionResponse(BaseModel):
    action: ReviewAction
    email_id: str
    application: ApplicationSummary | None = None
    status_update_id: str | None = None


@router.get("/queue", response_model=list[ReviewQueueItem])
async def review_queue(request: Request) -> list[ReviewQueueItem]:
    user_id = _user_id(await require_current_user(request))
    emails = await emails_repository(request).list_needs_review(user_id, limit=50)
    applications = applications_repository(request)

    items = []
    for email in emails:
        if email.id is None:
            continue
        candidates = await _candidate_summaries(user_id, email, applications)
        items.append(
            ReviewQueueItem(
                email_id=email.id,
                sender=email.sender,
                subject=email.subject,
                received_at=email.received_at.isoformat()
                if email.received_at is not None
                else None,
                snippet=email.snippet,
                review_reason=email.application_review_reason,
                extraction=email.extraction,
                matching_result=email.matching_result,
                candidates=candidates,
            )
        )
    return items


@router.post("/{email_id}/map", response_model=ReviewActionResponse)
async def map_review_email(
    email_id: str,
    body: MapReviewEmailRequest,
    request: Request,
) -> ReviewActionResponse:
    user_id = _user_id(await require_current_user(request))
    emails = emails_repository(request)
    email = await _review_email(user_id, email_id, emails)
    application = await applications_repository(request).get_for_user(
        user_id,
        body.application_id,
    )
    if application is None or application.id is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    status = body.status or _extracted_status(email) or application.current_status
    explanation = (
        body.explanation
        or email.application_review_reason
        or _match_explanation(email)
        or "Mapped manually from review queue."
    )
    service = ApplicationStatusService(
        settings(request),
        applications_repository(request),
        companies_repository(request),
        status_updates_repository(request),
        emails,
    )
    result = await service.record_manual_status_update(
        user_id,
        application.id,
        status,
        email=email,
        explanation=explanation,
        match_method="manual_review",
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    updated_email = await emails.store_application_match_result_for_user(
        user_id,
        email_id,
        "matched",
        matching_result=_manual_match_result(
            application.id,
            status,
            explanation,
            email,
            candidate_application_ids=_candidate_ids(email),
        ),
        application_id=application.id,
        status_update_id=result.status_update_id,
        review_reason=None,
    )
    if updated_email is None:
        raise HTTPException(status_code=404, detail="Review email not found.")

    return ReviewActionResponse(
        action="mapped",
        email_id=email_id,
        application=ApplicationSummary.from_record(result.application),
        status_update_id=result.status_update_id,
    )


@router.post("/{email_id}/create-application", response_model=ReviewActionResponse)
async def create_application_from_review(
    email_id: str,
    body: CreateApplicationFromReviewRequest,
    request: Request,
) -> ReviewActionResponse:
    user_id = _user_id(await require_current_user(request))
    emails = emails_repository(request)
    email = await _review_email(user_id, email_id, emails)
    extraction = email.extraction
    company_name = body.company_name or _fallback_company_name(email)
    role = body.role or (extraction.role if extraction else None) or UNKNOWN_ROLE_NAME

    status = body.status or _extracted_status(email) or "Applied"
    company = await companies_repository(request).upsert_company(
        user_id,
        company_name,
        domains=[extraction.sender_domain]
        if extraction is not None and extraction.sender_domain is not None
        else [],
    )
    try:
        application = await applications_repository(request).create_application(
            ApplicationCreate(
                user_id=user_id,
                company_id=company.id,
                company_name=company.name,
                role=role,
                job_id=body.job_id or (extraction.job_id if extraction else None),
                location=body.location or (extraction.location if extraction else None),
                current_status=status,
                normalized_keywords=_application_keywords(extraction),
                source_email_id=email.id,
                confidence=extraction.confidence if extraction is not None else None,
                notes=body.notes,
            )
        )
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=409,
            detail="An application with this job ID already exists. Map the email to the existing application instead.",
        ) from exc
    if application.id is None:
        raise HTTPException(status_code=500, detail="Created application has no id.")

    explanation = (
        body.explanation
        or email.application_review_reason
        or "Created manually from review queue."
    )
    status_update = await status_updates_repository(request).create_status_update(
        StatusUpdateCreate(
            user_id=user_id,
            application_id=application.id,
            email_id=email.id,
            previous_status=None,
            new_status=status,
            source="manual",
            confidence=extraction.confidence if extraction is not None else None,
            explanation=explanation,
            match_method="manual_create",
            evidence=extraction.evidence if extraction is not None else [],
        )
    )

    await emails.store_application_match_result_for_user(
        user_id,
        email_id,
        "matched",
        matching_result=_manual_match_result(
            application.id,
            status,
            explanation,
            email,
            candidate_application_ids=_candidate_ids(email),
        ),
        application_id=application.id,
        status_update_id=status_update.id,
        review_reason=None,
    )

    return ReviewActionResponse(
        action="created",
        email_id=email_id,
        application=ApplicationSummary.from_record(application),
        status_update_id=status_update.id,
    )


@router.post("/{email_id}/dismiss", response_model=ReviewActionResponse)
async def dismiss_review_email(
    email_id: str,
    body: DismissReviewEmailRequest,
    request: Request,
) -> ReviewActionResponse:
    user_id = _user_id(await require_current_user(request))
    emails = emails_repository(request)
    await _review_email(user_id, email_id, emails)
    reason = body.reason or "Dismissed as not a tracked job application email."
    updated_email = await emails.store_application_match_result_for_user(
        user_id,
        email_id,
        "ignored",
        matching_result={
            "decision": "no_match",
            "confidence": 1.0,
            "explanation": reason,
            "method": "manual",
            "application_id": None,
            "candidate_application_ids": [],
        },
        review_reason=reason,
    )
    if updated_email is None:
        raise HTTPException(status_code=404, detail="Review email not found.")
    return ReviewActionResponse(action="dismissed", email_id=email_id)


async def _candidate_summaries(
    user_id: str,
    email: EmailRecord,
    applications: Any,
) -> list[ApplicationSummary]:
    candidate_ids = _candidate_ids(email)
    if candidate_ids:
        candidates = await applications.list_by_ids(user_id, candidate_ids)
    else:
        extraction = email.extraction
        candidates = await applications.list_candidates(
            user_id,
            company=extraction.company if extraction is not None else None,
            keywords=_application_keywords(extraction),
            limit=5,
        )
    return [ApplicationSummary.from_record(candidate) for candidate in candidates]


async def _review_email(user_id: str, email_id: str, emails: Any) -> EmailRecord:
    email = await emails.get_for_user(user_id, email_id)
    if email is None:
        raise HTTPException(status_code=404, detail="Review email not found.")
    if email.processing_state != "needs_review":
        raise HTTPException(status_code=409, detail="Email is not awaiting review.")
    return email


def _manual_match_result(
    application_id: str,
    status: ApplicationStatus,
    explanation: str,
    email: EmailRecord,
    *,
    candidate_application_ids: list[str],
) -> dict[str, Any]:
    confidence = email.extraction.confidence if email.extraction is not None else 1.0
    return {
        "decision": "matched",
        "confidence": confidence,
        "explanation": explanation,
        "method": "manual",
        "application_id": application_id,
        "candidate_application_ids": candidate_application_ids or [application_id],
        "status": status,
    }


def _application_keywords(extraction: JobEmailExtraction | None) -> list[str]:
    if extraction is None:
        return []
    keywords = list(extraction.unique_keywords)
    if extraction.location is not None:
        keywords.append(extraction.location)
    if extraction.sender_domain is not None:
        keywords.append(extraction.sender_domain)
    if extraction.job_id is not None:
        keywords.append(extraction.job_id)
    return normalize_keywords(keywords)


def _fallback_company_name(email: EmailRecord) -> str:
    extraction = email.extraction
    if extraction is not None and extraction.company is not None:
        return extraction.company
    if extraction is not None and extraction.sender_domain is not None:
        return extraction.sender_domain

    _, address = parseaddr(email.sender or "")
    if "@" in address:
        domain = address.rsplit("@", 1)[1].strip().lower()
        if domain:
            return domain
    return UNKNOWN_COMPANY_NAME


def _candidate_ids(email: EmailRecord) -> list[str]:
    if not isinstance(email.matching_result, dict):
        return []
    values = email.matching_result.get("candidate_application_ids", [])
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _extracted_status(email: EmailRecord) -> ApplicationStatus | None:
    if email.extraction is None:
        return None
    return email.extraction.status_signal


def _match_explanation(email: EmailRecord) -> str | None:
    if not isinstance(email.matching_result, dict):
        return None
    explanation = email.matching_result.get("explanation")
    return explanation if isinstance(explanation, str) else None


def _user_id(user: UserRecord) -> str:
    if user.id is None:
        raise HTTPException(status_code=500, detail="Authenticated user has no id.")
    return user.id
