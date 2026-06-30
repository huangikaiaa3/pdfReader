# Deployment Notes

## Purpose

This document captures the current production-oriented container runtime path for the PDF reader backend.

Latest FastAPI Cloud redeploy trigger note:

- June 30, 2026: docs-only commit used to trigger a fresh default-branch deployment after environment variables were updated in FastAPI Cloud.

## FastAPI Cloud Build Baseline

FastAPI Cloud uses the latest supported Python version by default unless the app pins a version.

This project now pins Python in [pyproject.toml](/Users/wixx3r/Documents/pdfReader/pdfReader/pyproject.toml) with:

- `requires-python = "==3.10.*"`
- `[tool.fastapi] entrypoint = "app.main:app"`

Why this matters:

- our dependency set currently includes `psycopg[binary]==3.2.9`
- that package has wheels for Python `3.10` through `3.13`, but not `3.14`
- without a Python pin, FastAPI Cloud may try Python `3.14` and fail the build before the app even starts

This keeps the cloud runtime aligned with the local Docker image, which already uses `python:3.10-slim`.

## Development vs Production Compose

Development:

- `docker-compose.yml`
- uses bind mounts
- uses `uvicorn --reload`
- optimized for local iteration

Production-style runtime:

- `docker-compose.prod.yml`
- does not mount the source tree
- stores uploaded documents in a named Docker volume
- runs database migrations on API and worker startup
- uses restart policies for long-running services

## Production Compose Command

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

## Storage Behavior

The production compose file uses a named volume for:

- uploaded PDFs at `/app/storage`

This avoids tying document persistence to the local source checkout.

## Storage Abstraction

The backend now treats document storage as an abstraction instead of assuming local disk everywhere.

Current behavior:

- `STORAGE_BACKEND=local`
- uploaded PDFs are stored under `STORAGE_ROOT`
- `document_versions.storage_path` stores an opaque URI like `local://documents/<uuid>.pdf`

Prepared for later:

- `STORAGE_BACKEND=s3`
- `STORAGE_BUCKET`
- `STORAGE_KEY_PREFIX`

The S3-oriented settings are present so the persistence model and service boundaries are ready, even though actual S3 reads/writes are not implemented yet.

## Secret Handling

The runtime settings now treat `GEMINI_API_KEY` as a secret value.

Current safeguards:

- the Gemini key is required in `production`
- `STORAGE_BUCKET` is required when `STORAGE_BACKEND=s3`
- the application no longer passes the secret around as a plain config string

## Runtime Observability

The current runtime path now includes:

- `/livez` for lightweight process liveness
- `/readyz` for database + Redis readiness
- request logging with request IDs and latency
- Docker health checks for API, worker, PostgreSQL, and Redis
- periodic stale-session cleanup in the worker process

Request logs now include:

- request ID
- method
- path
- status code
- duration in milliseconds

You can control log verbosity with:

- `LOG_LEVEL`

## Session Runtime Controls

The current temporary-session product also relies on a few runtime guardrails:

- `MAX_UPLOAD_SIZE_BYTES`
- `MAX_PDF_PAGES`
- `MAX_SESSION_QUESTION_CHARS`
- `SESSION_INACTIVITY_TIMEOUT_MINUTES`
- `SESSION_CLEANUP_INTERVAL_SECONDS`

These help keep the temporary-session backend bounded and prevent the frontend from waiting indefinitely on invalid or over-large inputs.

## Startup Scripts

- `docker/api/start.sh`
- `docker/worker/start.sh`

Both currently run:

1. `alembic upgrade head`
2. the service entry command

This keeps a fresh deployment from starting against an outdated schema.

## Current Limits

This is a solid deployment baseline, but not the final production story yet.

Still missing or intentionally simple:

- secrets manager integration
- object storage such as S3 or GCS
- separate migration job instead of running migrations in both containers
- TLS / reverse proxy configuration
- autoscaling or multiple worker replicas
