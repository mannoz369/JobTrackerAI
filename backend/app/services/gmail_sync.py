import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

from app.core.config import Settings
from app.core.security import TokenCipher
from app.models.email import EmailCreate
from app.models.user import UserRecord
from app.repositories.emails import EmailsRepository
from app.repositories.users import UsersRepository
from app.services.gmail_api import GmailApiClient
from app.services.google_oauth import GoogleOAuthService


@dataclass(frozen=True)
class GmailSyncResult:
    user_id: str
    start_history_id: str | None
    latest_history_id: str | None
    changed_message_ids: list[str]
    saved_message_ids: list[str]


class GmailSyncError(RuntimeError):
    pass


class GmailSyncService:
    def __init__(
        self,
        settings: Settings,
        users_repository: UsersRepository,
        emails_repository: EmailsRepository,
        *,
        gmail_api_client: GmailApiClient | None = None,
        google_oauth_service: GoogleOAuthService | None = None,
        token_cipher: TokenCipher | None = None,
    ) -> None:
        self._settings = settings
        self._users_repository = users_repository
        self._emails_repository = emails_repository
        self._gmail_api_client = gmail_api_client or GmailApiClient(settings)
        self._google_oauth_service = google_oauth_service or GoogleOAuthService(settings)
        self._token_cipher = token_cipher or TokenCipher(
            settings.token_encryption_key or settings.session_secret_key
        )

    async def sync_user_history(
        self,
        user: UserRecord,
        notification_history_id: str | None = None,
    ) -> GmailSyncResult:
        if user.id is None:
            raise GmailSyncError("User record did not include an id.")

        start_history_id = user.gmail_watch.history_id
        if not start_history_id:
            if notification_history_id:
                await self._users_repository.update_last_processed_history_id(
                    user.id,
                    notification_history_id,
                )
            return GmailSyncResult(
                user_id=user.id,
                start_history_id=None,
                latest_history_id=notification_history_id,
                changed_message_ids=[],
                saved_message_ids=[],
            )

        refresh_token = self._decrypt_refresh_token(user)
        tokens = await self._google_oauth_service.refresh_access_token(refresh_token)
        history_response = await self._gmail_api_client.list_history(
            tokens.access_token,
            start_history_id,
        )
        message_ids = self._changed_message_ids(history_response.history)
        saved_message_ids: list[str] = []

        for message_id in message_ids:
            message = await self._gmail_api_client.get_message(
                tokens.access_token,
                message_id,
            )
            email = normalize_gmail_message(
                user_id=user.id,
                message=message,
                source_history_id=notification_history_id
                or history_response.history_id
                or start_history_id,
            )
            await self._emails_repository.upsert_email(email)
            saved_message_ids.append(email.gmail_message_id)

        latest_history_id = (
            notification_history_id or history_response.history_id or start_history_id
        )
        await self._users_repository.update_last_processed_history_id(
            user.id,
            latest_history_id,
        )
        return GmailSyncResult(
            user_id=user.id,
            start_history_id=start_history_id,
            latest_history_id=latest_history_id,
            changed_message_ids=message_ids,
            saved_message_ids=saved_message_ids,
        )

    def _decrypt_refresh_token(self, user: UserRecord) -> str:
        encrypted_refresh_token = user.oauth.refresh_token_encrypted
        if not encrypted_refresh_token:
            raise GmailSyncError("User does not have a refresh token.")
        return self._token_cipher.decrypt(encrypted_refresh_token)

    @staticmethod
    def _changed_message_ids(history: list[dict[str, Any]]) -> list[str]:
        message_ids: list[str] = []
        seen: set[str] = set()
        for history_item in history:
            for added in history_item.get("messagesAdded") or []:
                message = added.get("message") or {}
                message_id = message.get("id")
                if message_id is not None and str(message_id) not in seen:
                    seen.add(str(message_id))
                    message_ids.append(str(message_id))
        return message_ids


def normalize_gmail_message(
    *,
    user_id: str,
    message: dict[str, Any],
    source_history_id: str | None = None,
) -> EmailCreate:
    message_id = str(message.get("id") or "")
    if not message_id:
        raise GmailSyncError("Gmail message did not include an id.")

    payload = message.get("payload") or {}
    headers = _headers_by_name(payload.get("headers") or [])
    internal_date = _parse_internal_date(message.get("internalDate"))

    return EmailCreate(
        user_id=user_id,
        gmail_message_id=message_id,
        thread_id=message.get("threadId"),
        sender=headers.get("from"),
        recipients=_recipients(headers),
        subject=headers.get("subject"),
        received_at=internal_date or _parse_header_date(headers.get("date")),
        labels=[str(label) for label in message.get("labelIds") or []],
        snippet=message.get("snippet"),
        body_text=_extract_body_text(payload),
        source_history_id=source_history_id,
    )


def _headers_by_name(headers: list[dict[str, Any]]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for header in headers:
        name = header.get("name")
        value = header.get("value")
        if name and value is not None:
            normalized[str(name).lower()] = str(value)
    return normalized


def _recipients(headers: dict[str, str]) -> list[str]:
    values = [
        headers.get("to", ""),
        headers.get("cc", ""),
        headers.get("bcc", ""),
    ]
    recipients: list[str] = []
    for name, address in getaddresses(values):
        recipients.append(address or name)
    return [recipient for recipient in recipients if recipient]


def _parse_internal_date(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        millis = int(str(value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000, timezone.utc)


def _parse_header_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_body_text(payload: dict[str, Any]) -> str | None:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    _collect_body_parts(payload, plain_parts, html_parts)
    if plain_parts:
        return _normalize_text("\n".join(plain_parts))
    if html_parts:
        return _normalize_text(_html_to_text("\n".join(html_parts)))
    return None


def _collect_body_parts(
    payload: dict[str, Any],
    plain_parts: list[str],
    html_parts: list[str],
) -> None:
    mime_type = str(payload.get("mimeType") or "").lower()
    data = (payload.get("body") or {}).get("data")
    if data and mime_type == "text/plain":
        plain_parts.append(_decode_body_data(str(data)))
    elif data and mime_type == "text/html":
        html_parts.append(_decode_body_data(str(data)))

    for part in payload.get("parts") or []:
        if isinstance(part, dict):
            _collect_body_parts(part, plain_parts, html_parts)


def _decode_body_data(data: str) -> str:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}").decode(
        "utf-8",
        errors="replace",
    )


def _normalize_text(text: str) -> str:
    normalized_lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    collapsed = "\n".join(line for line in normalized_lines if line)
    return collapsed or ""


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return unescape(parser.text)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() in {"br", "div", "p", "li", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)
