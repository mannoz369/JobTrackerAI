import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any

from app.models.backfill import BackfillJobCreate
from app.repositories.backfill_jobs import BackfillJobsRepository


class InsertResult:
    def __init__(self, inserted_id: str) -> None:
        self.inserted_id = inserted_id


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def sort(self, key: str, direction: Any) -> "FakeCursor":
        reverse = direction == -1
        self.documents = sorted(
            self.documents,
            key=lambda document: document.get(key)
            or datetime.min.replace(tzinfo=timezone.utc),
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


class FakeBackfillJobsCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.indexes: list[tuple[Any, dict[str, Any]]] = []

    async def create_index(self, keys: Any, **kwargs: Any) -> None:
        self.indexes.append((keys, kwargs))

    async def insert_one(self, document: dict[str, Any]) -> InsertResult:
        inserted = {"_id": f"job_{len(self.documents) + 1}", **deepcopy(document)}
        self.documents.append(inserted)
        return InsertResult(inserted["_id"])

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        document = self._find(query)
        return deepcopy(document) if document is not None else None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [
                deepcopy(document)
                for document in self.documents
                if self._matches(document, query)
            ]
        )

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        document = self._find(query)
        if document is None:
            return None
        document.update(deepcopy(update.get("$set", {})))
        for key, value in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + value
        for key, value in update.get("$push", {}).items():
            document.setdefault(key, []).append(value)
        return deepcopy(document)

    def _find(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if self._matches(document, query):
                return document
        return None

    @staticmethod
    def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, value in query.items():
            current = document.get(key)
            if isinstance(value, dict) and "$in" in value:
                if current not in value["$in"]:
                    return False
            elif current != value:
                return False
        return True


class FakeDatabase:
    def __init__(self) -> None:
        self.backfill_jobs = FakeBackfillJobsCollection()

    def __getitem__(self, name: str) -> FakeBackfillJobsCollection:
        assert name == "backfill_jobs"
        return self.backfill_jobs


def test_backfill_job_repository_persists_contract_and_indexes() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = BackfillJobsRepository(database)
        await repository.ensure_indexes()

        job = await repository.create_job(
            BackfillJobCreate(
                user_id="user_123",
                start_date=date(2026, 1, 2),
                gmail_query="after:2026/01/01",
            )
        )

        assert job.id == "job_1"
        assert job.status == "pending"
        assert job.page_token is None
        assert job.fetched_count == 0
        assert any(
            kwargs.get("name") == "backfill_jobs_user_active_unique"
            and kwargs.get("unique") is True
            for _, kwargs in database.backfill_jobs.indexes
        )

    asyncio.run(run())


def test_backfill_job_repository_tracks_cursor_progress_and_retry() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = BackfillJobsRepository(database)
        job = await repository.create_job(
            BackfillJobCreate(
                user_id="user_123",
                start_date=date(2026, 1, 2),
                gmail_query="after:2026/01/01",
            )
        )
        assert job.id is not None

        running = await repository.mark_running(job.id)
        assert running is not None
        assert running.status == "running"

        progressed = await repository.update_progress(
            job.id,
            page_token="next-page",
            increments={"fetched_count": 2, "saved_count": 1, "duplicate_count": 1},
        )
        assert progressed is not None
        assert progressed.page_token == "next-page"
        assert progressed.fetched_count == 2
        assert progressed.saved_count == 1
        assert progressed.duplicate_count == 1

        failed = await repository.mark_failed(job.id, "Gmail timed out")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.last_error == "Gmail timed out"
        assert failed.errors == ["Gmail timed out"]

        retried = await repository.reset_for_retry(job.id)
        assert retried is not None
        assert retried.status == "pending"
        assert retried.page_token == "next-page"
        assert retried.last_error is None

    asyncio.run(run())
