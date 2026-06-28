"""Document-related API schemas."""

from uuid import UUID

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    """Response schema for a successful document upload."""

    document_id: UUID
    document_version_id: UUID
    ingestion_job_id: UUID
    pipeline_status: str


class DocumentRecoveryResponse(BaseModel):
    """Response schema for a document-version recovery request."""

    document_version_id: UUID
    ingestion_job_id: UUID | None
    pipeline_status: str
    message: str


class LatestIngestionJobResponse(BaseModel):
    """Summary of the most recent ingestion job for one document version."""

    ingestion_job_id: UUID
    job_type: str
    status: str
    attempt_count: int
    error_message: str | None
    started_at: str | None
    finished_at: str | None


class DocumentArtifactCountsResponse(BaseModel):
    """Counts of persisted ingestion artifacts for one document version."""

    pages: int
    chunks: int
    embeddings: int


class DocumentVersionStatusResponse(BaseModel):
    """Current status snapshot for one document version."""

    document_id: UUID
    document_version_id: UUID
    title: str
    original_filename: str
    pipeline_status: str
    page_count: int | None
    file_size_bytes: int
    mime_type: str
    created_at: str
    updated_at: str
    latest_job: LatestIngestionJobResponse | None
    artifact_counts: DocumentArtifactCountsResponse
