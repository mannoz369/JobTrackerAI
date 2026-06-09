from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings


GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailApiError(RuntimeError):
    pass


class GmailApiConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GmailWatchRegistration:
    history_id: str
    expiration: datetime


@dataclass(frozen=True)
class GmailHistoryResponse:
    history: list[dict[str, Any]]
    history_id: str | None


@dataclass(frozen=True)
class GmailMessageListResponse:
    message_ids: list[str]
    next_page_token: str | None
    result_size_estimate: int | None = None


class GmailApiClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def watch_mailbox(self, access_token: str) -> GmailWatchRegistration:
        if not self._settings.gmail_pubsub_topic:
            raise GmailApiConfigurationError("Gmail Pub/Sub topic is not configured.")

        body: dict[str, Any] = {"topicName": self._settings.gmail_pubsub_topic}
        if self._settings.gmail_watch_label_ids:
            body["labelIds"] = self._settings.gmail_watch_label_ids

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{GMAIL_API_BASE_URL}/watch",
                json=body,
                headers=self._authorization_headers(access_token),
            )

        if response.status_code >= 400:
            raise GmailApiError("Gmail watch registration failed.")

        payload = response.json()
        history_id = payload.get("historyId")
        expiration = payload.get("expiration")
        if not history_id or not expiration:
            raise GmailApiError("Gmail watch response was missing metadata.")

        return GmailWatchRegistration(
            history_id=str(history_id),
            expiration=self._datetime_from_millis(expiration),
        )

    async def list_history(
        self,
        access_token: str,
        start_history_id: str,
    ) -> GmailHistoryResponse:
        history: list[dict[str, Any]] = []
        latest_history_id: str | None = None
        params: dict[str, Any] = {
            "startHistoryId": start_history_id,
            "historyTypes": "messageAdded",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                response = await client.get(
                    f"{GMAIL_API_BASE_URL}/history",
                    params=params,
                    headers=self._authorization_headers(access_token),
                )
                if response.status_code >= 400:
                    raise GmailApiError("Gmail history synchronization failed.")

                payload = response.json()
                history.extend(payload.get("history") or [])
                if payload.get("historyId") is not None:
                    latest_history_id = str(payload["historyId"])

                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
                params["pageToken"] = page_token

        return GmailHistoryResponse(history=history, history_id=latest_history_id)

    async def list_messages(
        self,
        access_token: str,
        *,
        query: str,
        page_token: str | None = None,
        max_results: int = 25,
    ) -> GmailMessageListResponse:
        params: dict[str, Any] = {
            "q": query,
            "maxResults": max_results,
        }
        if page_token is not None:
            params["pageToken"] = page_token

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{GMAIL_API_BASE_URL}/messages",
                params=params,
                headers=self._authorization_headers(access_token),
            )

        if response.status_code >= 400:
            raise GmailApiError("Gmail message search failed.")

        payload = response.json()
        message_ids = [
            str(message["id"])
            for message in payload.get("messages") or []
            if isinstance(message, dict) and message.get("id") is not None
        ]
        result_size_estimate = payload.get("resultSizeEstimate")
        return GmailMessageListResponse(
            message_ids=message_ids,
            next_page_token=payload.get("nextPageToken"),
            result_size_estimate=int(result_size_estimate)
            if result_size_estimate is not None
            else None,
        )

    async def get_message(self, access_token: str, message_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{GMAIL_API_BASE_URL}/messages/{message_id}",
                params={"format": "full"},
                headers=self._authorization_headers(access_token),
            )

        if response.status_code >= 400:
            raise GmailApiError("Gmail message fetch failed.")
        payload: dict[str, Any] = response.json()
        return payload

    @staticmethod
    def _authorization_headers(access_token: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

    @staticmethod
    def _datetime_from_millis(value: object) -> datetime:
        try:
            millis = int(str(value))
        except (TypeError, ValueError) as exc:
            raise GmailApiError("Gmail timestamp was invalid.") from exc
        return datetime.fromtimestamp(millis / 1000, timezone.utc)
