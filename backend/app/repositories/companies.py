from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, ReturnDocument

from app.models.application import normalize_match_text
from app.models.company import CompanyCreate, CompanyRecord


class CompaniesRepository:
    def __init__(self, database: Any) -> None:
        self.collection = database["companies"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("user_id", ASCENDING), ("normalized_name", ASCENDING)],
            unique=True,
            name="companies_user_name_unique",
        )
        await self.collection.create_index(
            [("user_id", ASCENDING), ("domains", ASCENDING)],
            name="companies_user_domains_lookup",
        )

    async def upsert_company(
        self,
        user_id: str,
        name: str,
        *,
        domains: list[str] | None = None,
    ) -> CompanyRecord:
        now = datetime.now(timezone.utc)
        company = CompanyCreate(user_id=user_id, name=name, domains=domains or [])
        set_on_insert: dict[str, Any] = {
            "user_id": company.user_id,
            "created_at": now,
        }
        update: dict[str, Any] = {
            "$set": {
                "name": company.name,
                "normalized_name": company.normalized_name,
                "updated_at": now,
            },
            "$setOnInsert": set_on_insert,
        }
        if company.domains:
            update["$addToSet"] = {"domains": {"$each": company.domains}}
        else:
            set_on_insert["domains"] = []

        document = await self.collection.find_one_and_update(
            {
                "user_id": company.user_id,
                "normalized_name": company.normalized_name,
            },
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return CompanyRecord.model_validate(document)

    async def get_by_id(self, company_id: str) -> CompanyRecord | None:
        document = await self.collection.find_one({"_id": self._mongo_id(company_id)})
        if document is None:
            return None
        return CompanyRecord.model_validate(document)

    async def get_by_name(self, user_id: str, name: str) -> CompanyRecord | None:
        normalized_name = normalize_match_text(name)
        if normalized_name is None:
            return None
        document = await self.collection.find_one(
            {
                "user_id": user_id,
                "normalized_name": normalized_name,
            }
        )
        if document is None:
            return None
        return CompanyRecord.model_validate(document)

    @staticmethod
    def _mongo_id(value: str) -> str | ObjectId:
        if ObjectId.is_valid(value):
            return ObjectId(value)
        return value
