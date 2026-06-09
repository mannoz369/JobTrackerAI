from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.models.application import (
    ApplicationCreate,
    ApplicationRecord,
    ApplicationStatus,
    normalize_keywords,
)
from app.models.email import EmailRecord
from app.models.status_update import StatusUpdateCreate
from app.repositories.applications import ApplicationsRepository
from app.repositories.companies import CompaniesRepository
from app.repositories.emails import EmailsRepository
from app.repositories.status_updates import StatusUpdatesRepository
from app.services.application_matching import (
    ApplicationMatchResult,
    ApplicationMatchingService,
)


ApplicationStatusAction = Literal[
    "status_updated",
    "application_created",
    "needs_review",
    "ignored",
    "already_processed",
]


class ApplicationStatusResult(BaseModel):
    action: ApplicationStatusAction
    application_id: str | None = None
    status_update_id: str | None = None
    match_result: ApplicationMatchResult | None = None
    review_reason: str | None = Field(default=None, max_length=1000)


class ManualStatusUpdateResult(BaseModel):
    application: ApplicationRecord
    status_update_id: str


class ApplicationStatusService:
    def __init__(
        self,
        settings: Settings,
        applications_repository: ApplicationsRepository,
        companies_repository: CompaniesRepository,
        status_updates_repository: StatusUpdatesRepository,
        emails_repository: EmailsRepository,
        *,
        matching_service: ApplicationMatchingService | None = None,
    ) -> None:
        self._settings = settings
        self._applications_repository = applications_repository
        self._companies_repository = companies_repository
        self._status_updates_repository = status_updates_repository
        self._emails_repository = emails_repository
        self._matching_service = matching_service or ApplicationMatchingService(
            settings,
            applications_repository,
        )

    async def process_email(self, email: EmailRecord) -> ApplicationStatusResult:
        if email.id is None:
            return ApplicationStatusResult(
                action="ignored",
                review_reason="Email is missing a persisted id.",
            )
        if email.extraction is None:
            return ApplicationStatusResult(
                action="ignored",
                review_reason="Email has no extraction metadata.",
            )
        if not email.extraction.is_job_related:
            return ApplicationStatusResult(
                action="ignored",
                review_reason="Email is not job-related.",
            )

        existing_update = await self._status_updates_repository.get_by_email_id(
            email.user_id,
            email.id,
        )
        if existing_update is not None:
            match_result = ApplicationMatchResult(
                decision="matched",
                confidence=1.0,
                explanation="Email already has a recorded status update.",
                method="none",
                application_id=existing_update.application_id,
                candidate_application_ids=[existing_update.application_id],
            )
            await self._store_email_match(
                email,
                match_result,
                application_id=existing_update.application_id,
                status_update_id=existing_update.id,
            )
            return ApplicationStatusResult(
                action="already_processed",
                application_id=existing_update.application_id,
                status_update_id=existing_update.id,
                match_result=match_result,
            )

        if email.extraction.requires_review(
            self._settings.email_extraction_review_confidence_threshold
        ):
            match_result = ApplicationMatchResult(
                decision="ambiguous",
                confidence=email.extraction.confidence,
                explanation=email.extraction.review_reason
                or "Extraction confidence or ambiguity indicators require review.",
            )
            return await self._mark_needs_review(email, match_result)

        match_result = await self._matching_service.match_email(email)
        if (
            match_result.decision == "matched"
            and match_result.application_id is not None
            and match_result.confidence
            >= self._settings.application_match_confidence_threshold
        ):
            application = await self._applications_repository.get_by_id(
                match_result.application_id
            )
            if application is None:
                return await self._mark_needs_review(
                    email,
                    ApplicationMatchResult(
                        decision="ambiguous",
                        confidence=match_result.confidence,
                        explanation="Matched application id no longer exists.",
                        method=match_result.method,
                        application_id=match_result.application_id,
                        candidate_application_ids=match_result.candidate_application_ids,
                    ),
                )
            return await self._apply_status_update(email, application, match_result)

        if self._can_auto_create(email):
            return await self._auto_create_application(email, match_result)

        return await self._mark_needs_review(email, match_result)

    async def record_manual_status_update(
        self,
        user_id: str,
        application_id: str,
        new_status: ApplicationStatus,
        *,
        email: EmailRecord | None = None,
        explanation: str | None = None,
        confidence: float | None = None,
        match_method: str = "manual",
    ) -> ManualStatusUpdateResult | None:
        application = await self._applications_repository.get_for_user(
            user_id,
            application_id,
        )
        if application is None or application.id is None:
            return None

        evidence = []
        email_id = None
        if email is not None:
            email_id = email.id
            if email.extraction is not None:
                evidence = email.extraction.evidence
                confidence = confidence if confidence is not None else email.extraction.confidence

        status_update = await self._status_updates_repository.create_status_update(
            StatusUpdateCreate(
                user_id=user_id,
                application_id=application.id,
                email_id=email_id,
                previous_status=application.current_status,
                new_status=new_status,
                source="manual",
                confidence=confidence,
                explanation=explanation,
                match_method=match_method,
                evidence=evidence,
            )
        )
        updated_application = await self._applications_repository.update_current_status_for_user(
            user_id,
            application.id,
            new_status,
        )
        if updated_application is None:
            return None
        assert status_update.id is not None
        return ManualStatusUpdateResult(
            application=updated_application,
            status_update_id=status_update.id,
        )

    async def _apply_status_update(
        self,
        email: EmailRecord,
        application: ApplicationRecord,
        match_result: ApplicationMatchResult,
    ) -> ApplicationStatusResult:
        assert email.id is not None
        assert application.id is not None
        assert email.extraction is not None

        status_update = await self._status_updates_repository.create_status_update(
            StatusUpdateCreate(
                user_id=email.user_id,
                application_id=application.id,
                email_id=email.id,
                previous_status=application.current_status,
                new_status=email.extraction.status_signal,
                source="email",
                confidence=match_result.confidence,
                explanation=match_result.explanation,
                match_method=match_result.method,
                evidence=email.extraction.evidence,
            )
        )
        await self._applications_repository.update_current_status(
            application.id,
            email.extraction.status_signal,
        )
        await self._store_email_match(
            email,
            match_result,
            application_id=application.id,
            status_update_id=status_update.id,
        )
        return ApplicationStatusResult(
            action="status_updated",
            application_id=application.id,
            status_update_id=status_update.id,
            match_result=match_result,
        )

    async def _auto_create_application(
        self,
        email: EmailRecord,
        match_result: ApplicationMatchResult,
    ) -> ApplicationStatusResult:
        assert email.id is not None
        assert email.extraction is not None
        assert email.extraction.company is not None
        assert email.extraction.role is not None

        company = await self._companies_repository.upsert_company(
            email.user_id,
            email.extraction.company,
            domains=[email.extraction.sender_domain]
            if email.extraction.sender_domain is not None
            else [],
        )
        application = await self._applications_repository.create_application(
            ApplicationCreate(
                user_id=email.user_id,
                company_id=company.id,
                company_name=company.name,
                role=email.extraction.role,
                job_id=email.extraction.job_id,
                location=email.extraction.location,
                current_status=email.extraction.status_signal,
                normalized_keywords=self._application_keywords(email),
                source_email_id=email.id,
                confidence=email.extraction.confidence,
            )
        )
        assert application.id is not None

        created_match = ApplicationMatchResult(
            decision="matched",
            confidence=email.extraction.confidence,
            explanation="Created a new application from a high-confidence application confirmation email.",
            method="none",
            application_id=application.id,
            candidate_application_ids=match_result.candidate_application_ids,
        )
        status_update = await self._status_updates_repository.create_status_update(
            StatusUpdateCreate(
                user_id=email.user_id,
                application_id=application.id,
                email_id=email.id,
                previous_status=None,
                new_status=email.extraction.status_signal,
                source="email",
                confidence=email.extraction.confidence,
                explanation=created_match.explanation,
                match_method="auto_create",
                evidence=email.extraction.evidence,
            )
        )
        await self._store_email_match(
            email,
            created_match,
            application_id=application.id,
            status_update_id=status_update.id,
        )
        return ApplicationStatusResult(
            action="application_created",
            application_id=application.id,
            status_update_id=status_update.id,
            match_result=created_match,
        )

    async def _mark_needs_review(
        self,
        email: EmailRecord,
        match_result: ApplicationMatchResult,
    ) -> ApplicationStatusResult:
        assert email.id is not None

        review_reason = self._review_reason(email, match_result)
        await self._emails_repository.store_application_match_result(
            email.id,
            "needs_review",
            matching_result=match_result.model_dump(mode="json"),
            application_id=match_result.application_id,
            review_reason=review_reason,
        )
        return ApplicationStatusResult(
            action="needs_review",
            application_id=match_result.application_id,
            match_result=match_result,
            review_reason=review_reason,
        )

    async def _store_email_match(
        self,
        email: EmailRecord,
        match_result: ApplicationMatchResult,
        *,
        application_id: str,
        status_update_id: str | None,
    ) -> None:
        assert email.id is not None
        await self._emails_repository.store_application_match_result(
            email.id,
            "matched",
            matching_result=match_result.model_dump(mode="json"),
            application_id=application_id,
            status_update_id=status_update_id,
            review_reason=None,
        )

    def _can_auto_create(self, email: EmailRecord) -> bool:
        extraction = email.extraction
        if extraction is None:
            return False
        return (
            extraction.email_type == "ApplicationConfirmation"
            and extraction.status_signal == "Applied"
            and extraction.confidence
            >= self._settings.application_autocreate_confidence_threshold
            and extraction.company is not None
            and extraction.role is not None
            and not extraction.ambiguous_indicators
            and extraction.review_reason is None
        )

    def _application_keywords(self, email: EmailRecord) -> list[str]:
        assert email.extraction is not None
        keywords = list(email.extraction.unique_keywords)
        if email.extraction.location is not None:
            keywords.append(email.extraction.location)
        if email.extraction.sender_domain is not None:
            keywords.append(email.extraction.sender_domain)
        if email.extraction.job_id is not None:
            keywords.append(email.extraction.job_id)
        return normalize_keywords(keywords)

    @staticmethod
    def _review_reason(
        email: EmailRecord,
        match_result: ApplicationMatchResult,
    ) -> str:
        extraction_reason = None
        if email.extraction is not None:
            extraction_reason = email.extraction.review_reason
            if extraction_reason is None and email.extraction.ambiguous_indicators:
                extraction_reason = "; ".join(email.extraction.ambiguous_indicators)
        if extraction_reason:
            return extraction_reason
        return match_result.explanation
