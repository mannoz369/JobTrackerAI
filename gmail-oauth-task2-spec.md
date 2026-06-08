# Gmail OAuth

## Why

The monitored mailbox must be tied to the Gmail account the user explicitly connects. OAuth also gives the backend refreshable access needed for push watch registration and historical backfill.

## What

Implement Google OAuth sign-in and Gmail authorization so a user can log in, connect their Gmail account, and store refreshable credentials securely for later Gmail API calls.

## Constraints

### Must
- Use Google OAuth with the signed-in user email as the monitored mailbox identity.
- Request only the scopes required for identity, Gmail reading, and Gmail watch registration.
- Store OAuth refresh tokens encrypted or otherwise protected server-side.
- Persist user records in MongoDB with Google account identifiers, email, OAuth token metadata, and Gmail watch state placeholders.
- Expose authenticated backend endpoints for the frontend to read connection status.

### Must Not
- Do not process emails in this task.
- Do not create applications or status updates in this task.
- Do not expose access tokens or refresh tokens to the browser.

### Out of Scope
- Pub/Sub webhook handling.
- Gemini extraction.
- Dashboard analytics beyond showing connection state.

## Current State

The foundation task should have created `frontend/`, `backend/`, settings loaders, MongoDB connectivity, and an app shell. No auth provider, session model, or user collection exists yet.

- Relevant files to read: `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/db/mongo.py`, `frontend/app/layout.tsx`, `frontend/app/page.tsx`
- Relevant files to create or change: backend auth routes, user model/repository, frontend login/connect Gmail UI.

## Tasks

### T1: Add User And Token Persistence
**What:** Define the `users` collection contract with Google identity fields, monitored email, encrypted refresh token storage, access token expiry metadata, and Gmail watch placeholders.
**Files:** `backend/app/models/user.py`, `backend/app/repositories/users.py`, `backend/app/core/security.py`, `backend/tests/repositories/test_users.py`
**Verify:** `cd backend && uv run pytest backend/tests/repositories/test_users.py`

### T2: Implement OAuth Flow
**What:** Add backend routes for Google OAuth start/callback, session creation, logout, and connection status. Ensure callback verifies state, stores the monitored Gmail address, and never returns raw provider tokens to the frontend.
**Files:** `backend/app/api/auth.py`, `backend/app/services/google_oauth.py`, `backend/app/main.py`, `backend/tests/api/test_auth.py`
**Verify:** `cd backend && uv run pytest backend/tests/api/test_auth.py`

### T3: Add Frontend Auth UI
**What:** Add sign-in/connect Gmail controls, authenticated shell behavior, and a connection status view that uses backend session/status endpoints.
**Files:** `frontend/app/page.tsx`, `frontend/components/auth/`, `frontend/lib/api.ts`
**Verify:** `cd frontend && npm run lint`

## Validation

- `cd backend && uv run pytest`
- `cd frontend && npm run lint`
- Manual check: click Sign in with Google, complete OAuth, and confirm the dashboard shows the connected Gmail address.
- Manual check: inspect browser network responses and confirm no access token or refresh token is returned to the client.

