# Deployment Notes

## Purpose

This document captures the current production-oriented container runtime path for the PDF reader backend.

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
