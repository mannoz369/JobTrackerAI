# JobTracker

JobTracker is a full-stack application for tracking job application activity. The current implementation includes the project foundation, Google OAuth connection flow, Gmail push ingestion, historical Gmail backfill, Gemini-based email extraction, and application matching/status persistence for a monitored Gmail mailbox.

## Repo Layout

- `backend/` - FastAPI service with settings, MongoDB dependency wiring, `GET /health`, Google OAuth routes, Gmail Pub/Sub ingestion, Gemini extraction and application matching services, HTTP-only sessions, and encrypted refresh-token persistence.
- `frontend/` - Next.js App Router UI with Tailwind, shadcn/ui configuration, and a Gmail connection dashboard.
- `.env.example` - Shared reference for local and deployment environment variables.

## Requirements

- Python 3.12 or newer.
- `uv` for backend dependency management.
- Node.js 20 or newer.
- npm 10 or newer.
- MongoDB Atlas connection details for database-backed features.

The health check does not require a live MongoDB connection. OAuth connection features require `MONGODB_URI`, `MONGODB_DATABASE`, Google OAuth credentials, and backend session/encryption secrets. Email extraction requires `GEMINI_API_KEY`.

## Environment Setup

Real secrets must stay in local `.env` files or deployment secret stores. Do not commit OAuth credentials, Gemini keys, MongoDB credentials, Pub/Sub identifiers with secrets, or Render secrets.

Create local env files from the templates:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Update the copied files with local values. Keep placeholder values for integrations that are not being implemented yet.

Generate strong local backend secrets before testing OAuth:

```bash
cd backend
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use the first value for `SESSION_SECRET_KEY` and the second value for `TOKEN_ENCRYPTION_KEY`.

## Backend

Install dependencies and run tests:

```bash
cd backend
uv run pytest
```

Start the API:

```bash
cd backend
uv run uvicorn app.main:app --reload
```

Health check:

[http://localhost:8000/health](http://localhost:8000/health)

Expected response:

```json
{
  "status": "ok",
  "service": "JobTracker API",
  "environment": "local"
}
```

OAuth endpoints:

- `GET /auth/google/start` redirects to Google and sets an HTTP-only OAuth state cookie.
- `GET /auth/google/callback` verifies state, stores encrypted refresh-token metadata in MongoDB, creates an HTTP-only app session, and redirects back to the frontend.
- `GET /auth/status` returns connection metadata only.
- `POST /auth/logout` clears the app session.

Gmail and extraction services:

- `POST /pubsub/gmail` acknowledges Gmail Pub/Sub notifications and syncs new messages into `emails`.
- `GET /backfill/status`, `POST /backfill/jobs`, and `POST /backfill/jobs/{job_id}/retry` expose a user-confirmed historical Gmail backfill workflow with cursor/progress tracking.
- `EmailExtractionWorker` processes pending emails with Gemini 2.5 Flash and stores validated extraction metadata for later application matching.
- `ApplicationMatchingService` matches extracted job emails to applications by job ID, company plus role, and LLM/keyword candidate reasoning.
- `ApplicationStatusService` writes immutable `status_updates`, mutates application current status, auto-creates high-confidence application confirmations, and routes ambiguous emails to review.

## Frontend

Install dependencies and run lint:

```bash
cd frontend
npm install
npm run lint
```

Start the app:

```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Deferred Integrations

The following variables are documented for later tasks but are not wired yet:

- Render: `RENDER_SERVICE_NAME`, `RENDER_DEPLOY_HOOK_URL`
