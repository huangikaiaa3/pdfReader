"""Redis-backed ingestion worker."""

from __future__ import annotations

import logging
import time

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal
from app.services.ingestion_service import process_ingestion_job, recover_orphaned_running_jobs
from app.services.session_service import expire_stale_sessions
from app.services.queue_service import get_redis_client

setup_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


def main() -> None:
    """Continuously consume ingestion jobs from Redis and process them."""

    settings = get_settings()
    client = get_redis_client()
    db = SessionLocal()
    try:
        recovered_count = recover_orphaned_running_jobs(db)
    finally:
        db.close()

    if recovered_count:
        logger.warning("Recovered %s orphaned running ingestion job(s) on startup.", recovered_count)

    db = SessionLocal()
    try:
        expired_count = expire_stale_sessions(db)
    finally:
        db.close()
    if expired_count:
        logger.info("Expired %s stale session(s) on worker startup.", expired_count)

    logger.info("Ingestion worker started. Waiting on queue '%s'.", settings.ingestion_queue_name)
    next_cleanup_at = time.monotonic() + settings.session_cleanup_interval_seconds

    while True:
        message = client.blpop(settings.ingestion_queue_name, timeout=5)
        if message:
            _, ingestion_job_id = message
            logger.info("Dequeued ingestion job %s", ingestion_job_id)
            process_ingestion_job(ingestion_job_id)

        if time.monotonic() >= next_cleanup_at:
            db = SessionLocal()
            try:
                expired_count = expire_stale_sessions(db)
            finally:
                db.close()
            if expired_count:
                logger.info("Expired %s stale session(s) during worker cleanup pass.", expired_count)
            next_cleanup_at = time.monotonic() + settings.session_cleanup_interval_seconds


if __name__ == "__main__":
    main()
