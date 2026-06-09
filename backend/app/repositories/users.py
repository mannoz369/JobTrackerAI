from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, ReturnDocument

from app.models.user import (
    GmailWatchState,
    GoogleUserProfile,
    OAuthTokenMetadata,
    UserRecord,
)


class UsersRepository:
    def __init__(self, database: Any) -> None:
        self.collection = database["users"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("google_sub", ASCENDING)],
            unique=True,
            name="users_google_sub_unique",
        )
        await self.collection.create_index(
            [("email", ASCENDING)],
            name="users_email_lookup",
        )
        await self.collection.create_index(
            [("monitored_email", ASCENDING)],
            name="users_monitored_email_lookup",
        )

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        mongo_id: str | ObjectId = user_id
        if ObjectId.is_valid(user_id):
            mongo_id = ObjectId(user_id)

        document = await self.collection.find_one({"_id": mongo_id})
        if document is None:
            return None
        return UserRecord.model_validate(document)

    async def get_by_google_sub(self, google_sub: str) -> UserRecord | None:
        document = await self.collection.find_one({"google_sub": google_sub})
        if document is None:
            return None
        return UserRecord.model_validate(document)

    async def get_by_monitored_email(self, monitored_email: str) -> UserRecord | None:
        normalized_email = monitored_email.strip().lower()
        document = await self.collection.find_one({"monitored_email": normalized_email})
        if document is None and normalized_email != monitored_email:
            document = await self.collection.find_one({"monitored_email": monitored_email})
        if document is None:
            return None
        return UserRecord.model_validate(document)

    async def list_users_needing_watch_renewal(
        self,
        renew_before: datetime,
    ) -> list[UserRecord]:
        cursor = self.collection.find(
            {
                "oauth.refresh_token_encrypted": {"$ne": None},
                "$or": [
                    {"gmail_watch.status": {"$ne": "registered"}},
                    {"gmail_watch.expiration": {"$lte": renew_before}},
                    {"gmail_watch.expiration": None},
                    {"gmail_watch.expiration": {"$exists": False}},
                ],
            }
        ).sort("gmail_watch.expiration", ASCENDING)
        documents = await cursor.to_list(length=None)
        return [UserRecord.model_validate(document) for document in documents]

    async def update_gmail_watch_state(
        self,
        user_id: str,
        gmail_watch: GmailWatchState,
    ) -> UserRecord | None:
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(user_id)},
            {
                "$set": {
                    "gmail_watch": gmail_watch.model_dump(mode="python"),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return UserRecord.model_validate(document)

    async def update_last_processed_history_id(
        self,
        user_id: str,
        history_id: str,
    ) -> UserRecord | None:
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(user_id)},
            {
                "$set": {
                    "gmail_watch.history_id": history_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return UserRecord.model_validate(document)

    async def upsert_google_user(
        self,
        profile: GoogleUserProfile,
        token_metadata: OAuthTokenMetadata,
    ) -> UserRecord:
        now = datetime.now(timezone.utc)
        update_fields: dict[str, Any] = {
            "google_sub": profile.google_sub,
            "email": profile.email,
            "email_verified": profile.email_verified,
            "monitored_email": profile.email,
            "name": profile.name,
            "picture": profile.picture,
            "oauth.access_token_expires_at": token_metadata.access_token_expires_at,
            "oauth.scopes": token_metadata.scopes,
            "oauth.token_type": token_metadata.token_type,
            "oauth.last_refreshed_at": now,
            "updated_at": now,
        }
        if token_metadata.refresh_token_encrypted is not None:
            update_fields["oauth.refresh_token_encrypted"] = (
                token_metadata.refresh_token_encrypted
            )

        document = await self.collection.find_one_and_update(
            {"google_sub": profile.google_sub},
            {
                "$set": update_fields,
                "$setOnInsert": {
                    "created_at": now,
                    "gmail_watch": GmailWatchState().model_dump(mode="python"),
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return UserRecord.model_validate(document)

    @staticmethod
    def _mongo_id(user_id: str) -> str | ObjectId:
        if ObjectId.is_valid(user_id):
            return ObjectId(user_id)
        return user_id
