#!/bin/sh
set -eu

exec python -m app.workers.ingestion_worker
