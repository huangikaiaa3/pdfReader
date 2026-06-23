"""Redis-backed ingestion worker."""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.services.ingestion_service import process_extraction_job
from app.services.queue_service import get_redis_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Continuously consume ingestion jobs from Redis and process them."""

    settings = get_settings()
    client = get_redis_client()
    logger.info("Ingestion worker started. Waiting on queue '%s'.", settings.ingestion_queue_name)

    while True:
        _, ingestion_job_id = client.blpop(settings.ingestion_queue_name)
        logger.info("Dequeued ingestion job %s", ingestion_job_id)
        process_extraction_job(ingestion_job_id)


if __name__ == "__main__":
    main()
