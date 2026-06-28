"""Document upload and recovery routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.document import DocumentRecoveryResponse, DocumentUploadResponse, DocumentVersionStatusResponse
from app.services.document_service import get_document_version_status, upload_document
from app.services.ingestion_service import recover_document_pipeline

router = APIRouter(tags=["documents"])


@router.post("/documents/upload", response_model=DocumentUploadResponse)
def upload_document_route(file: UploadFile = File(...), db: Session = Depends(get_db),) -> DocumentUploadResponse:
    """Accept a PDF upload and persist its initial metadata."""

    return upload_document(db=db, file=file)


@router.post("/document-versions/{document_version_id}/recover", response_model=DocumentRecoveryResponse)
def recover_document_version_route(document_version_id: UUID, db: Session = Depends(get_db)) -> DocumentRecoveryResponse:
    """Requeue the next missing ingestion stage for one document version."""

    return recover_document_pipeline(db=db, document_version_id=document_version_id)


@router.get("/document-versions/{document_version_id}", response_model=DocumentVersionStatusResponse)
def get_document_version_route(document_version_id: UUID, db: Session = Depends(get_db)) -> DocumentVersionStatusResponse:
    """Return the current status snapshot for one document version."""

    return get_document_version_status(db=db, document_version_id=document_version_id)
