# Project Foundation

## Why

The project needs a stable full-stack foundation before Gmail, Gemini, and dashboard features can be implemented without rework. A clean repo layout also makes 24-7 deployment and future feature additions easier to reason about.

## What

Scaffold a production-oriented web app with a Next.js frontend, FastAPI backend, MongoDB Atlas configuration, shared environment documentation, and basic health checks.

## Constraints

### Must
- Use a repo layout with `frontend/` for Next.js and `backend/` for FastAPI.
- Use Tailwind and shadcn/ui in the frontend.
- Use MongoDB Atlas through environment-driven connection settings.
- Keep secrets out of git and document required variables in `.env.example`.
- Add backend and frontend health/startup checks before feature work starts.

### Must Not
- Do not wire Gmail, Gemini, or Pub/Sub behavior in this task.
- Do not commit real OAuth credentials, Gemini keys, MongoDB credentials, or Render secrets.
- Do not add dashboard product screens beyond a minimal shell needed to verify the app boots.

### Out of Scope
- Gmail OAuth.
- Gmail push notification handling.
- Gemini extraction and application matching.
- Production deployment.

## Current State

This repository is currently empty except for planning specs and `.gitignore`. There are no existing app entry points, package manifests, Python modules, tests, or design patterns to preserve.

- Relevant files to create: `frontend/`, `backend/`, `.env.example`, `README.md`
- Backend should expose a simple `GET /health` endpoint.
- Frontend should expose a minimal authenticated-app shell placeholder without real auth.

## Tasks

### T1: Scaffold Backend
**What:** Create a FastAPI backend with dependency management, app entry point, health route, settings loader, MongoDB client dependency, and basic test setup.
**Files:** `backend/pyproject.toml`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/db/mongo.py`, `backend/tests/test_health.py`
**Verify:** `cd backend && uv run pytest`

### T2: Scaffold Frontend
**What:** Create a Next.js app with Tailwind, shadcn/ui setup, base layout, health/dashboard placeholder page, and lint/test scripts.
**Files:** `frontend/package.json`, `frontend/app/layout.tsx`, `frontend/app/page.tsx`, `frontend/app/globals.css`, `frontend/components/`
**Verify:** `cd frontend && npm run lint`

### T3: Document Local Setup
**What:** Add a root README and `.env.example` files that describe local startup, required services, and secret handling for MongoDB, Google OAuth, Pub/Sub, Gemini, and Render.
**Files:** `README.md`, `.env.example`, `backend/.env.example`, `frontend/.env.example`
**Verify:** Follow README commands from a clean shell and confirm backend `/health` and frontend home page load locally.

## Validation

- `cd backend && uv run pytest`
- `cd frontend && npm run lint`
- Manual check: start the backend and confirm `GET http://localhost:8000/health` returns a successful JSON response.
- Manual check: start the frontend and confirm `http://localhost:3000` renders the app shell without runtime errors.

