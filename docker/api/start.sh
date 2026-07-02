#!/bin/sh
set -eu

mkdir -p /app/storage /app/storage/documents
chown -R appuser:appuser /app/storage

python -m alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
