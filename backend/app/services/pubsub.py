import base64
import binascii
import json
import secrets
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


class PubSubValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GmailPubSubNotification:
    email_address: str
    history_id: str
    message_id: str | None
    subscription: str | None


class PubSubService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def parse_gmail_notification(
        self,
        payload: dict[str, Any],
        *,
        verification_token: str | None = None,
    ) -> GmailPubSubNotification:
        self._validate_verification_token(verification_token)
        subscription = payload.get("subscription")
        expected_subscription = self._settings.gmail_pubsub_subscription
        if expected_subscription and subscription != expected_subscription:
            raise PubSubValidationError("Pub/Sub subscription did not match.")

        message = payload.get("message")
        if not isinstance(message, dict):
            raise PubSubValidationError("Pub/Sub payload did not include a message.")

        encoded_data = message.get("data")
        if not isinstance(encoded_data, str) or not encoded_data:
            raise PubSubValidationError("Pub/Sub message did not include data.")

        notification_payload = self._decode_json_data(encoded_data)
        email_address = str(notification_payload.get("emailAddress") or "").strip().lower()
        history_id = str(notification_payload.get("historyId") or "").strip()
        if not email_address or not history_id:
            raise PubSubValidationError("Gmail notification was missing required data.")

        return GmailPubSubNotification(
            email_address=email_address,
            history_id=history_id,
            message_id=message.get("messageId") or message.get("message_id"),
            subscription=subscription,
        )

    def _validate_verification_token(self, verification_token: str | None) -> None:
        expected_token = self._settings.gmail_pubsub_verification_token
        if expected_token is None:
            return
        if verification_token is None or not secrets.compare_digest(
            verification_token,
            expected_token,
        ):
            raise PubSubValidationError("Pub/Sub verification token was invalid.")

    @staticmethod
    def _decode_json_data(encoded_data: str) -> dict[str, Any]:
        padding = "=" * (-len(encoded_data) % 4)
        try:
            decoded = base64.urlsafe_b64decode(f"{encoded_data}{padding}")
            payload = json.loads(decoded.decode("utf-8"))
        except (
            binascii.Error,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise PubSubValidationError("Pub/Sub data was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise PubSubValidationError("Pub/Sub data was not a JSON object.")
        return payload
