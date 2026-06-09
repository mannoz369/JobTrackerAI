from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings
from app.models.email import EmailProcessingState, EmailRecord
from app.models.extraction import JobEmailExtraction
from app.repositories.emails import EmailsRepository
from app.services.gemini import GeminiEmailExtractionService, GeminiTransientError


WorkerExtractionState = Literal[
    "extracted",
    "non_job",
    "needs_review",
    "deferred",
    "extraction_failed",
]


@dataclass(frozen=True)
class EmailExtractionWorkerResult:
    processed: int = 0
    extracted: int = 0
    non_job: int = 0
    needs_review: int = 0
    deferred: int = 0
    failed: int = 0

    def incremented(self, state: WorkerExtractionState) -> "EmailExtractionWorkerResult":
        return EmailExtractionWorkerResult(
            processed=self.processed + 1,
            extracted=self.extracted + (1 if state == "extracted" else 0),
            non_job=self.non_job + (1 if state == "non_job" else 0),
            needs_review=self.needs_review + (1 if state == "needs_review" else 0),
            deferred=self.deferred + (1 if state == "deferred" else 0),
            failed=self.failed + (1 if state == "extraction_failed" else 0),
        )


class EmailExtractionWorker:
    def __init__(
        self,
        settings: Settings,
        emails_repository: EmailsRepository,
        *,
        gemini_service: GeminiEmailExtractionService | None = None,
    ) -> None:
        self._settings = settings
        self._emails_repository = emails_repository
        self._gemini_service = gemini_service or GeminiEmailExtractionService(settings)

    async def process_pending(
        self,
        limit: int | None = None,
    ) -> EmailExtractionWorkerResult:
        batch_size = (
            limit
            if limit is not None
            else self._settings.email_extraction_batch_size
        )
        emails = await self._emails_repository.list_pending_extraction(batch_size)
        result = EmailExtractionWorkerResult()

        for email in emails:
            state = await self.process_email(email)
            result = result.incremented(state)

        return result

    async def process_email(self, email: EmailRecord) -> WorkerExtractionState:
        if email.id is None:
            return "extraction_failed"

        try:
            extraction = await self._gemini_service.extract_email(email)
        except GeminiTransientError as exc:
            await self._emails_repository.defer_extraction(
                email.id,
                self._safe_error_message(exc),
                model_name=self._gemini_service.model_name,
            )
            return "deferred"
        except Exception as exc:
            await self._emails_repository.mark_extraction_failed(
                email.id,
                self._safe_error_message(exc),
                model_name=self._gemini_service.model_name,
            )
            return "extraction_failed"

        processing_state = self._processing_state_for_extraction(extraction)
        await self._emails_repository.store_extraction_result(
            email.id,
            extraction,
            processing_state,
            model_name=self._gemini_service.model_name,
        )
        return processing_state

    def _processing_state_for_extraction(
        self,
        extraction: JobEmailExtraction,
    ) -> EmailProcessingState:
        if not extraction.is_job_related or (
            extraction.email_type == "Other" and extraction.status_signal == "Other"
        ):
            return "non_job"
        if extraction.requires_review(
            self._settings.email_extraction_review_confidence_threshold
        ):
            return "needs_review"
        return "extracted"

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__
