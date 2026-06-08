# Historical Gmail Backfill

## Why

Users may have started applying before they connected the app, so the system needs a controlled way to import older job emails. The default should be safe and start from today, but users should be able to choose an earlier date.

## What

Add a user-configurable backfill workflow that reads Gmail from a selected start date, stores matching email candidates idempotently, runs extraction and matching, and reports progress in the dashboard.

## Constraints

### Must
- Default each user backfill start date to the current connection date.
- Let the user choose an earlier date before starting backfill.
- Use Gmail search/date filters and pagination instead of fetching the entire mailbox blindly.
- Deduplicate against emails already stored by push ingestion.
- Track backfill job progress, errors, last cursor/page token, and completion state.
- Reuse the same extraction, matching, auto-create, and review queue flow as live ingestion.

### Must Not
- Do not run historical backfill automatically across a large mailbox without user confirmation.
- Do not block live push ingestion while backfill is running.
- Do not create duplicate applications or status updates from repeated backfill runs.

### Out of Scope
- New LLM extraction behavior.
- New dashboard analytics beyond backfill progress controls.
- Production scheduler setup unless needed to resume backfill jobs.

## Current State

Live Gmail ingestion should already store deduped email records, and Gemini/matching services should process stored emails. The dashboard should have authenticated screens but no backfill controls or backfill job state.

- Relevant files to read: `backend/app/services/gmail_sync.py`, `backend/app/services/email_extraction_worker.py`, `backend/app/services/application_matching.py`, `frontend/app/dashboard/`
- Relevant files to create or change: backfill model/repository/service, API endpoints, dashboard backfill controls.

## Tasks

### T1: Define Backfill Job Model
**What:** Create a `backfill_jobs` collection with user ID, start date, status, progress counts, Gmail query, page cursor, error fields, and timestamps.
**Files:** `backend/app/models/backfill.py`, `backend/app/repositories/backfill_jobs.py`, `backend/tests/repositories/test_backfill_jobs.py`
**Verify:** `cd backend && uv run pytest backend/tests/repositories/test_backfill_jobs.py`

### T2: Implement Backfill Service
**What:** Fetch Gmail messages from the chosen date forward, save emails through the existing dedupe path, process them through extraction and matching, and support retry/resume after failures.
**Files:** `backend/app/services/gmail_backfill.py`, `backend/app/services/gmail_sync.py`, `backend/app/services/email_extraction_worker.py`, `backend/tests/services/test_gmail_backfill.py`
**Verify:** `cd backend && uv run pytest backend/tests/services/test_gmail_backfill.py`

### T3: Add Backfill API And UI
**What:** Add endpoints and dashboard controls for choosing start date, starting backfill, viewing progress, retrying failures, and preventing overlapping jobs for one user.
**Files:** `backend/app/api/backfill.py`, `frontend/app/dashboard/settings/page.tsx`, `frontend/components/backfill/`, `frontend/lib/api.ts`
**Verify:** `cd backend && uv run pytest backend/tests/api/test_backfill.py && cd ../frontend && npm run lint`

## Validation

- `cd backend && uv run pytest`
- `cd frontend && npm run lint`
- Manual check: connect Gmail and confirm the default backfill start date is today's date for the user.
- Manual check: set a start date one month earlier, start backfill, and confirm progress counts increase without duplicate email records.
- Manual check: interrupt a backfill job and confirm retry resumes from tracked state instead of restarting blindly.
- Manual check: run backfill over emails that live ingestion already stored and confirm applications/status updates are not duplicated.

