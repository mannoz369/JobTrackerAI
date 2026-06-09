import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _coerce_fernet_key(secret: str) -> bytes:
    encoded = secret.encode("utf-8")
    try:
        decoded = base64.urlsafe_b64decode(encoded)
    except Exception:
        return _derive_fernet_key(secret)

    if len(decoded) == 32:
        return encoded
    return _derive_fernet_key(secret)


class TokenCipher:
    def __init__(self, secret: str) -> None:
        self._fernet = Fernet(_coerce_fernet_key(secret))

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_token: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_token.encode("utf-8")).decode(
                "utf-8"
            )
        except InvalidToken as exc:
            raise ValueError("Invalid encrypted token.") from exc


@dataclass(frozen=True)
class SessionPayload:
    user_id: str
    email: str
    expires_at: datetime


class SessionSigner:
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def create_session(
        self,
        *,
        user_id: str,
        email: str,
        max_age_seconds: int,
    ) -> str:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)
        payload = {
            "sub": user_id,
            "email": email,
            "exp": int(expires_at.timestamp()),
        }
        body = _base64url_encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        signature = self._sign(body)
        return f"{body}.{signature}"

    def verify_session(self, session_token: str | None) -> SessionPayload | None:
        if not session_token:
            return None

        try:
            body, signature = session_token.split(".", 1)
        except ValueError:
            return None

        expected = self._sign(body)
        if not hmac.compare_digest(signature, expected):
            return None

        try:
            payload: dict[str, Any] = json.loads(_base64url_decode(body))
            expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
            user_id = str(payload["sub"])
            email = str(payload["email"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

        if expires_at <= datetime.now(timezone.utc):
            return None

        return SessionPayload(user_id=user_id, email=email, expires_at=expires_at)

    def _sign(self, body: str) -> str:
        digest = hmac.new(self._secret, body.encode("utf-8"), hashlib.sha256).digest()
        return _base64url_encode(digest)
