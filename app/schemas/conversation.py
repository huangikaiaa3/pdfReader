"""Conversation and message API schemas."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.document import DocumentCitationResponse, DocumentSearchMatchResponse


class ConversationCreateRequest(BaseModel):
    """Request payload for creating a new conversation."""

    document_version_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=255)


class ConversationMessageCreateRequest(BaseModel):
    """Request payload for adding one user question to a conversation."""

    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)


class ConversationMessageResponse(BaseModel):
    """One persisted message inside a conversation."""

    message_id: UUID
    role: str
    content: str
    answer_status: str | None
    citations: list[DocumentCitationResponse]
    created_at: str
    updated_at: str


class ConversationSummaryResponse(BaseModel):
    """Conversation summary for list views."""

    conversation_id: UUID
    document_version_id: UUID
    title: str
    message_count: int
    created_at: str
    updated_at: str


class ConversationDetailResponse(BaseModel):
    """Full conversation payload including all messages."""

    conversation_id: UUID
    document_version_id: UUID
    title: str
    message_count: int
    created_at: str
    updated_at: str
    messages: list[ConversationMessageResponse]


class ConversationAskResponse(BaseModel):
    """Result of persisting one user question and assistant answer."""

    conversation_id: UUID
    document_version_id: UUID
    user_message: ConversationMessageResponse
    assistant_message: ConversationMessageResponse
    matches: list[DocumentSearchMatchResponse]
