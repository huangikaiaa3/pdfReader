"""Document upload workflow services."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document, DocumentVersion, IngestionJob
from app.schemas.document import DocumentRecoveryResponse, DocumentUploadResponse
from app.services.queue_service import enqueue_ingestion_job


def upload_document(db: Session, file: UploadFile) -> DocumentUploadResponse:
    """Persist an uploaded PDF and create its initial ingestion records."""

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF uploads are supported.")

    original_filename = file.filename or "uploaded.pdf"
    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    sha256 = hashlib.sha256(file_bytes).hexdigest()
    existing_document_version = _get_existing_document_version(db=db, sha256=sha256)
    if existing_document_version is not None:
        return _build_duplicate_upload_response(db=db, document_version=existing_document_version)

    document_id = uuid4()
    document_version_id = uuid4()
    ingestion_job_id = uuid4()

    storage_path = _store_uploaded_pdf(document_version_id=document_version_id, file_bytes=file_bytes)
    file_size_bytes = len(file_bytes)

    document = Document(
        id=document_id,
        title=original_filename,
        source_type="upload",
    )
    document_version = DocumentVersion(
        id=document_version_id,
        document_id=document_id,
        original_filename=original_filename,
        storage_path=str(storage_path),
        sha256=sha256,
        file_size_bytes=file_size_bytes,
        mime_type=file.content_type,
        page_count=None,
        pipeline_status="pending",
    )
    ingestion_job = IngestionJob(
        id=ingestion_job_id,
        document_version_id=document_version_id,
        job_type="extract_text",
        status="pending",
        attempt_count=1,
    )

    db.add(document)
    db.add(document_version)
    db.add(ingestion_job)
    db.commit()
    enqueue_ingestion_job(ingestion_job_id)

    return DocumentUploadResponse(
        document_id=document_id,
        document_version_id=document_version_id,
        ingestion_job_id=ingestion_job_id,
        pipeline_status=document_version.pipeline_status,
    )


def _store_uploaded_pdf(document_version_id, file_bytes: bytes) -> Path:
    """Write the uploaded PDF to local storage and return its path."""

    settings = get_settings()
    documents_dir = Path(settings.storage_root) / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    storage_path = documents_dir / f"{document_version_id}.pdf"
    storage_path.write_bytes(file_bytes)
    return storage_path


def _get_existing_document_version(db: Session, sha256: str) -> DocumentVersion | None:
    """Return an existing document version for the given checksum, if one exists."""

    return db.query(DocumentVersion).filter(DocumentVersion.sha256 == sha256).first()


def _build_duplicate_upload_response(db: Session, document_version: DocumentVersion) -> DocumentUploadResponse:
    """Return the existing upload response for a duplicate file upload."""

    ingestion_job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.document_version_id == document_version.id,
            IngestionJob.job_type == "extract_text",
        )
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    if ingestion_job is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Duplicate upload found without an ingestion job.",
        )

    return DocumentUploadResponse(
        document_id=document_version.document_id,
        document_version_id=document_version.id,
        ingestion_job_id=ingestion_job.id,
        pipeline_status=document_version.pipeline_status,
    )


def build_recovery_response(
    document_version: DocumentVersion,
    ingestion_job: IngestionJob | None,
    message: str,
) -> DocumentRecoveryResponse:
    """Build a response describing the next recovery action."""

    return DocumentRecoveryResponse(
        document_version_id=document_version.id,
        ingestion_job_id=ingestion_job.id if ingestion_job is not None else None,
        pipeline_status=document_version.pipeline_status,
        message=message,
    )
