# Production Deployment

## Why

The workflow must run 24-7 so new job emails are captured whenever they arrive. Deployment needs stable hosting, secrets, webhook reachability, watch renewal, and operational checks.

## What

Deploy the Next.js frontend and FastAPI backend to Render, connect MongoDB Atlas, configure Google Pub/Sub webhook delivery, and add production readiness checks for continuous Gmail monitoring.

## Constraints

### Must
- Deploy backend and frontend as separate Render services or an equivalent Render-supported layout.
- Store all secrets in Render environment variables.
- Use MongoDB Atlas for production data.
- Configure Google OAuth redirect URLs for the deployed frontend/backend.
- Configure Pub/Sub push subscription to call the deployed FastAPI webhook over HTTPS.
- Ensure Gmail watches are registered and renewed on a schedule before expiration.
- Add health checks and logs that make ingestion failures diagnosable.

### Must Not
- Do not commit production secrets.
- Do not depend on a local machine process for 24-7 ingestion.
- Do not use n8n as the core production workflow.

### Out of Scope
- Building new product features.
- Paid scaling decisions beyond initial free or low-cost deployment.
- Enterprise monitoring beyond basic Render logs, health checks, and retry visibility.

## Current State

The previous tasks should have created a full local application with OAuth, Gmail push ingestion, Gemini extraction, matching, dashboard, manual review, and backfill. No Render deployment configuration or production environment checklist exists yet.

- Relevant files to read: `README.md`, `backend/app/core/config.py`, `frontend/package.json`, `backend/pyproject.toml`
- Relevant files to create or change: Render configuration, deployment docs, production health checks.

## Tasks

### T1: Add Deployment Configuration
**What:** Add Render service configuration for backend and frontend, production build commands, health check paths, and required environment variable documentation.
**Files:** `render.yaml`, `README.md`, `.env.example`, `backend/.env.example`, `frontend/.env.example`
**Verify:** Review Render service definitions and confirm every referenced environment variable is documented.

### T2: Configure Production Integrations
**What:** Document and implement production setup for MongoDB Atlas, Google OAuth redirect URIs, Gmail watch topic, Pub/Sub push subscription, and Gemini API key.
**Files:** `README.md`, `backend/app/core/config.py`, `backend/app/services/gmail_watch.py`
**Verify:** Manual check: in Google Cloud Console, confirm OAuth redirect URIs and Pub/Sub push endpoint match the deployed Render URLs.

### T3: Add Runtime Health And Renewal Checks
**What:** Add health/readiness behavior that verifies backend startup, Mongo connectivity, configured secrets, and watch renewal job status without exposing secret values.
**Files:** `backend/app/api/health.py`, `backend/app/services/gmail_watch.py`, `backend/tests/api/test_health.py`
**Verify:** `cd backend && uv run pytest backend/tests/api/test_health.py`

### T4: Smoke Test Production Flow
**What:** Run an end-to-end smoke test from Gmail OAuth through live email ingestion, Gemini extraction, application matching, and dashboard display.
**Files:** `README.md`
**Verify:** Manual check: send a new job-related email to the connected Gmail account and confirm it appears on the production dashboard with extracted details and correct review/application state.

## Validation

- `cd backend && uv run pytest`
- `cd frontend && npm run lint`
- Manual check: deployed backend `/health` returns healthy.
- Manual check: deployed frontend loads over HTTPS and can start Google OAuth.
- Manual check: Pub/Sub delivers a test push message to the deployed webhook.
- Manual check: a real Gmail test message is processed without any local machine running.

