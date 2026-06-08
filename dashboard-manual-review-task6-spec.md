# Dashboard And Manual Review

## Why

Users need a usable dashboard to see their application pipeline, inspect timelines, correct uncertain matches, and manually update statuses when automated classification is not confident enough.

## What

Build the Next.js dashboard with overview metrics, company grouping, application timelines, status editing, and a review queue for ambiguous or unmatched emails.

## Constraints

### Must
- Use Next.js, Tailwind, and shadcn/ui from the foundation task.
- Show totals for all primary statuses: Applied, Reviewing, Assessment, Interview, Rejected, and Offers.
- Provide company grouped application views.
- Provide an application timeline based on `status_updates`.
- Provide a manual review section for ambiguous emails with candidate applications and confidence explanations.
- Let the user map an email to an existing application, create a new application, dismiss a non-job email, or edit status.

### Must Not
- Do not expose another user's data.
- Do not hide low-confidence AI decisions from the user.
- Do not create decorative marketing pages instead of the actual app experience.

### Out of Scope
- Gmail OAuth implementation details.
- Backfill controls unless the backfill task is already complete.
- Production deployment.

## Current State

The matching task should expose application data, status history, and review queue states in backend storage. The frontend currently has only the app shell and auth/connection status from earlier tasks.

- Relevant files to read: `frontend/app/page.tsx`, `frontend/components/`, `frontend/lib/api.ts`, backend application/status repositories.
- Relevant files to create or change: dashboard routes/components, backend API endpoints for applications and review actions.

## Tasks

### T1: Add Dashboard API Endpoints
**What:** Add authenticated backend endpoints for overview metrics, application lists, company groups, timelines, review queue items, status edits, and manual email mapping actions.
**Files:** `backend/app/api/applications.py`, `backend/app/api/review.py`, `backend/app/services/application_status.py`, `backend/tests/api/test_applications.py`, `backend/tests/api/test_review.py`
**Verify:** `cd backend && uv run pytest backend/tests/api/test_applications.py backend/tests/api/test_review.py`

### T2: Build Overview And Company Views
**What:** Build the primary dashboard screen with status metrics, company grouped applications, filtering, and clear empty states.
**Files:** `frontend/app/dashboard/page.tsx`, `frontend/components/dashboard/`, `frontend/lib/api.ts`
**Verify:** `cd frontend && npm run lint`

### T3: Build Timeline And Status Editing
**What:** Add application detail views with status timeline, editable current status, source email references, and optimistic UI handling for status changes.
**Files:** `frontend/app/dashboard/applications/[id]/page.tsx`, `frontend/components/applications/`, `frontend/lib/api.ts`
**Verify:** `cd frontend && npm run lint`

### T4: Build Manual Review Queue
**What:** Add a review section where ambiguous emails show extracted details, candidate applications, confidence scores, evidence, and actions to map/create/dismiss.
**Files:** `frontend/app/dashboard/review/page.tsx`, `frontend/components/review/`, `frontend/lib/api.ts`
**Verify:** `cd frontend && npm run lint`

## Validation

- `cd backend && uv run pytest`
- `cd frontend && npm run lint`
- Manual check: log in, open the dashboard, and confirm overview counts match seeded backend data.
- Manual check: open a company group and confirm multiple applications at the same company are visible as separate records.
- Manual check: map an ambiguous email from the review queue to an application and confirm the application timeline updates.
- Manual check: manually change status and confirm refresh preserves the new status and history.

