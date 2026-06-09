from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.models.backfill import BackfillJobCreate, BackfillJobRecord


ACTIVE_BACKFILL_STATUSES = ("pending", "running")


class BackfillJobsRepository:
    def __init__(self, database: Any) -> None:
        self.collection = database["backfill_jobs"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="backfill_jobs_user_created_lookup",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING), ("status", ASCENDING)],
            name="backfill_jobs_user_status_lookup",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING)],
            unique=True,
            partialFilterExpression={
                "status": {"$in": list(ACTIVE_BACKFILL_STATUSES)}
            },
            name="backfill_jobs_user_active_unique",
        )

    async def create_job(self, job: BackfillJobCreate) -> BackfillJobRecord:
        now = datetime.now(timezone.utc)
        document = job.model_dump(mode="python")
        document["start_date"] = job.start_date.isoformat()
        document["created_at"] = now
        document["updated_at"] = now
        result = await self.collection.insert_one(document)
        created = await self.collection.find_one({"_id": result.inserted_id})
        return BackfillJobRecord.model_validate(created)

    async def get_by_id(self, job_id: str) -> BackfillJobRecord | None:
        document = await self.collection.find_one({"_id": self._mongo_id(job_id)})
        if document is None:
            return None
        return BackfillJobRecord.model_validate(document)

    async def get_for_user(
        self,
        user_id: str,
        job_id: str,
    ) -> BackfillJobRecord | None:
        document = await self.collection.find_one(
            {
                "_id": self._mongo_id(job_id),
                "user_id": user_id,
            }
        )
        if document is None:
            return None
        return BackfillJobRecord.model_validate(document)

    async def get_latest_for_user(self, user_id: str) -> BackfillJobRecord | None:
        cursor = (
            self.collection.find({"user_id": user_id})
            .sort("created_at", DESCENDING)
            .limit(1)
        )
        documents = await cursor.to_list(length=1)
        if not documents:
            return None
        return BackfillJobRecord.model_validate(documents[0])

    async def get_active_for_user(self, user_id: str) -> BackfillJobRecord | None:
        document = await self.collection.find_one(
            {
                "user_id": user_id,
                "status": {"$in": list(ACTIVE_BACKFILL_STATUSES)},
            }
        )
        if document is None:
            return None
        return BackfillJobRecord.model_validate(document)

    async def mark_running(self, job_id: str) -> BackfillJobRecord | None:
        now = datetime.now(timezone.utc)
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(job_id)},
            {
                "$set": {
                    "status": "running",
                    "started_at": now,
                    "completed_at": None,
                    "last_error": None,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return BackfillJobRecord.model_validate(document)

    async def reset_for_retry(
        self,
        job_id: str,
        *,
        gmail_query: str | None = None,
    ) -> BackfillJobRecord | None:
        now = datetime.now(timezone.utc)
        set_fields: dict[str, Any] = {
            "status": "pending",
            "last_error": None,
            "completed_at": None,
            "updated_at": now,
        }
        if gmail_query is not None:
            set_fields["gmail_query"] = gmail_query
            set_fields["page_token"] = None
            set_fields["fetched_count"] = 0
            set_fields["saved_count"] = 0
            set_fields["duplicate_count"] = 0
            set_fields["processed_count"] = 0
            set_fields["extracted_count"] = 0
            set_fields["non_job_count"] = 0
            set_fields["needs_review_count"] = 0
            set_fields["failed_count"] = 0
            set_fields["matched_count"] = 0
            set_fields["created_count"] = 0
            set_fields["errors"] = []

        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(job_id)},
            {"$set": set_fields},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return BackfillJobRecord.model_validate(document)

    async def update_progress(
        self,
        job_id: str,
        *,
        page_token: str | None,
        increments: dict[str, int],
        error: str | None = None,
    ) -> BackfillJobRecord | None:
        now = datetime.now(timezone.utc)
        update: dict[str, Any] = {
            "$set": {
                "page_token": page_token,
                "updated_at": now,
            }
        }
        non_zero_increments = {
            field: value for field, value in increments.items() if value
        }
        if non_zero_increments:
            update["$inc"] = non_zero_increments
        if error:
            safe_error = error[:500]
            update["$set"]["last_error"] = safe_error
            update["$push"] = {"errors": safe_error}

        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(job_id)},
            update,
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return BackfillJobRecord.model_validate(document)

    async def mark_succeeded(self, job_id: str) -> BackfillJobRecord | None:
        now = datetime.now(timezone.utc)
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(job_id)},
            {
                "$set": {
                    "status": "succeeded",
                    "page_token": None,
                    "last_error": None,
                    "completed_at": now,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return BackfillJobRecord.model_validate(document)

    async def mark_failed(
        self,
        job_id: str,
        error: str,
    ) -> BackfillJobRecord | None:
        now = datetime.now(timezone.utc)
        safe_error = error[:500]
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(job_id)},
            {
                "$set": {
                    "status": "failed",
                    "last_error": safe_error,
                    "completed_at": now,
                    "updated_at": now,
                },
                "$push": {"errors": safe_error},
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return BackfillJobRecord.model_validate(document)

    @staticmethod
    def _mongo_id(job_id: str) -> str | ObjectId:
        if ObjectId.is_valid(job_id):
            return ObjectId(job_id)
        return job_id
