# Gmail Push Ingestion

## Why

The app must run continuously and react when job-related mail arrives instead of polling every few minutes. Gmail Watch plus Pub/Sub gives near real-time ingestion while keeping API usage controlled.

## What

Implement Gmail watch registration, Pub/Sub webhook handling, history synchronization, email deduplication, and durable email storage for each connected user.

## Constraints

### Must
- Use Gmail Watch API with Google Pub/Sub for new-mail notifications.
- Register watches for the authenticated user's monitored Gmail account.
- Store `historyId`, watch expiration, and renewal metadata per user.
- Acknowledge Pub/Sub webhooks quickly and process email synchronization idempotently.
- Deduplicate emails by Gmail message ID per user.
- Store normalized email documents in MongoDB before Gemini extraction.

### Must Not
- Do not classify or match applications in this task.
- Do not rely on interval inbox polling as the primary ingestion mechanism.
- Do not store full raw email bodies indefinitely unless the data retention decision is explicit.

### Out of Scope
- Gemini extraction.
- Dashboard review workflows.
- Historical backfill by user-selected start date.

## Current State

The OAuth task should provide connected users with refreshable Gmail credentials and a persisted monitored email address. There is not yet a Pub/Sub webhook, Gmail watch service, or `emails` collection.

- Relevant files to read: `backend/app/services/google_oauth.py`, `backend/app/repositories/users.py`, `backend/app/core/config.py`
- Relevant files to create or change: Gmail service, Pub/Sub routes, email repository, watch renewal job.

## Tasks

### T1: Add Email Storage Contract
**What:** Define the `emails` collection with user ID, Gmail message ID, thread ID, sender, recipients, subject, received timestamp, labels, snippet, normalized body text, processing state, and dedupe indexes.
**Files:** `backend/app/models/email.py`, `backend/app/repositories/emails.py`, `backend/tests/repositories/test_emails.py`
**Verify:** `cd backend && uv run pytest backend/tests/repositories/test_emails.py`

### T2: Register And Renew Gmail Watches
**What:** Add a Gmail service that registers `users.watch`, stores the returned `historyId` and expiration, and renews watches before expiration for all connected users.
**Files:** `backend/app/services/gmail_watch.py`, `backend/app/repositories/users.py`, `backend/app/core/config.py`, `backend/tests/services/test_gmail_watch.py`
**Verify:** `cd backend && uv run pytest backend/tests/services/test_gmail_watch.py`

### T3: Handle Pub/Sub Notifications
**What:** Add a webhook endpoint that validates Pub/Sub requests, decodes Gmail notifications, loads the user by monitored email, and schedules history synchronization without blocking the acknowledgment.
**Files:** `backend/app/api/pubsub.py`, `backend/app/services/pubsub.py`, `backend/app/main.py`, `backend/tests/api/test_pubsub.py`
**Verify:** `cd backend && uv run pytest backend/tests/api/test_pubsub.py`

### T4: Synchronize Gmail History
**What:** Fetch changed message IDs from Gmail history, retrieve message metadata/body, normalize content, save deduped emails, and update each user's last processed history ID.
**Files:** `backend/app/services/gmail_sync.py`, `backend/app/repositories/emails.py`, `backend/app/repositories/users.py`, `backend/tests/services/test_gmail_sync.py`
**Verify:** `cd backend && uv run pytest backend/tests/services/test_gmail_sync.py`

## Validation

- `cd backend && uv run pytest`
- Manual check: connect Gmail, register a watch, send a test email to that Gmail account, and confirm a new document appears in the `emails` collection within seconds.
- Manual check: resend the same Pub/Sub notification payload and confirm no duplicate email document is created.
- Manual check: expire or remove watch metadata in a test user and confirm the renewal job recreates the watch.

