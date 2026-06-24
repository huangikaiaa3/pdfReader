"""Ingestion job processing services."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import UUID

from app.db.models import ChunkEmbedding, DocumentChunk, DocumentPage, DocumentVersion, IngestionJob
from app.db.session import SessionLocal
from app.services.chunking_service import build_document_chunks
from app.services.embedding_service import build_chunk_embedding_payloads
from app.services.extraction_service import extract_pdf_text
from app.services.queue_service import enqueue_ingestion_job, publish_ingestion_event

logger = logging.getLogger(__name__)


def process_ingestion_job(ingestion_job_id: UUID | str) -> None:
    """Dispatch one ingestion job to the correct pipeline stage handler."""

    db = SessionLocal()
    try:
        logger.info("Starting ingestion job %s", ingestion_job_id)
        ingestion_job = db.query(IngestionJob).filter(IngestionJob.id == ingestion_job_id).first()
        if ingestion_job is None:
            logger.warning("Ingestion job %s not found", ingestion_job_id)
            return

        if ingestion_job.job_type == "extract_text":
            process_extraction_job(db, ingestion_job)
            return
        if ingestion_job.job_type == "chunk_text":
            process_chunking_job(db, ingestion_job)
            return
        if ingestion_job.job_type == "build_embeddings":
            process_embedding_job(db, ingestion_job)
            return

        _mark_job_failed(
            db,
            ingestion_job,
            f"Unsupported ingestion job type: {ingestion_job.job_type}",
        )
        logger.error("Unsupported ingestion job type '%s' for job %s", ingestion_job.job_type, ingestion_job_id)
    except Exception as exc:
        logger.exception("Ingestion job %s crashed", ingestion_job_id)
        ingestion_job = db.query(IngestionJob).filter(IngestionJob.id == ingestion_job_id).first()
        if ingestion_job is not None:
            _mark_job_failed(db, ingestion_job, str(exc))
    finally:
        db.close()


def process_extraction_job(db, ingestion_job: IngestionJob) -> None:
    """Run PDF extraction for one ingestion job and persist the outcome."""

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
    try:
        if document_version is None:
            _mark_job_failed(db, ingestion_job, "Document version not found for ingestion job.")
            logger.error("Document version missing for ingestion job %s", ingestion_job.id)
            return

        ingestion_job.status = "running"
        ingestion_job.started_at = datetime.now(timezone.utc)
        ingestion_job.error_message = None
        document_version.pipeline_status = "extracting"
        db.commit()
        logger.info("Ingestion job %s marked running", ingestion_job.id)
        _publish_pipeline_event(document_version, ingestion_job)

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
            next_job = _create_next_job(db, document_version.id, "chunk_text")
            document_version.pipeline_status = "chunking"
            ingestion_job.status = "succeeded"
            ingestion_job.error_message = None
            logger.info(
                "Ingestion job %s succeeded with page_count=%s total_char_count=%s",
                ingestion_job.id,
                extraction_result["page_count"],
                extraction_result["total_char_count"],
            )
        else:
            document_version.pipeline_status = "failed"
            ingestion_job.status = "failed"
            ingestion_job.error_message = extraction_result["message"]
            logger.warning(
                "Ingestion job %s failed readability check: %s",
                ingestion_job.id,
                extraction_result["message"],
            )

        ingestion_job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _publish_pipeline_event(document_version, ingestion_job)
        if extraction_result["is_readable"]:
            enqueue_ingestion_job(next_job.id)
    except Exception as exc:
        _mark_job_failed(db, ingestion_job, str(exc))
        logger.exception("Extraction job %s crashed", ingestion_job.id)


def process_chunking_job(db, ingestion_job: IngestionJob) -> None:
    """Build retrieval chunks from extracted page text."""

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
    try:
        if document_version is None:
            _mark_job_failed(db, ingestion_job, "Document version not found for ingestion job.")
            logger.error("Document version missing for ingestion job %s", ingestion_job.id)
            return

        document_pages = (
            db.query(DocumentPage)
            .filter(DocumentPage.document_version_id == document_version.id)
            .order_by(DocumentPage.page_number.asc())
            .all()
        )
        if not document_pages:
            _mark_job_failed(db, ingestion_job, "No extracted pages found for chunking.")
            logger.error("No extracted pages found for chunking job %s", ingestion_job.id)
            return

        ingestion_job.status = "running"
        ingestion_job.started_at = datetime.now(timezone.utc)
        ingestion_job.error_message = None
        document_version.pipeline_status = "chunking"
        db.commit()
        logger.info("Chunking job %s marked running", ingestion_job.id)
        _publish_pipeline_event(document_version, ingestion_job)

        chunk_payloads = build_document_chunks(document_pages)
        if not chunk_payloads:
            _mark_job_failed(db, ingestion_job, "No usable chunks were produced from extracted text.")
            logger.warning("Chunking job %s produced no chunks", ingestion_job.id)
            return

        for payload in chunk_payloads:
            db.add(
                DocumentChunk(
                    document_version_id=document_version.id,
                    chunk_index=payload["chunk_index"],
                    start_page_number=payload["start_page_number"],
                    end_page_number=payload["end_page_number"],
                    text=payload["text"],
                    char_count=payload["char_count"],
                )
            )

        next_job = _create_next_job(db, document_version.id, "build_embeddings")
        document_version.pipeline_status = "embedding"
        ingestion_job.status = "succeeded"
        ingestion_job.error_message = None
        ingestion_job.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Chunking job %s succeeded with chunk_count=%s", ingestion_job.id, len(chunk_payloads))
        _publish_pipeline_event(document_version, ingestion_job)
        enqueue_ingestion_job(next_job.id)
    except Exception as exc:
        _mark_job_failed(db, ingestion_job, str(exc))
        logger.exception("Chunking job %s crashed", ingestion_job.id)


def process_embedding_job(db, ingestion_job: IngestionJob) -> None:
    """Generate and persist embeddings for document chunks."""

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
    try:
        if document_version is None:
            _mark_job_failed(db, ingestion_job, "Document version not found for ingestion job.")
            logger.error("Document version missing for embedding job %s", ingestion_job.id)
            return

        document_chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_version_id == document_version.id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        if not document_chunks:
            _mark_job_failed(db, ingestion_job, "No document chunks found for embedding generation.")
            logger.error("No document chunks found for embedding job %s", ingestion_job.id)
            return

        ingestion_job.status = "running"
        ingestion_job.started_at = datetime.now(timezone.utc)
        ingestion_job.error_message = None
        document_version.pipeline_status = "embedding"
        db.commit()
        _publish_pipeline_event(document_version, ingestion_job)

        embedding_payloads = build_chunk_embedding_payloads(document_version, document_chunks)
        if not embedding_payloads:
            _mark_job_failed(db, ingestion_job, "No embeddings were produced for document chunks.")
            logger.warning("Embedding job %s produced no embeddings", ingestion_job.id)
            return

        for payload in embedding_payloads:
            db.add(
                ChunkEmbedding(
                    document_chunk_id=payload["document_chunk_id"],
                    embedding_model=payload["embedding_model"],
                    dimensions=payload["dimensions"],
                    vector=payload["vector"],
                )
            )

        document_version.pipeline_status = "ready"
        ingestion_job.status = "succeeded"
        ingestion_job.error_message = None
        ingestion_job.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Embedding job %s succeeded with embedding_count=%s", ingestion_job.id, len(embedding_payloads))
        _publish_pipeline_event(document_version, ingestion_job)
    except Exception as exc:
        _mark_job_failed(db, ingestion_job, str(exc))
        logger.exception("Embedding job %s crashed", ingestion_job.id)


def _mark_job_failed(db, ingestion_job: IngestionJob, error_message: str) -> None:
    """Mark one ingestion job and its document version as failed."""

    ingestion_job.status = "failed"
    ingestion_job.error_message = error_message
    ingestion_job.started_at = ingestion_job.started_at or datetime.now(timezone.utc)
    ingestion_job.finished_at = datetime.now(timezone.utc)

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
    if document_version is not None:
        document_version.pipeline_status = "failed"

    db.commit()

    if document_version is not None:
        _publish_pipeline_event(document_version, ingestion_job)
    else:
        publish_ingestion_event(
            {
                "event": "pipeline_status",
                "document_version_id": str(ingestion_job.document_version_id),
                "ingestion_job_id": str(ingestion_job.id),
                "status": "failed",
                "page_count": None,
                "error_message": error_message,
            }
        )


def _publish_pipeline_event(document_version: DocumentVersion, ingestion_job: IngestionJob) -> None:
    """Publish the current pipeline state for one document version."""

    publish_ingestion_event(
        {
            "event": "pipeline_status",
            "document_version_id": str(document_version.id),
            "ingestion_job_id": str(ingestion_job.id),
            "status": document_version.pipeline_status,
            "page_count": document_version.page_count,
            "error_message": ingestion_job.error_message,
        }
    )


def _create_next_job(db, document_version_id: UUID, job_type: str) -> IngestionJob:
    """Create the next stage job for one document version."""

    next_job = IngestionJob(
        document_version_id=document_version_id,
        job_type=job_type,
        status="pending",
        attempt_count=1,
    )
    db.add(next_job)
    db.flush()
    return next_job
