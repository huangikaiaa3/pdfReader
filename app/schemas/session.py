"""Temporary session API schemas."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.document import DocumentCitationResponse, DocumentSearchMatchResponse


class SessionMessageResponse(BaseModel):
    """One message stored during an active temporary session."""

    message_id: UUID
    role: str
    content: str
    answer_status: str | None
    citations: list[DocumentCitationResponse]
    created_at: str
    updated_at: str


class SessionDetailResponse(BaseModel):
    """Current state of one active or failed session."""

    session_id: UUID
    document_version_id: UUID
    status: str
    title: str
    original_filename: str
    pipeline_status: str
    page_count: int | None
    file_size_bytes: int
    failure_message: str | None
    last_activity_at: str
    created_at: str
    updated_at: str
    message_count: int
    messages: list[SessionMessageResponse]


class SessionAskRequest(BaseModel):
    """Request payload for asking one question in an active session."""

    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)


class SessionAskResponse(BaseModel):
    """Result of persisting one user question and assistant answer in a session."""

    session_id: UUID
    document_version_id: UUID
    status: str
    user_message: SessionMessageResponse
    assistant_message: SessionMessageResponse
    matches: list[DocumentSearchMatchResponse]


class SessionEndResponse(BaseModel):
    """Response for ending and cleaning up a session."""

    session_id: UUID
    status: str
    message: str
