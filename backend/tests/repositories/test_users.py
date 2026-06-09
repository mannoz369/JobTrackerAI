import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.security import TokenCipher
from app.models.user import GoogleUserProfile, OAuthTokenMetadata
from app.repositories.users import UsersRepository


class FakeUsersCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.indexes: list[tuple[Any, dict[str, Any]]] = []

    async def create_index(self, keys: Any, **kwargs: Any) -> None:
        self.indexes.append((keys, kwargs))

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        document = self._find(query)
        return deepcopy(document) if document is not None else None

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        document = self._find(query)
        if document is None:
            document = {"_id": "user_1"}
            document.update(deepcopy(update.get("$setOnInsert", {})))
            self.documents.append(document)

        for key, value in update.get("$set", {}).items():
            self._set_nested(document, key, value)

        return deepcopy(document)

    def _find(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    @staticmethod
    def _set_nested(document: dict[str, Any], dotted_key: str, value: Any) -> None:
        current = document
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value


class FakeDatabase:
    def __init__(self) -> None:
        self.users = FakeUsersCollection()

    def __getitem__(self, name: str) -> FakeUsersCollection:
        assert name == "users"
        return self.users


def test_token_cipher_encrypts_refresh_tokens() -> None:
    cipher = TokenCipher("test-secret")

    encrypted = cipher.encrypt("raw-refresh-token")

    assert encrypted != "raw-refresh-token"
    assert cipher.decrypt(encrypted) == "raw-refresh-token"


def test_upsert_google_user_persists_contract_and_indexes() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = UsersRepository(database)
        await repository.ensure_indexes()
        token_metadata = OAuthTokenMetadata(
            refresh_token_encrypted="encrypted-refresh-token",
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes=["openid", "email", "https://www.googleapis.com/auth/gmail.readonly"],
            token_type="Bearer",
        )

        user = await repository.upsert_google_user(
            GoogleUserProfile(
                google_sub="google-user-123",
                email="person@example.com",
                email_verified=True,
                name="Person Example",
                picture="https://example.com/avatar.png",
            ),
            token_metadata,
        )

        assert user.id == "user_1"
        assert user.google_sub == "google-user-123"
        assert user.monitored_email == "person@example.com"
        assert user.oauth.refresh_token_encrypted == "encrypted-refresh-token"
        assert user.gmail_watch.status == "not_registered"
        assert database.users.indexes

    asyncio.run(run())


def test_upsert_without_refresh_token_preserves_existing_refresh_token() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = UsersRepository(database)
        profile = GoogleUserProfile(
            google_sub="google-user-123",
            email="person@example.com",
            email_verified=True,
        )

        await repository.upsert_google_user(
            profile,
            OAuthTokenMetadata(refresh_token_encrypted="encrypted-refresh-token"),
        )
        user = await repository.upsert_google_user(
            profile,
            OAuthTokenMetadata(
                refresh_token_encrypted=None,
                scopes=["openid", "email"],
                token_type="Bearer",
            ),
        )

        assert user.oauth.refresh_token_encrypted == "encrypted-refresh-token"

    asyncio.run(run())
