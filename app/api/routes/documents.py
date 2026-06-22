"""Document upload routes."""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.document import DocumentUploadResponse
from app.services.document_service import upload_document

router = APIRouter(tags=["documents"])


@router.post("/documents/upload", response_model=DocumentUploadResponse)
def upload_document_route(file: UploadFile = File(...), db: Session = Depends(get_db),) -> DocumentUploadResponse:
    """Accept a PDF upload and persist its initial metadata."""

    return upload_document(db=db, file=file)
