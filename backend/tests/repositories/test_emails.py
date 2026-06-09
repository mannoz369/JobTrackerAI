import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.models.email import EmailCreate
from app.models.extraction import JobEmailExtraction
from app.repositories.emails import EmailsRepository


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


class FakeUpdateResult:
    def __init__(self, modified_count: int) -> None:
        self.modified_count = modified_count


class FakeEmailsCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.indexes: list[tuple[Any, dict[str, Any]]] = []

    async def create_index(self, keys: Any, **kwargs: Any) -> None:
        self.indexes.append((keys, kwargs))

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
            document = {"_id": f"email_{len(self.documents) + 1}"}
            document.update(deepcopy(update.get("$setOnInsert", {})))
            self.documents.append(document)

        document.update(deepcopy(update.get("$set", {})))
        for key, value in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + value
        return deepcopy(document)

    async def update_many(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
    ) -> FakeUpdateResult:
        modified_count = 0
        for document in self.documents:
            if not self._matches(document, query):
                continue
            document.update(deepcopy(update.get("$set", {})))
            modified_count += 1
        return FakeUpdateResult(modified_count)

    def _find(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if self._matches(document, query):
                return document
        return None

    @staticmethod
    def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
        return all(document.get(key) == value for key, value in query.items())


class FakeDatabase:
    def __init__(self) -> None:
        self.emails = FakeEmailsCollection()

    def __getitem__(self, name: str) -> FakeEmailsCollection:
        assert name == "emails"
        return self.emails


def test_email_repository_persists_contract_and_indexes() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = EmailsRepository(database)
        await repository.ensure_indexes()

        email = await repository.upsert_email(
            EmailCreate(
                user_id="user_123",
                gmail_message_id="gmail-message-1",
                thread_id="thread-1",
                sender="recruiter@example.com",
                recipients=["person@example.com"],
                subject="Application update",
                received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                labels=["INBOX", "IMPORTANT"],
                snippet="Thanks for applying",
                body_text="Thanks for applying.\nWe will follow up soon.",
                source_history_id="history-10",
            )
        )

        assert email.id == "email_1"
        assert email.user_id == "user_123"
        assert email.gmail_message_id == "gmail-message-1"
        assert email.processing_state == "pending_extraction"
        assert email.body_text == "Thanks for applying.\nWe will follow up soon."
        assert any(
            kwargs.get("name") == "emails_user_gmail_message_unique"
            and kwargs.get("unique") is True
            for _, kwargs in database.emails.indexes
        )

    asyncio.run(run())


def test_upsert_email_deduplicates_by_user_and_gmail_message_id() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = EmailsRepository(database)

        await repository.upsert_email(
            EmailCreate(
                user_id="user_123",
                gmail_message_id="gmail-message-1",
                subject="Original",
            )
        )
        duplicate = await repository.upsert_email(
            EmailCreate(
                user_id="user_123",
                gmail_message_id="gmail-message-1",
                subject="Updated",
                processing_state="failed",
            )
        )

        assert len(database.emails.documents) == 1
        assert duplicate.subject == "Updated"
        assert duplicate.processing_state == "pending_extraction"

    asyncio.run(run())


def test_list_pending_extraction_returns_oldest_pending_emails() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = EmailsRepository(database)
        old = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new = datetime(2026, 1, 2, tzinfo=timezone.utc)
        database.emails.documents = [
            {
                "_id": "email_1",
                "user_id": "user_123",
                "gmail_message_id": "gmail-message-1",
                "processing_state": "pending_extraction",
                "created_at": new,
                "updated_at": new,
            },
            {
                "_id": "email_2",
                "user_id": "user_123",
                "gmail_message_id": "gmail-message-2",
                "processing_state": "extracted",
                "created_at": old,
                "updated_at": old,
            },
            {
                "_id": "email_3",
                "user_id": "user_123",
                "gmail_message_id": "gmail-message-3",
                "processing_state": "pending_extraction",
                "created_at": old,
                "updated_at": old,
            },
        ]

        emails = await repository.list_pending_extraction(limit=1)

        assert [email.id for email in emails] == ["email_3"]

    asyncio.run(run())


def test_store_extraction_result_updates_processing_metadata() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = EmailsRepository(database)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        database.emails.documents = [
            {
                "_id": "email_1",
                "user_id": "user_123",
                "gmail_message_id": "gmail-message-1",
                "processing_state": "pending_extraction",
                "created_at": now,
                "updated_at": now,
            }
        ]
        extraction = JobEmailExtraction.model_validate(
            {
                "isJobRelated": True,
                "company": "Acme",
                "role": "Backend Engineer",
                "jobId": "ACME-42",
                "location": "Remote",
                "emailType": "ApplicationConfirmation",
                "statusSignal": "Applied",
                "dates": [],
                "senderDomain": "jobs.acme.example",
                "confidence": 0.92,
                "evidence": [
                    {
                        "field": "statusSignal",
                        "snippet": "Thank you for applying.",
                    }
                ],
                "ambiguousIndicators": [],
                "uniqueKeywords": ["ACME-42"],
                "reviewReason": None,
            }
        )

        updated = await repository.store_extraction_result(
            "email_1",
            extraction,
            "extracted",
            model_name="gemini-2.5-flash",
            extracted_at=now,
        )

        assert updated is not None
        assert updated.processing_state == "extracted"
        assert updated.extraction is not None
        assert updated.extraction.job_id == "ACME-42"
        assert updated.extraction_model == "gemini-2.5-flash"
        assert updated.extraction_attempts == 1
        assert database.emails.documents[0]["extraction"]["uniqueKeywords"] == [
            "ACME-42"
        ]

    asyncio.run(run())


def test_mark_extraction_failed_records_error_and_attempt() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = EmailsRepository(database)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        database.emails.documents = [
            {
                "_id": "email_1",
                "user_id": "user_123",
                "gmail_message_id": "gmail-message-1",
                "processing_state": "pending_extraction",
                "created_at": now,
                "updated_at": now,
            }
        ]

        updated = await repository.mark_extraction_failed(
            "email_1",
            "invalid model JSON",
            model_name="gemini-2.5-flash",
        )

        assert updated is not None
        assert updated.processing_state == "extraction_failed"
        assert updated.extraction_error == "invalid model JSON"
        assert updated.extraction_attempts == 1

    asyncio.run(run())


def test_clear_application_links_moves_linked_emails_back_to_review() -> None:
    async def run() -> None:
        database = FakeDatabase()
        repository = EmailsRepository(database)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        database.emails.documents = [
            {
                "_id": "email_1",
                "user_id": "user_123",
                "gmail_message_id": "gmail-message-1",
                "processing_state": "matched",
                "application_id": "app_1",
                "status_update_id": "status_update_1",
                "matching_result": {"decision": "matched"},
                "matched_at": now,
                "created_at": now,
                "updated_at": now,
            },
            {
                "_id": "email_2",
                "user_id": "user_123",
                "gmail_message_id": "gmail-message-2",
                "processing_state": "matched",
                "application_id": "app_2",
                "created_at": now,
                "updated_at": now,
            },
        ]

        modified = await repository.clear_application_links_for_user(
            "user_123",
            "app_1",
        )

        assert modified == 1
        updated = database.emails.documents[0]
        assert updated["processing_state"] == "needs_review"
        assert updated["application_id"] is None
        assert updated["status_update_id"] is None
        assert updated["matching_result"] is None
        assert updated["matched_at"] is None
        assert (
            updated["application_review_reason"]
            == "Application was deleted. Review or dismiss this email."
        )
        assert database.emails.documents[1]["application_id"] == "app_2"

    asyncio.run(run())
