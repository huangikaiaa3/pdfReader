"""Redis-backed ingestion worker."""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal
from app.services.ingestion_service import process_ingestion_job, recover_orphaned_running_jobs
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

    logger.info("Ingestion worker started. Waiting on queue '%s'.", settings.ingestion_queue_name)

    while True:
        _, ingestion_job_id = client.blpop(settings.ingestion_queue_name)
        logger.info("Dequeued ingestion job %s", ingestion_job_id)
        process_ingestion_job(ingestion_job_id)


if __name__ == "__main__":
    main()
