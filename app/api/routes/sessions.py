"""Temporary session routes."""

from __future__ import annotations

import json
import time
from typing import Annotated, Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.core.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal, get_db
from app.schemas.session import SessionAskRequest, SessionAskResponse, SessionDetailResponse, SessionEndResponse
from app.services.queue_service import get_redis_client
from app.services.session_service import (
    ask_session_question,
    create_session,
    end_session,
    expire_stale_sessions,
    get_current_session,
    get_session,
)

router = APIRouter(tags=["sessions"])

TERMINAL_SESSION_STATUSES = {"ready", "failed"}


@router.post("/sessions", response_model=SessionDetailResponse)
def create_session_route(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> SessionDetailResponse:
    """Start a new temporary PDF chat session."""

    return create_session(db=db, file=file, current_user=current_user)


@router.get("/sessions/current", response_model=SessionDetailResponse)
def get_current_session_route(
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> SessionDetailResponse:
    """Return the user's current active session."""

    return get_current_session(db=db, current_user=current_user)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session_route(
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> SessionDetailResponse:
    """Return one active or failed session."""

    return get_session(db=db, session_id=session_id, current_user=current_user)


@router.post("/sessions/{session_id}/messages", response_model=SessionAskResponse)
def ask_session_question_route(
    session_id: UUID,
    payload: SessionAskRequest,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> SessionAskResponse:
    """Ask one question within a temporary session."""

    return ask_session_question(
        db=db,
        session_id=session_id,
        question=payload.question,
        top_k=payload.top_k,
        current_user=current_user,
    )


@router.post("/sessions/{session_id}/end", response_model=SessionEndResponse)
def end_session_route(
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> SessionEndResponse:
    """End a temporary session and delete its artifacts."""

    return end_session(db=db, session_id=session_id, current_user=current_user)


@router.get("/sessions/{session_id}/events")
def stream_session_events_route(
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """Stream status events for one temporary session."""

    def event_stream() -> Iterator[str]:
        db = SessionLocal()
        settings = get_settings()
        redis_client = get_redis_client()
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(settings.ingestion_event_channel)
        try:
            expire_stale_sessions(db=db, owner_user_id=current_user.id)
            current_session = get_session(db=db, session_id=session_id, current_user=current_user)
            initial_payload = {
                "event": "session_status",
                "session_id": str(current_session.session_id),
                "document_version_id": str(current_session.document_version_id),
                "status": current_session.status,
                "pipeline_status": current_session.pipeline_status,
                "page_count": current_session.page_count,
                "error_message": current_session.failure_message,
            }
            yield _format_sse(initial_payload)
            if current_session.status in TERMINAL_SESSION_STATUSES:
                return

            while True:
                message = pubsub.get_message(timeout=1.0)
                if not message:
                    time.sleep(0.25)
                    continue
                payload = json.loads(message["data"])
                if payload.get("session_id") != str(session_id):
                    continue
                yield _format_sse(payload)
                if payload.get("status") in TERMINAL_SESSION_STATUSES:
                    break
        finally:
            pubsub.close()
            db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


def _format_sse(payload: dict) -> str:
    """Format a payload as an SSE event."""

    return f"event: {payload['event']}\ndata: {json.dumps(payload)}\n\n"
