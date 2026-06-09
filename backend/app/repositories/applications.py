from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.models.application import (
    ApplicationCreate,
    ApplicationRecord,
    ApplicationStatus,
    normalize_keywords,
    normalize_match_text,
)


class ApplicationsRepository:
    def __init__(self, database: Any) -> None:
        self.collection = database["applications"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("user_id", ASCENDING), ("normalized_job_id", ASCENDING)],
            unique=True,
            partialFilterExpression={"normalized_job_id": {"$type": "string"}},
            name="applications_user_job_id_unique",
        )
        await self.collection.create_index(
            [
                ("user_id", ASCENDING),
                ("normalized_company", ASCENDING),
                ("normalized_role", ASCENDING),
            ],
            name="applications_user_company_role_lookup",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING), ("company_id", ASCENDING)],
            name="applications_user_company_lookup",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING), ("normalized_keywords", ASCENDING)],
            name="applications_user_keywords_lookup",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING), ("current_status", ASCENDING)],
            name="applications_user_status_lookup",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="applications_user_updated_lookup",
        )

    async def create_application(
        self,
        application: ApplicationCreate,
    ) -> ApplicationRecord:
        now = datetime.now(timezone.utc)
        document = application.model_dump(mode="python")
        document["created_at"] = now
        document["updated_at"] = now

        result = await self.collection.insert_one(document)
        created = await self.collection.find_one({"_id": result.inserted_id})
        return ApplicationRecord.model_validate(created)

    async def get_by_id(self, application_id: str) -> ApplicationRecord | None:
        document = await self.collection.find_one(
            {"_id": self._mongo_id(application_id)}
        )
        if document is None:
            return None
        return ApplicationRecord.model_validate(document)

    async def get_for_user(
        self,
        user_id: str,
        application_id: str,
    ) -> ApplicationRecord | None:
        document = await self.collection.find_one(
            {
                "_id": self._mongo_id(application_id),
                "user_id": user_id,
            }
        )
        if document is None:
            return None
        return ApplicationRecord.model_validate(document)

    async def list_for_user(
        self,
        user_id: str,
        *,
        statuses: list[ApplicationStatus] | None = None,
        limit: int = 100,
    ) -> list[ApplicationRecord]:
        if limit <= 0:
            return []

        query: dict[str, Any] = {"user_id": user_id}
        if statuses:
            query["current_status"] = {"$in": statuses}

        cursor = (
            self.collection.find(query)
            .sort("updated_at", DESCENDING)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        return [ApplicationRecord.model_validate(document) for document in documents]

    async def list_by_ids(
        self,
        user_id: str,
        application_ids: list[str],
    ) -> list[ApplicationRecord]:
        mongo_ids = [self._mongo_id(application_id) for application_id in application_ids]
        if not mongo_ids:
            return []

        cursor = self.collection.find(
            {
                "user_id": user_id,
                "_id": {"$in": mongo_ids},
            }
        )
        documents = await cursor.to_list(length=len(mongo_ids))
        records = [ApplicationRecord.model_validate(document) for document in documents]
        by_id = {record.id: record for record in records}
        return [
            by_id[application_id]
            for application_id in application_ids
            if application_id in by_id
        ]

    async def count_by_status(self, user_id: str) -> dict[ApplicationStatus, int]:
        cursor = self.collection.aggregate(
            [
                {"$match": {"user_id": user_id}},
                {"$group": {"_id": "$current_status", "count": {"$sum": 1}}},
            ]
        )
        documents = await cursor.to_list(length=None)
        return {
            document["_id"]: document["count"]
            for document in documents
            if document["_id"] is not None
        }

    async def list_by_job_id(
        self,
        user_id: str,
        job_id: str,
    ) -> list[ApplicationRecord]:
        normalized_job_id = normalize_match_text(job_id)
        if normalized_job_id is None:
            return []

        cursor = self.collection.find(
            {
                "user_id": user_id,
                "normalized_job_id": normalized_job_id,
            }
        )
        documents = await cursor.to_list(length=None)
        return [ApplicationRecord.model_validate(document) for document in documents]

    async def list_by_company_and_role(
        self,
        user_id: str,
        company: str,
        role: str,
    ) -> list[ApplicationRecord]:
        normalized_company = normalize_match_text(company)
        normalized_role = normalize_match_text(role)
        if normalized_company is None or normalized_role is None:
            return []

        cursor = self.collection.find(
            {
                "user_id": user_id,
                "normalized_company": normalized_company,
                "normalized_role": normalized_role,
            }
        )
        documents = await cursor.to_list(length=None)
        return [ApplicationRecord.model_validate(document) for document in documents]

    async def list_candidates(
        self,
        user_id: str,
        *,
        company: str | None = None,
        keywords: list[str] | None = None,
        limit: int = 10,
    ) -> list[ApplicationRecord]:
        if limit <= 0:
            return []

        normalized_company = normalize_match_text(company)
        normalized_keywords = normalize_keywords(keywords or [])
        query: dict[str, Any] = {"user_id": user_id}
        or_clauses: list[dict[str, Any]] = []
        if normalized_company is not None:
            or_clauses.append({"normalized_company": normalized_company})
        if normalized_keywords:
            or_clauses.append({"normalized_keywords": {"$in": normalized_keywords}})
        if or_clauses:
            query["$or"] = or_clauses

        cursor = (
            self.collection.find(query)
            .sort("updated_at", DESCENDING)
            .limit(limit)
        )
        documents = await cursor.to_list(length=limit)
        return [ApplicationRecord.model_validate(document) for document in documents]

    async def update_current_status(
        self,
        application_id: str,
        status: ApplicationStatus,
    ) -> ApplicationRecord | None:
        document = await self.collection.find_one_and_update(
            {"_id": self._mongo_id(application_id)},
            {
                "$set": {
                    "current_status": status,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return ApplicationRecord.model_validate(document)

    async def update_current_status_for_user(
        self,
        user_id: str,
        application_id: str,
        status: ApplicationStatus,
    ) -> ApplicationRecord | None:
        document = await self.collection.find_one_and_update(
            {
                "_id": self._mongo_id(application_id),
                "user_id": user_id,
            },
            {
                "$set": {
                    "current_status": status,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            return None
        return ApplicationRecord.model_validate(document)

    async def delete_for_user(
        self,
        user_id: str,
        application_id: str,
    ) -> bool:
        result = await self.collection.delete_one(
            {
                "_id": self._mongo_id(application_id),
                "user_id": user_id,
            }
        )
        return result.deleted_count == 1

    @staticmethod
    def _mongo_id(value: str) -> str | ObjectId:
        if ObjectId.is_valid(value):
            return ObjectId(value)
        return value
