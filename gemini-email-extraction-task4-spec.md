# Gemini Email Extraction

## Why

Incoming emails need structured job metadata before they can become useful application records. Gemini should extract not only obvious fields like company and role, but also every useful identifier that can help distinguish similar applications.

## What

Process stored emails with Gemini 2.5 Flash, validate JSON-only extraction output, and persist structured classification data for downstream matching.

## Constraints

### Must
- Use Gemini 2.5 Flash through an environment-provided API key.
- Require JSON-only model output and validate it with a strict schema before storage.
- Extract company, role, job ID, location, email type, status signal, dates, sender domain, confidence, evidence, and additional unique keywords or identifiers.
- Preserve enough evidence to explain a classification without storing unnecessary raw sensitive content.
- Mark failed or low-confidence extractions for retry or review.

### Must Not
- Do not let unvalidated LLM output directly mutate application status.
- Do not assume every email is job-related.
- Do not hard-code company-specific parsing rules as the primary extraction mechanism.

### Out of Scope
- Application matching and status transitions.
- Manual review UI.
- Historical backfill.

## Current State

The Gmail push ingestion task should store normalized email documents with processing state. There is no Gemini client, extraction schema, or `status_updates` integration yet.

- Relevant files to read: `backend/app/models/email.py`, `backend/app/repositories/emails.py`, `backend/app/core/config.py`
- Relevant files to create or change: Gemini service, extraction models, processing worker, extraction tests.

## Tasks

### T1: Define Extraction Schema
**What:** Create a strict extraction model with fields for job identity, email classification, status signal, confidence, evidence snippets, ambiguous indicators, and a `uniqueKeywords` list for location, requisition IDs, team names, recruiter names, domains, and other matching hints.
**Files:** `backend/app/models/extraction.py`, `backend/tests/models/test_extraction.py`
**Verify:** `cd backend && uv run pytest backend/tests/models/test_extraction.py`

### T2: Implement Gemini Client And Prompt
**What:** Add a Gemini service that sends normalized email content with a JSON-only prompt, handles timeouts/retries, parses model output, and rejects invalid responses.
**Files:** `backend/app/services/gemini.py`, `backend/app/prompts/job_email_extraction.md`, `backend/app/core/config.py`, `backend/tests/services/test_gemini.py`
**Verify:** `cd backend && uv run pytest backend/tests/services/test_gemini.py`

### T3: Add Email Extraction Worker
**What:** Process pending email records, call Gemini, store extraction results on the email document, and update processing state to extracted, non_job, extraction_failed, or needs_review.
**Files:** `backend/app/services/email_extraction_worker.py`, `backend/app/repositories/emails.py`, `backend/tests/services/test_email_extraction_worker.py`
**Verify:** `cd backend && uv run pytest backend/tests/services/test_email_extraction_worker.py`

## Validation

- `cd backend && uv run pytest`
- Manual check: insert a sample interview email and confirm Gemini output includes company, role, status signal, confidence, evidence, and unique keywords.
- Manual check: insert a non-job newsletter email and confirm it is classified as `Other` or `non_job` without creating an application.
- Manual check: force invalid model JSON and confirm the email is marked for retry or review rather than crashing the worker.

