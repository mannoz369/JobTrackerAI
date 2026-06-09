from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.models.application import (
    ApplicationRecord,
    normalize_keywords,
    normalize_match_text,
)
from app.models.email import EmailRecord
from app.models.extraction import JobEmailExtraction
from app.repositories.applications import ApplicationsRepository


MatchDecision = Literal["matched", "ambiguous", "no_match"]
MatchMethod = Literal["job_id", "company_role", "llm", "keyword", "none"]


class ApplicationMatchResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision: MatchDecision
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1, max_length=1000)
    method: MatchMethod = "none"
    application_id: str | None = None
    candidate_application_ids: list[str] = Field(default_factory=list, max_length=20)


class LlmApplicationMatchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    application_id: str | None = Field(default=None, alias="applicationId")
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1, max_length=1000)


class ApplicationMatchLlm(Protocol):
    async def match_application(
        self,
        email: EmailRecord,
        extraction: JobEmailExtraction,
        candidates: list[ApplicationRecord],
    ) -> LlmApplicationMatchResponse:
        ...


class ApplicationMatchingService:
    def __init__(
        self,
        settings: Settings,
        applications_repository: ApplicationsRepository,
        *,
        llm_matcher: ApplicationMatchLlm | None = None,
    ) -> None:
        self._settings = settings
        self._applications_repository = applications_repository
        self._llm_matcher = llm_matcher

    async def match_email(self, email: EmailRecord) -> ApplicationMatchResult:
        extraction = email.extraction
        if extraction is None:
            return ApplicationMatchResult(
                decision="no_match",
                confidence=0.0,
                explanation="Email has no extraction metadata to match.",
            )
        if not extraction.is_job_related:
            return ApplicationMatchResult(
                decision="no_match",
                confidence=0.0,
                explanation="Email extraction is not job-related.",
            )

        job_id_result = await self._match_by_job_id(email.user_id, extraction)
        if job_id_result is not None:
            return job_id_result

        company_role_result = await self._match_by_company_and_role(
            email.user_id,
            extraction,
        )
        if company_role_result is not None:
            return company_role_result

        candidates = await self._applications_repository.list_candidates(
            email.user_id,
            company=extraction.company,
            keywords=self._candidate_keywords(extraction),
            limit=10,
        )
        if not candidates:
            return ApplicationMatchResult(
                decision="no_match",
                confidence=0.0,
                explanation="No existing application candidates matched company or keywords.",
            )

        if self._llm_matcher is not None:
            return await self._match_with_llm(email, extraction, candidates)
        return self._match_by_keywords(extraction, candidates)

    async def _match_by_job_id(
        self,
        user_id: str,
        extraction: JobEmailExtraction,
    ) -> ApplicationMatchResult | None:
        if extraction.job_id is None:
            return None

        matches = await self._applications_repository.list_by_job_id(
            user_id,
            extraction.job_id,
        )
        if not matches:
            return None

        candidate_ids = self._candidate_ids(matches)
        if len(matches) == 1:
            return ApplicationMatchResult(
                decision="matched",
                confidence=1.0,
                explanation="Matched application by exact normalized job ID.",
                method="job_id",
                application_id=matches[0].id,
                candidate_application_ids=candidate_ids,
            )
        return ApplicationMatchResult(
            decision="ambiguous",
            confidence=0.99,
            explanation="Multiple applications share the extracted job ID.",
            method="job_id",
            candidate_application_ids=candidate_ids,
        )

    async def _match_by_company_and_role(
        self,
        user_id: str,
        extraction: JobEmailExtraction,
    ) -> ApplicationMatchResult | None:
        if extraction.company is None or extraction.role is None:
            return None

        matches = await self._applications_repository.list_by_company_and_role(
            user_id,
            extraction.company,
            extraction.role,
        )
        if not matches:
            return None

        candidate_ids = self._candidate_ids(matches)
        if len(matches) == 1:
            return ApplicationMatchResult(
                decision="matched",
                confidence=0.92,
                explanation="Matched application by exact normalized company and role.",
                method="company_role",
                application_id=matches[0].id,
                candidate_application_ids=candidate_ids,
            )
        return ApplicationMatchResult(
            decision="ambiguous",
            confidence=0.76,
            explanation="Multiple applications share the extracted company and role.",
            method="company_role",
            candidate_application_ids=candidate_ids,
        )

    async def _match_with_llm(
        self,
        email: EmailRecord,
        extraction: JobEmailExtraction,
        candidates: list[ApplicationRecord],
    ) -> ApplicationMatchResult:
        response = await self._llm_matcher.match_application(
            email,
            extraction,
            candidates,
        )
        candidate_ids = self._candidate_ids(candidates)
        if response.application_id not in candidate_ids:
            return ApplicationMatchResult(
                decision="no_match",
                confidence=min(response.confidence, 0.5),
                explanation=response.explanation,
                method="llm",
                candidate_application_ids=candidate_ids,
            )

        if response.confidence >= self._settings.application_match_confidence_threshold:
            return ApplicationMatchResult(
                decision="matched",
                confidence=response.confidence,
                explanation=response.explanation,
                method="llm",
                application_id=response.application_id,
                candidate_application_ids=candidate_ids,
            )
        return ApplicationMatchResult(
            decision="ambiguous",
            confidence=response.confidence,
            explanation=response.explanation,
            method="llm",
            application_id=response.application_id,
            candidate_application_ids=candidate_ids,
        )

    def _match_by_keywords(
        self,
        extraction: JobEmailExtraction,
        candidates: list[ApplicationRecord],
    ) -> ApplicationMatchResult:
        scored_candidates = sorted(
            (
                (self._candidate_score(extraction, candidate), candidate)
                for candidate in candidates
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        top_score, top_candidate = scored_candidates[0]
        next_score = scored_candidates[1][0] if len(scored_candidates) > 1 else 0.0
        candidate_ids = self._candidate_ids(candidates)

        if top_score < 0.5:
            return ApplicationMatchResult(
                decision="no_match",
                confidence=top_score,
                explanation="Candidate applications did not share enough company, role, or keyword evidence.",
                method="keyword",
                candidate_application_ids=candidate_ids,
            )
        if (
            top_score >= self._settings.application_match_confidence_threshold
            and top_score - next_score >= self._settings.application_match_ambiguity_margin
        ):
            return ApplicationMatchResult(
                decision="matched",
                confidence=top_score,
                explanation="Matched application by combined company, role, and unique keyword evidence.",
                method="keyword",
                application_id=top_candidate.id,
                candidate_application_ids=candidate_ids,
            )
        return ApplicationMatchResult(
            decision="ambiguous",
            confidence=top_score,
            explanation="Candidate applications were too close to choose automatically.",
            method="keyword",
            application_id=top_candidate.id,
            candidate_application_ids=candidate_ids,
        )

    def _candidate_score(
        self,
        extraction: JobEmailExtraction,
        candidate: ApplicationRecord,
    ) -> float:
        score = 0.0
        if (
            normalize_match_text(extraction.company) is not None
            and normalize_match_text(extraction.company) == candidate.normalized_company
        ):
            score += 0.35

        extracted_role = normalize_match_text(extraction.role)
        if extracted_role is not None and extracted_role == candidate.normalized_role:
            score += 0.35
        elif extracted_role is not None:
            role_overlap = self._token_overlap(
                extracted_role,
                candidate.normalized_role,
            )
            score += min(0.25, role_overlap * 0.25)

        extracted_keywords = set(self._candidate_keywords(extraction))
        candidate_keywords = set(candidate.normalized_keywords)
        if extracted_keywords and candidate_keywords:
            overlap = extracted_keywords & candidate_keywords
            score += min(0.3, 0.1 * len(overlap))

        if (
            extraction.location is not None
            and normalize_match_text(extraction.location) in candidate_keywords
        ):
            score += 0.1

        return min(score, 1.0)

    @staticmethod
    def _token_overlap(left: str, right: str | None) -> float:
        if right is None:
            return 0.0
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    @staticmethod
    def _candidate_keywords(extraction: JobEmailExtraction) -> list[str]:
        keywords = list(extraction.unique_keywords)
        if extraction.location is not None:
            keywords.append(extraction.location)
        if extraction.sender_domain is not None:
            keywords.append(extraction.sender_domain)
        if extraction.job_id is not None:
            keywords.append(extraction.job_id)
        return normalize_keywords(keywords)

    @staticmethod
    def _candidate_ids(candidates: list[ApplicationRecord]) -> list[str]:
        return [candidate.id for candidate in candidates if candidate.id is not None]
