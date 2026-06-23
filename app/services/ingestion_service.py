"""Ingestion job processing services."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import UUID

from app.db.models import DocumentPage, DocumentVersion, IngestionJob
from app.db.session import SessionLocal
from app.services.extraction_service import extract_pdf_text
from app.services.queue_service import publish_ingestion_event

logger = logging.getLogger(__name__)


def process_extraction_job(ingestion_job_id: UUID | str) -> None:
    """Run PDF extraction for an ingestion job and persist the outcome."""

    db = SessionLocal()
    try:
        logger.info("Starting ingestion job %s", ingestion_job_id)
        ingestion_job = db.query(IngestionJob).filter(IngestionJob.id == ingestion_job_id).first()
        if ingestion_job is None:
            logger.warning("Ingestion job %s not found", ingestion_job_id)
            return

        document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
        if document_version is None:
            ingestion_job.status = "failed"
            ingestion_job.error_message = "Document version not found for ingestion job."
            ingestion_job.started_at = ingestion_job.started_at or datetime.now(timezone.utc)
            ingestion_job.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.error("Document version missing for ingestion job %s", ingestion_job_id)
            return

        ingestion_job.status = "running"
        ingestion_job.started_at = datetime.now(timezone.utc)
        ingestion_job.error_message = None
        document_version.extraction_status = "running"
        db.commit()
        logger.info("Ingestion job %s marked running", ingestion_job_id)
        publish_ingestion_event(
            {
                "event": "extraction_status",
                "document_version_id": str(document_version.id),
                "ingestion_job_id": str(ingestion_job.id),
                "status": "running",
                "page_count": document_version.page_count,
                "error_message": None,
            }
        )

        extraction_result = extract_pdf_text(document_version.storage_path)
        document_version.page_count = extraction_result["page_count"]

        if extraction_result["is_readable"]:
            for page in extraction_result["pages"]:
                document_page = DocumentPage(
                    document_version_id=document_version.id,
                    page_number=page["page_number"],
                    text=page["text"],
                    char_count=page["char_count"],
                )
                db.add(document_page)
            document_version.extraction_status = "succeeded"
            ingestion_job.status = "succeeded"
            ingestion_job.error_message = None
            logger.info(
                "Ingestion job %s succeeded with page_count=%s total_char_count=%s",
                ingestion_job_id,
                extraction_result["page_count"],
                extraction_result["total_char_count"],
            )
        else:
            document_version.extraction_status = "failed"
            ingestion_job.status = "failed"
            ingestion_job.error_message = extraction_result["message"]
            logger.warning(
                "Ingestion job %s failed readability check: %s",
                ingestion_job_id,
                extraction_result["message"],
            )

        ingestion_job.finished_at = datetime.now(timezone.utc)
        db.commit()
        publish_ingestion_event(
            {
                "event": "extraction_status",
                "document_version_id": str(document_version.id),
                "ingestion_job_id": str(ingestion_job.id),
                "status": document_version.extraction_status,
                "page_count": extraction_result["page_count"],
                "error_message": ingestion_job.error_message,
            }
        )
    except Exception as exc:
        ingestion_job = db.query(IngestionJob).filter(IngestionJob.id == ingestion_job_id).first()
        if ingestion_job is not None:
            ingestion_job.status = "failed"
            ingestion_job.error_message = str(exc)
            ingestion_job.started_at = ingestion_job.started_at or datetime.now(timezone.utc)
            ingestion_job.finished_at = datetime.now(timezone.utc)
            document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
            if document_version is not None:
                document_version.extraction_status = "failed"
            db.commit()
            publish_ingestion_event(
                {
                    "event": "extraction_status",
                    "document_version_id": str(ingestion_job.document_version_id),
                    "ingestion_job_id": str(ingestion_job.id),
                    "status": "failed",
                    "page_count": None,
                    "error_message": str(exc),
                }
            )
        logger.exception("Ingestion job %s crashed", ingestion_job_id)
    finally:
        db.close()
