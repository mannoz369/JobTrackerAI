# Application Matching And Status

## Why

The project becomes valuable when it can connect email updates to the correct job application and maintain a reliable status timeline. This is also the main place where ambiguity from multiple roles at the same company must be handled safely.

## What

Create application, company, and status update persistence; implement confidence-based matching; auto-create applications from application confirmation emails; and route ambiguous matches to manual review.

## Constraints

### Must
- Store applications with mutable status and immutable status history.
- Support statuses: `Applied`, `Reviewing`, `Assessment`, `Interview`, `Offer`, `Rejected`, and `Other`.
- Match by job ID first, then company plus role, then LLM-assisted reasoning with confidence.
- Use extracted unique keywords for matching when job ID and role are insufficient.
- Auto-create applications only when extraction strongly indicates a new application confirmation.
- Send ambiguous or low-confidence cases to a review queue instead of silently changing an application.

### Must Not
- Do not overwrite application status without writing a `status_updates` history entry.
- Do not auto-merge applications from the same company without enough evidence.
- Do not drop unmatched emails.

### Out of Scope
- Frontend manual review UI.
- Backfill orchestration.
- Analytics charts beyond stored data availability.

## Current State

The Gemini extraction task should mark emails with structured job metadata and confidence. There are not yet `applications`, `companies`, or `status_updates` collections, nor any matching service.

- Relevant files to read: `backend/app/models/extraction.py`, `backend/app/models/email.py`, `backend/app/repositories/emails.py`
- Relevant files to create or change: application models/repositories, matching service, status transition service.

## Tasks

### T1: Define Application Data Model
**What:** Create `applications`, `companies`, and `status_updates` models and repositories with indexes for user ID, company, role, job ID, normalized keywords, and current status.
**Files:** `backend/app/models/application.py`, `backend/app/models/company.py`, `backend/app/models/status_update.py`, `backend/app/repositories/applications.py`, `backend/app/repositories/companies.py`, `backend/app/repositories/status_updates.py`
**Verify:** `cd backend && uv run pytest backend/tests/repositories/test_applications.py`

### T2: Implement Matching Service
**What:** Match extracted emails to applications using Level 1 job ID, Level 2 company and role, and Level 3 Gemini-assisted reasoning over candidate applications and unique keywords. Return confidence and explanation for every match decision.
**Files:** `backend/app/services/application_matching.py`, `backend/app/services/gemini.py`, `backend/tests/services/test_application_matching.py`
**Verify:** `cd backend && uv run pytest backend/tests/services/test_application_matching.py`

### T3: Implement Status Updates And Auto-Create
**What:** Apply matched status changes, create status history entries, auto-create applications from high-confidence `Applied` emails, and mark unmatched/ambiguous emails for manual review.
**Files:** `backend/app/services/application_status.py`, `backend/app/repositories/applications.py`, `backend/app/repositories/status_updates.py`, `backend/app/repositories/emails.py`, `backend/tests/services/test_application_status.py`
**Verify:** `cd backend && uv run pytest backend/tests/services/test_application_status.py`

## Validation

- `cd backend && uv run pytest`
- Manual check: process an email with a matching job ID and confirm it updates the correct application at 100 percent confidence.
- Manual check: process an Oracle email where multiple Oracle applications exist and confirm low-confidence output enters the review queue.
- Manual check: process a clear "thank you for applying" email with no existing application and confirm a new application is created with status `Applied`.
- Manual check: change an application's status and confirm a new `status_updates` record is written.

