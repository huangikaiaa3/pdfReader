#!/bin/sh
set -eu

mkdir -p /app/storage /app/storage/documents
chown -R appuser:appuser /app/storage

exec python -m app.workers.ingestion_worker
