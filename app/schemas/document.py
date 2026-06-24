"""Document-related API schemas."""

from uuid import UUID

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    """Response schema for a successful document upload."""

    document_id: UUID
    document_version_id: UUID
    ingestion_job_id: UUID
    pipeline_status: str
