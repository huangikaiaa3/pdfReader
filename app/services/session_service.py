"""Temporary session lifecycle services."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document, DocumentVersion, IngestionJob, Session as ChatSession, SessionMessage, User
from app.schemas.session import SessionAskResponse, SessionDetailResponse, SessionEndResponse, SessionMessageResponse
from app.services.qa_service import ask_document_question
from app.services.queue_service import enqueue_ingestion_job
from app.services.storage_service import delete_pdf, get_document_storage

ACTIVE_SESSION_STATUSES = {"ingesting", "ready", "failed"}
logger = logging.getLogger(__name__)


def create_session(db: Session, file: UploadFile, current_user: User) -> SessionDetailResponse:
    """Create one new temporary session from an uploaded PDF."""

    expire_stale_sessions(db=db, owner_user_id=current_user.id)
    existing_session = _get_active_session(db=db, owner_user_id=current_user.id)
    if existing_session is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active session. End it before starting a new one.",
        )

    file_bytes, original_filename = _read_and_validate_upload(file)
    document_id = uuid4()
    document_version_id = uuid4()
    ingestion_job_id = uuid4()
    now = datetime.now(timezone.utc)

    storage_object = get_document_storage().store_pdf(document_version_id=document_version_id, file_bytes=file_bytes)
    file_size_bytes = len(file_bytes)
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    document = Document(id=document_id, owner_user_id=current_user.id, title=original_filename, source_type="session_upload")
    document_version = DocumentVersion(
        id=document_version_id,
        document_id=document_id,
        original_filename=original_filename,
        storage_path=storage_object.uri,
        sha256=sha256,
        file_size_bytes=file_size_bytes,
        mime_type=file.content_type or "application/pdf",
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
    chat_session = ChatSession(
        owner_user_id=current_user.id,
        document_version_id=document_version_id,
        status="ingesting",
        title=original_filename,
        failure_message=None,
        last_activity_at=now,
    )

    db.add(document)
    db.add(document_version)
    db.add(ingestion_job)
    db.add(chat_session)
    db.commit()
    db.refresh(chat_session)
    enqueue_ingestion_job(ingestion_job_id)
    return _build_session_detail_response(chat_session)


def get_current_session(db: Session, current_user: User) -> SessionDetailResponse:
    """Return the user's single active session if one exists."""

    expire_stale_sessions(db=db, owner_user_id=current_user.id)
    session = _get_active_session(db=db, owner_user_id=current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active session found.")
    return _build_session_detail_response(session)


def get_session(db: Session, session_id, current_user: User) -> SessionDetailResponse:
    """Return one active session owned by the current user."""

    expire_stale_sessions(db=db, owner_user_id=current_user.id)
    session = _get_owned_session(db=db, session_id=session_id, current_user=current_user)
    return _build_session_detail_response(session)


def ask_session_question(db: Session, session_id, question: str, top_k: int, current_user: User) -> SessionAskResponse:
    """Persist one question/answer exchange inside an active session."""

    expire_stale_sessions(db=db, owner_user_id=current_user.id)
    session = _get_owned_session(db=db, session_id=session_id, current_user=current_user)
    if session.status != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not ready for chat yet.")
    if len(question) > get_settings().max_session_question_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question exceeds the maximum allowed length for a session message.",
        )

    user_message = SessionMessage(
        session_id=session.id,
        role="user",
        content=question,
        answer_status=None,
        citations_json=None,
    )
    db.add(user_message)
    session.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user_message)

    try:
        answer_response = ask_document_question(
            db=db,
            document_version_id=session.document_version_id,
            question=question,
            top_k=top_k,
            current_user=current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        session.last_activity_at = datetime.now(timezone.utc)
        db.commit()
        logger.exception("AI answer generation failed for session %s", session.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI service is temporarily unavailable. Please try again.",
        ) from exc

    assistant_message = SessionMessage(
        session_id=session.id,
        role="assistant",
        content=answer_response.answer,
        answer_status=answer_response.answer_status,
        citations_json=[citation.model_dump(mode="json") for citation in answer_response.citations],
    )
    db.add(assistant_message)
    session.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assistant_message)
    db.refresh(session)

    return SessionAskResponse(
        session_id=session.id,
        document_version_id=session.document_version_id,
        status=session.status,
        user_message=_build_session_message_response(user_message),
        assistant_message=_build_session_message_response(assistant_message),
        matches=answer_response.matches,
    )


def end_session(db: Session, session_id, current_user: User) -> SessionEndResponse:
    """End one session and delete all of its temporary artifacts."""

    expire_stale_sessions(db=db, owner_user_id=current_user.id)
    session = _get_owned_session(db=db, session_id=session_id, current_user=current_user)
    _delete_session_artifacts(db=db, session=session)
    return SessionEndResponse(
        session_id=session_id,
        status="ended",
        message="Session ended and temporary artifacts were deleted.",
    )


def expire_stale_sessions(db: Session, owner_user_id=None) -> int:
    """Delete sessions that have been inactive beyond the configured timeout."""

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.session_inactivity_timeout_minutes)
    query = db.query(ChatSession).filter(ChatSession.last_activity_at < cutoff)
    if owner_user_id is not None:
        query = query.filter(ChatSession.owner_user_id == owner_user_id)
    stale_sessions = query.all()
    for stale_session in stale_sessions:
        _delete_session_artifacts(db=db, session=stale_session, commit=False)
    if stale_sessions:
        db.commit()
    return len(stale_sessions)


def touch_session_activity(db: Session, document_version_id, status: str | None = None, failure_message: str | None = None) -> None:
    """Update session state from ingestion pipeline progress."""

    session = db.query(ChatSession).filter(ChatSession.document_version_id == document_version_id).first()
    if session is None:
        return
    if status is not None:
        session.status = status
    session.failure_message = failure_message
    session.last_activity_at = datetime.now(timezone.utc)


def get_session_by_document_version_id(db: Session, document_version_id):
    """Return the session associated with a document version, if present."""

    return db.query(ChatSession).filter(ChatSession.document_version_id == document_version_id).first()


def _read_and_validate_upload(file: UploadFile) -> tuple[bytes, str]:
    """Read and validate the uploaded PDF for a temporary session."""

    settings = get_settings()
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF uploads are supported.")

    original_filename = file.filename or "uploaded.pdf"
    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")
    if len(file_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Uploaded file exceeds the maximum allowed size.")
    return file_bytes, original_filename


def _get_active_session(db: Session, owner_user_id) -> ChatSession | None:
    """Return the current active session for one user, if any."""

    return (
        db.query(ChatSession)
        .filter(ChatSession.owner_user_id == owner_user_id, ChatSession.status.in_(ACTIVE_SESSION_STATUSES))
        .order_by(ChatSession.created_at.desc())
        .first()
    )


def _get_owned_session(db: Session, session_id, current_user: User) -> ChatSession:
    """Return one session owned by the current user."""

    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.owner_user_id == current_user.id).first()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


def _delete_session_artifacts(db: Session, session: ChatSession, commit: bool = True) -> None:
    """Delete one session and all temporary data created for it."""

    storage_path = session.document_version.storage_path
    document = session.document_version.document
    if storage_path:
        try:
            delete_pdf(storage_path)
        except NotImplementedError:
            pass
    db.delete(session)
    db.delete(document)
    if commit:
        db.commit()


def _build_session_detail_response(session: ChatSession) -> SessionDetailResponse:
    """Build the API response for one current session."""

    document_version = session.document_version
    messages = sorted(session.messages, key=lambda message: (message.created_at, message.id))
    return SessionDetailResponse(
        session_id=session.id,
        document_version_id=document_version.id,
        status=session.status,
        title=session.title,
        original_filename=document_version.original_filename,
        pipeline_status=document_version.pipeline_status,
        page_count=document_version.page_count,
        file_size_bytes=document_version.file_size_bytes,
        failure_message=session.failure_message,
        last_activity_at=session.last_activity_at.isoformat(),
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
        message_count=len(messages),
        messages=[_build_session_message_response(message) for message in messages],
    )


def _build_session_message_response(message: SessionMessage) -> SessionMessageResponse:
    """Build the API response for one stored session message."""

    from app.schemas.document import DocumentCitationResponse

    citations_json = message.citations_json or []
    return SessionMessageResponse(
        message_id=message.id,
        role=message.role,
        content=message.content,
        answer_status=message.answer_status,
        citations=[DocumentCitationResponse(**citation) for citation in citations_json],
        created_at=message.created_at.isoformat(),
        updated_at=message.updated_at.isoformat(),
    )
