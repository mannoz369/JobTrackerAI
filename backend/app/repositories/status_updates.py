from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from app.models.status_update import StatusUpdateCreate, StatusUpdateRecord


class StatusUpdatesRepository:
    def __init__(self, database: Any) -> None:
        self.collection = database["status_updates"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [
                ("user_id", ASCENDING),
                ("application_id", ASCENDING),
                ("created_at", DESCENDING),
            ],
            name="status_updates_user_application_lookup",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING), ("email_id", ASCENDING)],
            unique=True,
            partialFilterExpression={"email_id": {"$type": "string"}},
            name="status_updates_user_email_unique",
        )

    async def create_status_update(
        self,
        status_update: StatusUpdateCreate,
    ) -> StatusUpdateRecord:
        document = status_update.model_dump(mode="python")
        document["created_at"] = datetime.now(timezone.utc)
        result = await self.collection.insert_one(document)
        created = await self.collection.find_one({"_id": result.inserted_id})
        return StatusUpdateRecord.model_validate(created)

    async def get_by_email_id(
        self,
        user_id: str,
        email_id: str,
    ) -> StatusUpdateRecord | None:
        document = await self.collection.find_one(
            {
                "user_id": user_id,
                "email_id": email_id,
            }
        )
        if document is None:
            return None
        return StatusUpdateRecord.model_validate(document)

    async def list_for_application(
        self,
        user_id: str,
        application_id: str,
        *,
        limit: int = 50,
    ) -> list[StatusUpdateRecord]:
        if limit <= 0:
            return []
        cursor = (
            self.collection.find(
                {
                    "user_id": user_id,
                    "application_id": application_id,
                }
            )
            .sort("created_at", DESCENDING)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        return [StatusUpdateRecord.model_validate(document) for document in documents]

    async def delete_for_application(
        self,
        user_id: str,
        application_id: str,
    ) -> int:
        result = await self.collection.delete_many(
            {
                "user_id": user_id,
                "application_id": application_id,
            }
        )
        return result.deleted_count
