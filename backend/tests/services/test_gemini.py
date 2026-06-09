import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.models.email import EmailCreate
from app.services.gemini import (
    GeminiConfigurationError,
    GeminiEmailExtractionService,
    GeminiResponseValidationError,
)


async def no_sleep(_: float) -> None:
    return None


def extraction_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "isJobRelated": True,
        "company": "Acme",
        "role": "Backend Engineer",
        "jobId": "ACME-42",
        "location": "Remote",
        "emailType": "ApplicationConfirmation",
        "statusSignal": "Applied",
        "dates": [],
        "senderDomain": "jobs.acme.example",
        "confidence": 0.88,
        "evidence": [
            {
                "field": "statusSignal",
                "snippet": "Thank you for applying.",
            }
        ],
        "ambiguousIndicators": [],
        "uniqueKeywords": ["ACME-42", "Remote", "jobs.acme.example"],
        "reviewReason": None,
    }
    payload.update(overrides)
    return payload


def email_create() -> EmailCreate:
    return EmailCreate(
        user_id="user_123",
        gmail_message_id="gmail-message-1",
        thread_id="thread-1",
        sender="Recruiting <jobs@jobs.acme.example>",
        recipients=["person@example.com"],
        subject="Thanks for applying to Backend Engineer",
        received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        labels=["INBOX"],
        snippet="Thank you for applying.",
        body_text="Thank you for applying to Backend Engineer, requisition ACME-42.",
    )


def make_settings() -> Settings:
    return Settings(
        gemini_api_key="gemini-key",
        gemini_retry_backoff_seconds=0,
    )


def response_with_text(text: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
    )


def test_extract_email_posts_json_schema_request_and_validates_response() -> None:
    async def run() -> None:
        requests: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            requests.append(body)
            assert str(request.url).endswith(
                "/v1beta/models/gemini-2.5-flash:generateContent"
            )
            assert request.headers["x-goog-api-key"] == "gemini-key"
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            assert "uniqueKeywords" in body["generationConfig"]["responseJsonSchema"][
                "required"
            ]
            prompt_text = body["contents"][0]["parts"][0]["text"]
            assert "Thanks for applying to Backend Engineer" in prompt_text
            assert "jobs.acme.example" in prompt_text
            return response_with_text(json.dumps(extraction_payload()))

        service = GeminiEmailExtractionService(
            make_settings(),
            transport=httpx.MockTransport(handler),
            sleep=no_sleep,
        )

        extraction = await service.extract_email(email_create())

        assert len(requests) == 1
        assert extraction.company == "Acme"
        assert extraction.job_id == "ACME-42"
        assert extraction.status_signal == "Applied"

    asyncio.run(run())


def test_extract_email_retries_transient_gemini_errors() -> None:
    async def run() -> None:
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(503, json={"error": "unavailable"})
            return response_with_text(json.dumps(extraction_payload()))

        service = GeminiEmailExtractionService(
            make_settings(),
            transport=httpx.MockTransport(handler),
            sleep=no_sleep,
        )

        extraction = await service.extract_email(email_create())

        assert calls == 2
        assert extraction.email_type == "ApplicationConfirmation"

    asyncio.run(run())


def test_extract_email_rejects_invalid_model_json() -> None:
    async def run() -> None:
        service = GeminiEmailExtractionService(
            make_settings(),
            transport=httpx.MockTransport(
                lambda _: response_with_text("not-json")
            ),
            sleep=no_sleep,
        )

        with pytest.raises(GeminiResponseValidationError):
            await service.extract_email(email_create())

    asyncio.run(run())


def test_extract_email_requires_api_key() -> None:
    async def run() -> None:
        service = GeminiEmailExtractionService(
            Settings(gemini_api_key=None),
            transport=httpx.MockTransport(
                lambda _: response_with_text(json.dumps(extraction_payload()))
            ),
            sleep=no_sleep,
        )

        with pytest.raises(GeminiConfigurationError):
            await service.extract_email(email_create())

    asyncio.run(run())
