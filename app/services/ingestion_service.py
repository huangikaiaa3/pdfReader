"""Ingestion job processing services."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import ChunkEmbedding, Document, DocumentChunk, DocumentPage, DocumentVersion, IngestionJob, User
from app.db.session import SessionLocal
from app.schemas.document import DocumentRecoveryResponse
from app.services.document_service import build_recovery_response
from app.services.chunking_service import build_document_chunks
from app.services.embedding_service import build_chunk_embedding_payloads
from app.services.extraction_service import extract_pdf_text
from app.services.queue_service import enqueue_ingestion_job, publish_ingestion_event
from app.services.session_service import get_session_by_document_version_id, touch_session_activity

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
        if ingestion_job.status == "succeeded":
            logger.info("Skipping already-succeeded ingestion job %s", ingestion_job_id)
            return
        if ingestion_job.status == "running":
            logger.info("Skipping already-running ingestion job %s", ingestion_job_id)
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
            allow_retry=False,
        )
        logger.error("Unsupported ingestion job type '%s' for job %s", ingestion_job.job_type, ingestion_job_id)
    except Exception as exc:
        logger.exception("Ingestion job %s crashed", ingestion_job_id)
        ingestion_job = db.query(IngestionJob).filter(IngestionJob.id == ingestion_job_id).first()
        if ingestion_job is not None:
            _mark_job_failed(db, ingestion_job, str(exc), allow_retry=True)
    finally:
        db.close()


def process_extraction_job(db, ingestion_job: IngestionJob) -> None:
    """Run PDF extraction for one ingestion job and persist the outcome."""

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
    try:
        if document_version is None:
            _mark_job_failed(db, ingestion_job, "Document version not found for ingestion job.", allow_retry=False)
            logger.error("Document version missing for ingestion job %s", ingestion_job.id)
            return

        _reset_stage_artifacts(db, document_version, "extract_text")
        ingestion_job.status = "running"
        ingestion_job.started_at = datetime.now(timezone.utc)
        ingestion_job.finished_at = None
        ingestion_job.error_message = None
        document_version.pipeline_status = "extracting"
        touch_session_activity(db, document_version.id, status="ingesting", failure_message=None)
        db.commit()
        logger.info("Ingestion job %s marked running", ingestion_job.id)
        _publish_pipeline_event(db, document_version, ingestion_job)

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
            touch_session_activity(db, document_version.id, status="ingesting", failure_message=None)
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
            touch_session_activity(db, document_version.id, status="failed", failure_message=extraction_result["message"])
            ingestion_job.status = "failed"
            ingestion_job.error_message = extraction_result["message"]
            ingestion_job.finished_at = datetime.now(timezone.utc)
            db.commit()
            _publish_pipeline_event(db, document_version, ingestion_job)
            logger.warning(
                "Ingestion job %s failed readability check: %s",
                ingestion_job.id,
                extraction_result["message"],
            )
            return

        ingestion_job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _publish_pipeline_event(db, document_version, ingestion_job)
        if extraction_result["is_readable"]:
            enqueue_ingestion_job(next_job.id)
    except Exception as exc:
        _mark_job_failed(db, ingestion_job, str(exc), allow_retry=True)
        logger.exception("Extraction job %s crashed", ingestion_job.id)


def process_chunking_job(db, ingestion_job: IngestionJob) -> None:
    """Build retrieval chunks from extracted page text."""

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
    try:
        if document_version is None:
            _mark_job_failed(db, ingestion_job, "Document version not found for ingestion job.", allow_retry=False)
            logger.error("Document version missing for ingestion job %s", ingestion_job.id)
            return

        document_pages = (
            db.query(DocumentPage)
            .filter(DocumentPage.document_version_id == document_version.id)
            .order_by(DocumentPage.page_number.asc())
            .all()
        )
        if not document_pages:
            _mark_job_failed(db, ingestion_job, "No extracted pages found for chunking.", allow_retry=False)
            logger.error("No extracted pages found for chunking job %s", ingestion_job.id)
            return

        _reset_stage_artifacts(db, document_version, "chunk_text")
        ingestion_job.status = "running"
        ingestion_job.started_at = datetime.now(timezone.utc)
        ingestion_job.finished_at = None
        ingestion_job.error_message = None
        document_version.pipeline_status = "chunking"
        touch_session_activity(db, document_version.id, status="ingesting", failure_message=None)
        db.commit()
        logger.info("Chunking job %s marked running", ingestion_job.id)
        _publish_pipeline_event(db, document_version, ingestion_job)

        chunk_payloads = build_document_chunks(document_pages)
        if not chunk_payloads:
            _mark_job_failed(
                db,
                ingestion_job,
                "No usable chunks were produced from extracted text.",
                allow_retry=False,
            )
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
        touch_session_activity(db, document_version.id, status="ingesting", failure_message=None)
        ingestion_job.status = "succeeded"
        ingestion_job.error_message = None
        ingestion_job.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Chunking job %s succeeded with chunk_count=%s", ingestion_job.id, len(chunk_payloads))
        _publish_pipeline_event(db, document_version, ingestion_job)
        enqueue_ingestion_job(next_job.id)
    except Exception as exc:
        _mark_job_failed(db, ingestion_job, str(exc), allow_retry=True)
        logger.exception("Chunking job %s crashed", ingestion_job.id)


def process_embedding_job(db, ingestion_job: IngestionJob) -> None:
    """Generate and persist embeddings for document chunks."""

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
    try:
        if document_version is None:
            _mark_job_failed(db, ingestion_job, "Document version not found for ingestion job.", allow_retry=False)
            logger.error("Document version missing for embedding job %s", ingestion_job.id)
            return

        document_chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_version_id == document_version.id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        if not document_chunks:
            _mark_job_failed(db, ingestion_job, "No document chunks found for embedding generation.", allow_retry=False)
            logger.error("No document chunks found for embedding job %s", ingestion_job.id)
            return

        _reset_stage_artifacts(db, document_version, "build_embeddings")
        ingestion_job.status = "running"
        ingestion_job.started_at = datetime.now(timezone.utc)
        ingestion_job.finished_at = None
        ingestion_job.error_message = None
        document_version.pipeline_status = "embedding"
        touch_session_activity(db, document_version.id, status="ingesting", failure_message=None)
        db.commit()
        _publish_pipeline_event(db, document_version, ingestion_job)

        embedding_payloads = build_chunk_embedding_payloads(document_version, document_chunks)
        if not embedding_payloads:
            _mark_job_failed(db, ingestion_job, "No embeddings were produced for document chunks.", allow_retry=False)
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
        touch_session_activity(db, document_version.id, status="ready", failure_message=None)
        ingestion_job.status = "succeeded"
        ingestion_job.error_message = None
        ingestion_job.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Embedding job %s succeeded with embedding_count=%s", ingestion_job.id, len(embedding_payloads))
        _publish_pipeline_event(db, document_version, ingestion_job)
    except Exception as exc:
        _mark_job_failed(db, ingestion_job, str(exc), allow_retry=True)
        logger.exception("Embedding job %s crashed", ingestion_job.id)


def recover_orphaned_running_jobs(db, error_message: str = "Worker restarted before completing this job.") -> int:
    """Fail and requeue any jobs left in running state by a previous worker process."""

    running_jobs = db.query(IngestionJob).filter(IngestionJob.status == "running").order_by(IngestionJob.started_at.asc()).all()
    for ingestion_job in running_jobs:
        logger.warning("Recovering orphaned running job %s", ingestion_job.id)
        _mark_job_failed(db, ingestion_job, error_message, allow_retry=True)
    return len(running_jobs)


def recover_document_pipeline(db, document_version_id: UUID | str, current_user: User) -> DocumentRecoveryResponse:
    """Requeue the next required stage for one document version based on stored state."""

    document_version = (
        db.query(DocumentVersion)
        .join(Document)
        .filter(DocumentVersion.id == document_version_id, Document.owner_user_id == current_user.id)
        .first()
    )
    if document_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found.")

    next_job_type = _determine_next_job_type(db, document_version)
    if next_job_type is None:
        return build_recovery_response(
            document_version=document_version,
            ingestion_job=None,
            message="Document version is already ready. No recovery job was enqueued.",
        )

    active_job = _get_active_job(db, document_version.id, next_job_type)
    if active_job is not None:
        return build_recovery_response(
            document_version=document_version,
            ingestion_job=active_job,
            message=f"An active '{next_job_type}' job already exists for this document version.",
        )

    next_job = _create_next_job(db, document_version.id, next_job_type)
    document_version.pipeline_status = _pipeline_status_for_job_type(next_job_type)
    touch_session_activity(db, document_version.id, status="ingesting", failure_message=None)
    db.commit()
    enqueue_ingestion_job(next_job.id)
    _publish_pipeline_event(db, document_version, next_job)
    logger.info(
        "Recovery enqueued job %s (%s) for document version %s",
        next_job.id,
        next_job_type,
        document_version.id,
    )
    return build_recovery_response(
        document_version=document_version,
        ingestion_job=next_job,
        message=f"Enqueued recovery job for stage '{next_job_type}'.",
    )


def _mark_job_failed(db, ingestion_job: IngestionJob, error_message: str, allow_retry: bool) -> None:
    """Mark one ingestion job and its document version as failed."""

    ingestion_job.status = "failed"
    ingestion_job.error_message = error_message
    ingestion_job.started_at = ingestion_job.started_at or datetime.now(timezone.utc)
    ingestion_job.finished_at = datetime.now(timezone.utc)

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == ingestion_job.document_version_id).first()
    retry_job = None
    if allow_retry and document_version is not None and ingestion_job.attempt_count < get_settings().ingestion_max_attempts:
        retry_job = _create_retry_job(db, ingestion_job)
        document_version.pipeline_status = _pipeline_status_for_job_type(ingestion_job.job_type)
        touch_session_activity(db, document_version.id, status="ingesting", failure_message=error_message)
    elif document_version is not None:
        document_version.pipeline_status = "failed"
        touch_session_activity(db, document_version.id, status="failed", failure_message=error_message)

    db.commit()

    if retry_job is not None and document_version is not None:
        logger.warning(
            "Retrying ingestion job %s with replacement job %s (attempt %s/%s)",
            ingestion_job.id,
            retry_job.id,
            retry_job.attempt_count,
            get_settings().ingestion_max_attempts,
        )
        _publish_pipeline_event(db, document_version, retry_job)
        enqueue_ingestion_job(retry_job.id)
    elif document_version is not None:
        _publish_pipeline_event(db, document_version, ingestion_job)
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


def _reset_stage_artifacts(db, document_version: DocumentVersion, job_type: str) -> None:
    """Delete derived rows that the current stage is responsible for rebuilding."""

    document_chunk_ids = (
        select(DocumentChunk.id).where(DocumentChunk.document_version_id == document_version.id)
    )

    if job_type == "extract_text":
        db.query(ChunkEmbedding).filter(ChunkEmbedding.document_chunk_id.in_(document_chunk_ids)).delete(
            synchronize_session=False
        )
        db.query(DocumentChunk).filter(DocumentChunk.document_version_id == document_version.id).delete(
            synchronize_session=False
        )
        db.query(DocumentPage).filter(DocumentPage.document_version_id == document_version.id).delete(
            synchronize_session=False
        )
    elif job_type == "chunk_text":
        db.query(ChunkEmbedding).filter(ChunkEmbedding.document_chunk_id.in_(document_chunk_ids)).delete(
            synchronize_session=False
        )
        db.query(DocumentChunk).filter(DocumentChunk.document_version_id == document_version.id).delete(
            synchronize_session=False
        )
    elif job_type == "build_embeddings":
        db.query(ChunkEmbedding).filter(ChunkEmbedding.document_chunk_id.in_(document_chunk_ids)).delete(
            synchronize_session=False
        )
    db.flush()


def _publish_pipeline_event(db, document_version: DocumentVersion, ingestion_job: IngestionJob) -> None:
    """Publish the current pipeline state for one document version."""

    session = get_session_by_document_version_id(db, document_version.id)
    publish_ingestion_event(
        {
            "event": "session_status",
            "session_id": str(session.id) if session is not None else None,
            "document_version_id": str(document_version.id),
            "ingestion_job_id": str(ingestion_job.id),
            "status": session.status if session is not None else document_version.pipeline_status,
            "pipeline_status": document_version.pipeline_status,
            "page_count": document_version.page_count,
            "error_message": ingestion_job.error_message,
        }
    )


def _determine_next_job_type(db, document_version: DocumentVersion) -> str | None:
    """Inspect persisted state and return the next missing pipeline stage."""

    page_count = db.query(DocumentPage).filter(DocumentPage.document_version_id == document_version.id).count()
    if page_count == 0:
        return "extract_text"

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_version_id == document_version.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not chunks:
        return "chunk_text"

    chunk_ids = [chunk.id for chunk in chunks]
    embedding_count = db.query(ChunkEmbedding).filter(ChunkEmbedding.document_chunk_id.in_(chunk_ids)).count()
    if embedding_count < len(chunk_ids):
        return "build_embeddings"

    return None


def _pipeline_status_for_job_type(job_type: str) -> str:
    """Map one ingestion job type to its visible pipeline status."""

    status_map = {
        "extract_text": "extracting",
        "chunk_text": "chunking",
        "build_embeddings": "embedding",
    }
    return status_map.get(job_type, "pending")


def _get_active_job(db, document_version_id: UUID, job_type: str) -> IngestionJob | None:
    """Return an existing pending or running job for the same document version and stage."""

    return (
        db.query(IngestionJob)
        .filter(
            IngestionJob.document_version_id == document_version_id,
            IngestionJob.job_type == job_type,
            IngestionJob.status.in_(["pending", "running"]),
        )
        .order_by(IngestionJob.created_at.desc())
        .first()
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


def _create_retry_job(db, ingestion_job: IngestionJob) -> IngestionJob:
    """Create a replacement job for a retry attempt of the same stage."""

    retry_job = IngestionJob(
        document_version_id=ingestion_job.document_version_id,
        job_type=ingestion_job.job_type,
        status="pending",
        attempt_count=ingestion_job.attempt_count + 1,
    )
    db.add(retry_job)
    db.flush()
    return retry_job
