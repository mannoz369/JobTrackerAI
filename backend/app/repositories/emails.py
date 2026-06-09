from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.models.email import EmailCreate, EmailProcessingState, EmailRecord
from app.models.extraction import JobEmailExtraction


class EmailsRepository:
    def __init__(self, database: Any) -> None:
        self.collection = database["emails"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("user_id", ASCENDING), ("gmail_message_id", ASCENDING)],
            unique=True,
            name="emails_user_gmail_message_unique",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING), ("received_at", DESCENDING)],
            name="emails_user_received_lookup",
        )
        await self.collection.create_index(
            [("processing_state", ASCENDING), ("updated_at", ASCENDING)],
            name="emails_processing_state_lookup",
        )
        await self.collection.create_index(
            [
                ("user_id", ASCENDING),
                ("application_id", ASCENDING),
                ("received_at", DESCENDING),
            ],
            name="emails_user_application_lookup",
        )

    async def get_by_user_and_message_id(
        self,
        user_id: str,
        gmail_message_id: str,
    ) -> EmailRecord | None:
        document = await self.collection.find_one(
            {"user_id": user_id, "gmail_message_id": gmail_message_id}
        )
        if document is None:
            return None
        return EmailRecord.model_validate(document)

    async def get_for_user(
        self,
        user_id: str,
        email_id: str,
    ) -> EmailRecord | None:
        document = await self.collection.find_one(
            {
                "_id": self._mongo_id(email_id),
                "user_id": user_id,
            }
        )
        if document is None:
            return None
        return EmailRecord.model_validate(document)

    async def list_needs_review(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[EmailRecord]:
        if limit <= 0:
            return []

        cursor = (
            self.collection.find(
                {
                    "user_id": user_id,
                    "processing_state": "needs_review",
                }
            )
            .sort("updated_at", ASCENDING)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        return [EmailRecord.model_validate(document) for document in documents]

    async def count_needs_review(self, user_id: str) -> int:
        return await self.collection.count_documents(
            {
                "user_id": user_id,
                "processing_state": "needs_review",
            }
        )

    async def upsert_email(self, email: EmailCreate) -> EmailRecord:
        now = datetime.now(timezone.utc)
        payload = email.model_dump(mode="python")
        processing_state = payload.pop("processing_state")
        update_fields = {
            **payload,
            "updated_at": now,
        }

        document = await self.collection.find_one_and_update(
            {
                "user_id": email.user_id,
                "gmail_message_id": email.gmail_message_id,
            },
            {
                "$set": update_fields,
                "$setOnInsert": {
                    "created_at": now,
                    "processing_state": processing_state,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return EmailRecord.model_validate(document)

    async def list_pending_extraction(self, limit: int) -> list[EmailRecord]:
        if limit <= 0:
            return []

        cursor = (
            self.collection.find({"processing_state": "pending_extraction"})
            .sort("updated_at", ASCENDING)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        return [EmailRecord.model_validate(document) for document in documents]

    async def store_extraction_result(
        self,
        email_id: str,
        extraction: JobEmailExtraction,
        processing_state: EmailProcessingState,
        *,
        model_name: str,
        extracted_at: datetime | None = None,
    ) -> EmailRecord | None:
        now = datetime.now(timezone.utc)
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(email_id)},
            {
                "$set": {
                    "extraction": extraction.model_dump(mode="json", by_alias=True),
                    "processing_state": processing_state,
                    "extraction_model": model_name,
                    "extracted_at": extracted_at or now,
                    "extraction_error": None,
                    "updated_at": now,
                },
                "$inc": {"extraction_attempts": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return EmailRecord.model_validate(document)

    async def mark_extraction_failed(
        self,
        email_id: str,
        error: str,
        *,
        model_name: str | None = None,
    ) -> EmailRecord | None:
        now = datetime.now(timezone.utc)
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(email_id)},
            {
                "$set": {
                    "processing_state": "extraction_failed",
                    "extraction_model": model_name,
                    "extraction_error": error[:500],
                    "updated_at": now,
                },
                "$inc": {"extraction_attempts": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return EmailRecord.model_validate(document)

    async def defer_extraction(
        self,
        email_id: str,
        error: str,
        *,
        model_name: str | None = None,
    ) -> EmailRecord | None:
        now = datetime.now(timezone.utc)
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(email_id)},
            {
                "$set": {
                    "processing_state": "pending_extraction",
                    "extraction_model": model_name,
                    "extraction_error": error[:500],
                    "updated_at": now,
                },
                "$inc": {"extraction_attempts": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return EmailRecord.model_validate(document)

    async def store_application_match_result(
        self,
        email_id: str,
        processing_state: EmailProcessingState,
        *,
        matching_result: dict[str, Any],
        application_id: str | None = None,
        status_update_id: str | None = None,
        review_reason: str | None = None,
        matched_at: datetime | None = None,
    ) -> EmailRecord | None:
        now = datetime.now(timezone.utc)
        update_fields: dict[str, Any] = {
            "processing_state": processing_state,
            "matching_result": matching_result,
            "application_id": application_id,
            "status_update_id": status_update_id,
            "application_review_reason": review_reason,
            "matched_at": matched_at if application_id is not None else None,
            "updated_at": now,
        }
        if application_id is not None and matched_at is None:
            update_fields["matched_at"] = now

        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(email_id)},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return EmailRecord.model_validate(document)

    async def store_application_match_result_for_user(
        self,
        user_id: str,
        email_id: str,
        processing_state: EmailProcessingState,
        *,
        matching_result: dict[str, Any],
        application_id: str | None = None,
        status_update_id: str | None = None,
        review_reason: str | None = None,
        matched_at: datetime | None = None,
    ) -> EmailRecord | None:
        now = datetime.now(timezone.utc)
        update_fields: dict[str, Any] = {
            "processing_state": processing_state,
            "matching_result": matching_result,
            "application_id": application_id,
            "status_update_id": status_update_id,
            "application_review_reason": review_reason,
            "matched_at": matched_at if application_id is not None else None,
            "updated_at": now,
        }
        if application_id is not None and matched_at is None:
            update_fields["matched_at"] = now

        document = await self.collection.find_one_and_update(
            {
                "_id": self._mongo_id(email_id),
                "user_id": user_id,
            },
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return EmailRecord.model_validate(document)

    async def clear_application_links_for_user(
        self,
        user_id: str,
        application_id: str,
    ) -> int:
        result = await self.collection.update_many(
            {
                "user_id": user_id,
                "application_id": application_id,
            },
            {
                "$set": {
                    "processing_state": "needs_review",
                    "application_id": None,
                    "status_update_id": None,
                    "matching_result": None,
                    "application_review_reason": "Application was deleted. Review or dismiss this email.",
                    "matched_at": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return result.modified_count

    @staticmethod
    def _mongo_id(email_id: str) -> str | ObjectId:
        if ObjectId.is_valid(email_id):
            return ObjectId(email_id)
        return email_id
