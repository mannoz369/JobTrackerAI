import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.models.application import ApplicationCreate
from app.models.status_update import StatusUpdateCreate
from app.repositories.applications import ApplicationsRepository
from app.repositories.companies import CompaniesRepository
from app.repositories.status_updates import StatusUpdatesRepository


class FakeInsertResult:
    def __init__(self, inserted_id: str) -> None:
        self.inserted_id = inserted_id


class FakeDeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def sort(self, key: str, direction: Any) -> "FakeCursor":
        reverse = direction == -1
        self.documents = sorted(
            self.documents,
            key=lambda document: document.get(key) or datetime.min.replace(
                tzinfo=timezone.utc
            ),
            reverse=reverse,
        )
        return self

    def limit(self, limit: int) -> "FakeCursor":
        self.documents = self.documents[:limit]
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is None:
            return deepcopy(self.documents)
        return deepcopy(self.documents[:length])


class FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.documents: list[dict[str, Any]] = []
        self.indexes: list[tuple[Any, dict[str, Any]]] = []

    async def create_index(self, keys: Any, **kwargs: Any) -> None:
        self.indexes.append((keys, kwargs))

    async def insert_one(self, document: dict[str, Any]) -> FakeInsertResult:
        inserted = deepcopy(document)
        inserted["_id"] = f"{self.name}_{len(self.documents) + 1}"
        self.documents.append(inserted)
        return FakeInsertResult(inserted["_id"])

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        document = self._find(query)
        return deepcopy(document) if document is not None else None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [deepcopy(document) for document in self.documents if self._matches(document, query)]
        )

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        document = self._find(query)
        if document is None:
            document = {"_id": f"{self.name}_{len(self.documents) + 1}"}
            document.update(deepcopy(update.get("$setOnInsert", {})))
            self.documents.append(document)

        document.update(deepcopy(update.get("$set", {})))
        for key, value in update.get("$addToSet", {}).items():
            values = value.get("$each", []) if isinstance(value, dict) else [value]
            existing = document.setdefault(key, [])
            for item in values:
                if item not in existing:
                    existing.append(item)
        return deepcopy(document)

    async def delete_one(self, query: dict[str, Any]) -> FakeDeleteResult:
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                del self.documents[index]
                return FakeDeleteResult(1)
        return FakeDeleteResult(0)

    async def delete_many(self, query: dict[str, Any]) -> FakeDeleteResult:
        before = len(self.documents)
        self.documents = [
            document for document in self.documents if not self._matches(document, query)
        ]
        return FakeDeleteResult(before - len(self.documents))

    def _find(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if self._matches(document, query):
                return document
        return None

    def _matches(self, document: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, value in query.items():
            if key == "$or":
                if not any(self._matches(document, clause) for clause in value):
                    return False
                continue
            document_value = document.get(key)
            if isinstance(value, dict) and "$in" in value:
                if isinstance(document_value, list):
                    if not set(document_value) & set(value["$in"]):
                        return False
                elif document_value not in value["$in"]:
                    return False
                continue
            if document_value != value:
                return False
        return True


class FakeDatabase:
    def __init__(self) -> None:
        self.collections = {
            "applications": FakeCollection("application"),
            "companies": FakeCollection("company"),
            "status_updates": FakeCollection("status_update"),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections[name]


def test_application_repositories_persist_contracts_and_indexes() -> None:
    async def run() -> None:
        database = FakeDatabase()
        companies = CompaniesRepository(database)
        applications = ApplicationsRepository(database)
        status_updates = StatusUpdatesRepository(database)

        await companies.ensure_indexes()
        await applications.ensure_indexes()
        await status_updates.ensure_indexes()

        company = await companies.upsert_company(
            "user_123",
            "Acme",
            domains=["jobs.acme.example", "jobs.acme.example"],
        )
        application = await applications.create_application(
            ApplicationCreate(
                user_id="user_123",
                company_id=company.id,
                company_name=company.name,
                role="Backend Engineer",
                job_id="ACME-42",
                location="Remote",
                normalized_keywords=["Remote", "Python", "ACME-42"],
                source_email_id="email_1",
                confidence=0.95,
            )
        )
        status_update = await status_updates.create_status_update(
            StatusUpdateCreate(
                user_id="user_123",
                application_id=application.id or "",
                email_id="email_1",
                previous_status=None,
                new_status="Applied",
                confidence=0.95,
                explanation="Initial application confirmation.",
            )
        )

        assert company.id == "company_1"
        assert company.normalized_name == "acme"
        assert company.domains == ["jobs.acme.example"]
        assert application.id == "application_1"
        assert application.normalized_company == "acme"
        assert application.normalized_role == "backend engineer"
        assert application.normalized_job_id == "acme-42"
        assert application.normalized_keywords == ["remote", "python", "acme-42"]
        assert status_update.id == "status_update_1"
        assert any(
            kwargs.get("name") == "applications_user_job_id_unique"
            and kwargs.get("unique") is True
            for _, kwargs in database.collections["applications"].indexes
        )

        by_job_id = await applications.list_by_job_id("user_123", "ACME-42")
        assert [record.id for record in by_job_id] == ["application_1"]

        updated = await applications.update_current_status(
            application.id or "",
            "Interview",
        )
        assert updated is not None
        assert updated.current_status == "Interview"

        history = await status_updates.list_for_application(
            "user_123",
            application.id or "",
        )
        assert [update.id for update in history] == ["status_update_1"]

        deleted_history = await status_updates.delete_for_application(
            "user_123",
            application.id or "",
        )
        assert deleted_history == 1

        deleted_application = await applications.delete_for_user(
            "user_123",
            application.id or "",
        )
        assert deleted_application is True
        assert await applications.get_for_user("user_123", application.id or "") is None

    asyncio.run(run())
