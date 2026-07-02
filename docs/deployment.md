# Deployment Notes

## Preferred Runtime

The current preferred deployment shape is:

- frontend on the same EC2 instance
- backend API on the same EC2 instance
- ingestion worker on the same EC2 instance
- PostgreSQL on the same EC2 instance
- Redis on the same EC2 instance

This keeps the whole backend stack in one Docker Compose runtime and avoids the shared-storage mismatch we hit with:

- backend on FastAPI Cloud
- worker on EC2
- `STORAGE_BACKEND=local`

That split deployment failed because uploaded PDFs were written to the backend container filesystem, while the worker was trying to read them from a different machine.

## Why Single-Origin EC2 Is Simpler For This App

This app currently relies on local filesystem storage for uploaded PDFs:

- `STORAGE_BACKEND=local`
- `STORAGE_ROOT=/app/storage`

When the API and worker share one EC2 host and one Docker volume:

- the API writes uploaded PDFs once
- the worker reads the same files
- no object storage is required yet

For the current temporary PDF chat product, this is the simplest reliable runtime shape.

It also avoids the browser mixed-content issue we hit when:

- frontend was served over `https`
- backend was served over plain `http`
- browser blocked the frontend's API calls

## Compose File

Use:

- [docker-compose.prod.yml](/Users/wixx3r/Documents/pdfReader/pdfReader/docker-compose.prod.yml)

This stack runs:

- `frontend`
- `api`
- `worker`
- `postgres`
- `redis`

It also uses Docker-managed volumes for:

- uploaded PDFs
- PostgreSQL data
- Redis data

## Environment File

Start from:

- [.env.ec2.example](/Users/wixx3r/Documents/pdfReader/pdfReader/.env.ec2.example)

Create the real runtime file on the EC2 host as `.env`.

Important values:

- `ENVIRONMENT=production`
- `DATABASE_URL=postgresql+psycopg://postgres:<password>@postgres:5432/pdfreader`
- `REDIS_URL=redis://redis:6379/0`
- `STORAGE_BACKEND=local`
- `STORAGE_ROOT=/app/storage`
- `GEMINI_API_KEY=<your key>`
- `CORS_ALLOWED_ORIGINS=http://<ec2-public-ip>`
- `POSTGRES_PASSWORD=<same password used by the postgres container>`

## EC2 Startup Command

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

## Expected Public Entry Point

With the current compose file, the public app is published on:

- `http://<ec2-public-ip>`

The frontend is served by nginx, and nginx proxies API traffic to the internal FastAPI service.

Examples:

- `http://51.20.107.183/`
- `http://51.20.107.183/health`

## Storage Behavior

The `api` and `worker` services both mount the same Docker volume at:

- `/app/storage`

That is what makes local document storage safe again in this deployment shape.

Persisted `document_versions.storage_path` values still look like:

- `local://documents/<document-version-id>.pdf`

## Health And Startup

Current startup behavior:

- `docker/api/start.sh`
- `docker/worker/start.sh`

Both run:

1. `alembic upgrade head`
2. the service process

Health checks are present for:

- API
- worker
- PostgreSQL
- Redis

## Frontend Routing

The frontend is built into a dedicated nginx container.

Current routing behavior:

- `/` serves the React app
- `/auth/*` proxies to the FastAPI API container
- `/sessions/*` proxies to the FastAPI API container
- `/health`, `/livez`, `/readyz` proxy to the FastAPI API container

This gives the browser one origin and removes the cross-origin / mixed-content problem.

## What This Replaces

This EC2 Compose path is now the preferred runtime instead of:

- Vercel frontend + plain HTTP EC2 backend
- FastAPI Cloud backend + EC2 worker
- managed shared credentials across platforms

That earlier split setup is still useful for learning, but it is no longer the easiest production path for the current codebase.

## Still Missing

This is a practical deployment baseline, not the final production architecture.

Still intentionally simple:

- no reverse proxy yet
- no TLS on the EC2 backend yet
- no custom domain on the backend yet
- no S3-compatible shared object storage yet
- no backups automation for the self-hosted PostgreSQL volume
- no rolling deployments or multiple replicas
