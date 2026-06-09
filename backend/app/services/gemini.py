from collections.abc import Awaitable, Callable
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.models.application import ApplicationRecord
from app.models.email import EmailCreate, EmailRecord
from app.models.extraction import (
    JobEmailExtraction,
    job_email_extraction_json_schema,
)
from app.services.application_matching import LlmApplicationMatchResponse


GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(RuntimeError):
    pass


class GeminiConfigurationError(GeminiError):
    pass


class GeminiApiError(GeminiError):
    pass


class GeminiResponseValidationError(GeminiError):
    pass


class GeminiTransientError(GeminiApiError):
    pass


SleepCallable = Callable[[float], Awaitable[None]]


class GeminiEmailExtractionService:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        prompt_path: Path | None = None,
        sleep: SleepCallable = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._sleep = sleep
        self._prompt_template = self._read_prompt(prompt_path)

    @property
    def model_name(self) -> str:
        return self._settings.gemini_model

    async def extract_email(self, email: EmailCreate | EmailRecord) -> JobEmailExtraction:
        self._require_config()
        request_body = self._request_body(email)
        max_attempts = self._settings.gemini_max_retries + 1
        last_error: GeminiError | None = None

        for attempt in range(max_attempts):
            try:
                payload = await self._send_generate_content_request(request_body)
                text = self._extract_response_text(payload)
                return JobEmailExtraction.model_validate_json(text)
            except GeminiTransientError as exc:
                last_error = exc
                if attempt >= max_attempts - 1:
                    raise exc
                await self._sleep(
                    self._settings.gemini_retry_backoff_seconds * (2**attempt)
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                raise GeminiResponseValidationError(
                    "Gemini response did not match the extraction schema."
                ) from exc

        if last_error is not None:
            raise last_error
        raise GeminiApiError("Gemini extraction failed.")

    async def _send_generate_content_request(
        self,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self._settings.gemini_timeout_seconds,
            transport=self._transport,
        ) as client:
            try:
                response = await client.post(
                    self._generate_content_url(),
                    json=request_body,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "x-goog-api-key": self._settings.gemini_api_key or "",
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise GeminiTransientError("Gemini request did not complete.") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise GeminiTransientError(
                f"Gemini request failed with status {response.status_code}."
            )
        if response.status_code >= 400:
            raise GeminiApiError(
                f"Gemini request failed with status {response.status_code}."
            )
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise GeminiResponseValidationError(
                "Gemini response was not valid JSON."
            ) from exc
        return payload

    def _request_body(self, email: EmailCreate | EmailRecord) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                f"{self._prompt_template.strip()}\n\n"
                                "Normalized email JSON:\n"
                                f"{json.dumps(self._email_payload(email), default=str)}"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": job_email_extraction_json_schema(),
            },
        }

    def _email_payload(self, email: EmailCreate | EmailRecord) -> dict[str, Any]:
        body_text = email.body_text or ""
        max_body_chars = self._settings.email_extraction_max_body_chars
        return {
            "gmailMessageId": email.gmail_message_id,
            "threadId": email.thread_id,
            "sender": email.sender,
            "senderDomain": self._sender_domain(email.sender),
            "recipients": email.recipients,
            "subject": email.subject,
            "receivedAt": email.received_at.isoformat() if email.received_at else None,
            "labels": email.labels,
            "snippet": email.snippet,
            "bodyText": body_text[:max_body_chars],
        }

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise GeminiResponseValidationError(
                "Gemini response did not include candidates."
            )

        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        text_parts = [
            part.get("text")
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        text = "".join(text_parts).strip()
        if not text:
            raise GeminiResponseValidationError(
                "Gemini response did not include JSON text."
            )
        return text

    def _generate_content_url(self) -> str:
        model_name = self._settings.gemini_model
        if model_name.startswith("models/"):
            model_name = model_name.removeprefix("models/")
        return f"{GEMINI_API_BASE_URL}/models/{model_name}:generateContent"

    def _require_config(self) -> None:
        if not self._settings.gemini_api_key:
            raise GeminiConfigurationError("Gemini API key is not configured.")

    @staticmethod
    def _read_prompt(prompt_path: Path | None) -> str:
        resolved_prompt_path = (
            prompt_path
            or Path(__file__).resolve().parents[1] / "prompts" / "job_email_extraction.md"
        )
        return resolved_prompt_path.read_text(encoding="utf-8")

    @staticmethod
    def _sender_domain(sender: str | None) -> str | None:
        if not sender:
            return None
        candidate = sender
        if "<" in candidate and ">" in candidate:
            candidate = candidate.split("<", 1)[1].split(">", 1)[0]
        if "@" not in candidate:
            return None
        domain = candidate.rsplit("@", 1)[1].strip().lower()
        return domain or None


def application_match_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "applicationId": {
                "type": ["string", "null"],
                "description": "The best matching application id, or null when none is safe.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence from 0.0 to 1.0 that this email belongs to applicationId.",
            },
            "explanation": {
                "type": "string",
                "description": "Short reason for the decision, including ambiguity when present.",
            },
        },
        "required": ["applicationId", "confidence", "explanation"],
    }


class GeminiApplicationMatchingService:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def model_name(self) -> str:
        return self._settings.gemini_model

    async def match_application(
        self,
        email: EmailRecord,
        extraction: JobEmailExtraction,
        candidates: list[ApplicationRecord],
    ) -> LlmApplicationMatchResponse:
        self._require_config()
        request_body = self._request_body(email, extraction, candidates)
        payload = await self._send_generate_content_request(request_body)
        text = self._extract_response_text(payload)
        try:
            return LlmApplicationMatchResponse.model_validate_json(text)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise GeminiResponseValidationError(
                "Gemini response did not match the application matching schema."
            ) from exc

    async def _send_generate_content_request(
        self,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self._settings.gemini_timeout_seconds,
            transport=self._transport,
        ) as client:
            try:
                response = await client.post(
                    self._generate_content_url(),
                    json=request_body,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "x-goog-api-key": self._settings.gemini_api_key or "",
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise GeminiTransientError("Gemini request did not complete.") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise GeminiTransientError(
                f"Gemini request failed with status {response.status_code}."
            )
        if response.status_code >= 400:
            raise GeminiApiError(
                f"Gemini request failed with status {response.status_code}."
            )
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise GeminiResponseValidationError(
                "Gemini response was not valid JSON."
            ) from exc
        return payload

    def _request_body(
        self,
        email: EmailRecord,
        extraction: JobEmailExtraction,
        candidates: list[ApplicationRecord],
    ) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Choose which existing job application this extracted "
                                "email update belongs to. Return null when the evidence "
                                "is ambiguous or insufficient.\n\n"
                                "Email:\n"
                                f"{json.dumps(self._email_payload(email), default=str)}\n\n"
                                "Extraction:\n"
                                f"{extraction.model_dump_json(by_alias=True)}\n\n"
                                "Candidate applications:\n"
                                f"{json.dumps(self._candidate_payload(candidates), default=str)}"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": application_match_json_schema(),
            },
        }

    @staticmethod
    def _email_payload(email: EmailRecord) -> dict[str, Any]:
        return {
            "id": email.id,
            "gmailMessageId": email.gmail_message_id,
            "sender": email.sender,
            "subject": email.subject,
            "receivedAt": email.received_at.isoformat() if email.received_at else None,
            "snippet": email.snippet,
        }

    @staticmethod
    def _candidate_payload(candidates: list[ApplicationRecord]) -> list[dict[str, Any]]:
        return [
            {
                "id": candidate.id,
                "companyName": candidate.company_name,
                "role": candidate.role,
                "jobId": candidate.job_id,
                "location": candidate.location,
                "currentStatus": candidate.current_status,
                "normalizedKeywords": candidate.normalized_keywords,
            }
            for candidate in candidates
        ]

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise GeminiResponseValidationError(
                "Gemini response did not include candidates."
            )

        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        text_parts = [
            part.get("text")
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        text = "".join(text_parts).strip()
        if not text:
            raise GeminiResponseValidationError(
                "Gemini response did not include JSON text."
            )
        return text

    def _generate_content_url(self) -> str:
        model_name = self._settings.gemini_model
        if model_name.startswith("models/"):
            model_name = model_name.removeprefix("models/")
        return f"{GEMINI_API_BASE_URL}/models/{model_name}:generateContent"

    def _require_config(self) -> None:
        if not self._settings.gemini_api_key:
            raise GeminiConfigurationError("Gemini API key is not configured.")
