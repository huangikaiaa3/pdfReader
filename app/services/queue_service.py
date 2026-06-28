"""Redis-backed queue helpers for ingestion work."""

from __future__ import annotations

import json
from uuid import UUID

from redis import Redis

from app.core.config import get_settings


def get_redis_client() -> Redis:
    """Return a Redis client for queue operations."""

    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def enqueue_ingestion_job(ingestion_job_id: UUID) -> None:
    """Push an ingestion job onto the Redis queue."""

    settings = get_settings()
    client = get_redis_client()
    client.rpush(settings.ingestion_queue_name, str(ingestion_job_id))


def publish_ingestion_event(payload: dict) -> None:
    """Publish an ingestion event for SSE consumers."""

    settings = get_settings()
    client = get_redis_client()
    client.publish(settings.ingestion_event_channel, json.dumps(payload))
