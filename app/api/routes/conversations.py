"""Conversation persistence routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps.auth import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.conversation import (
    ConversationAskResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationMessageCreateRequest,
    ConversationSummaryResponse,
)
from app.services.conversation_service import (
    ask_conversation_question,
    create_conversation,
    get_conversation,
    list_conversations,
)

router = APIRouter(tags=["conversations"])


@router.post("/conversations", response_model=ConversationDetailResponse)
def create_conversation_route(
    payload: ConversationCreateRequest,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> ConversationDetailResponse:
    """Create a new conversation tied to one ready document version."""

    return create_conversation(
        db=db,
        document_version_id=payload.document_version_id,
        current_user=current_user,
        title=payload.title,
    )


@router.get("/conversations", response_model=list[ConversationSummaryResponse])
def list_conversations_route(
    document_version_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> list[ConversationSummaryResponse]:
    """List conversations visible to the current user."""

    return list_conversations(db=db, current_user=current_user, document_version_id=document_version_id)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation_route(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> ConversationDetailResponse:
    """Return one persisted conversation and all of its messages."""

    return get_conversation(db=db, conversation_id=conversation_id, current_user=current_user)


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationAskResponse)
def ask_conversation_question_route(
    conversation_id: UUID,
    payload: ConversationMessageCreateRequest,
    db: Session = Depends(get_db),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> ConversationAskResponse:
    """Persist one user question and assistant answer inside a conversation."""

    return ask_conversation_question(
        db=db,
        conversation_id=conversation_id,
        question=payload.question,
        top_k=payload.top_k,
        current_user=current_user,
    )
