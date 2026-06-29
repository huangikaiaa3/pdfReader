"""Conversation persistence and message orchestration services."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.db.models import Conversation, ConversationMessage, Document, DocumentVersion, User
from app.schemas.conversation import (
    ConversationAskResponse,
    ConversationDetailResponse,
    ConversationMessageResponse,
    ConversationSummaryResponse,
)
from app.schemas.document import DocumentCitationResponse
from app.services.qa_service import ask_document_question


def create_conversation(db, document_version_id, current_user: User, title: str | None) -> ConversationDetailResponse:
    """Create one user-owned conversation for a ready document version."""

    document_version = _get_owned_document_version(db, document_version_id, current_user)
    if document_version.pipeline_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document version is not ready for conversation.",
        )

    conversation = Conversation(
        owner_user_id=current_user.id,
        document_version_id=document_version.id,
        title=(title or f"Chat about {document_version.document.title}").strip(),
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _build_conversation_detail_response(conversation)


def list_conversations(db, current_user: User, document_version_id=None) -> list[ConversationSummaryResponse]:
    """List conversations visible to the current user, optionally scoped to one document version."""

    query = db.query(Conversation).filter(Conversation.owner_user_id == current_user.id)
    if document_version_id is not None:
        query = query.filter(Conversation.document_version_id == document_version_id)
    conversations = query.order_by(Conversation.updated_at.desc(), Conversation.created_at.desc()).all()
    return [_build_conversation_summary_response(conversation) for conversation in conversations]


def get_conversation(db, conversation_id, current_user: User) -> ConversationDetailResponse:
    """Return one user-owned conversation with its persisted messages."""

    conversation = _get_owned_conversation(db, conversation_id, current_user)
    return _build_conversation_detail_response(conversation)


def ask_conversation_question(
    db,
    conversation_id,
    question: str,
    top_k: int,
    current_user: User,
) -> ConversationAskResponse:
    """Persist one question/answer pair inside a conversation."""

    conversation = _get_owned_conversation(db, conversation_id, current_user)

    user_message = ConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=question,
        answer_status=None,
        citations_json=None,
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    answer_response = ask_document_question(
        db=db,
        document_version_id=conversation.document_version_id,
        question=question,
        top_k=top_k,
        current_user=current_user,
    )

    assistant_message = ConversationMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=answer_response.answer,
        answer_status=answer_response.answer_status,
        citations_json=[citation.model_dump(mode="json") for citation in answer_response.citations],
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    db.refresh(conversation)

    return ConversationAskResponse(
        conversation_id=conversation.id,
        document_version_id=conversation.document_version_id,
        user_message=_build_message_response(user_message),
        assistant_message=_build_message_response(assistant_message),
        matches=answer_response.matches,
    )


def _get_owned_document_version(db, document_version_id, current_user: User) -> DocumentVersion:
    """Load one owned document version together with its parent document."""

    document_version = (
        db.query(DocumentVersion)
        .join(Document)
        .filter(DocumentVersion.id == document_version_id, Document.owner_user_id == current_user.id)
        .first()
    )
    if document_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found.")
    return document_version


def _get_owned_conversation(db, conversation_id, current_user: User) -> Conversation:
    """Load one conversation owned by the current user."""

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.owner_user_id == current_user.id)
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conversation


def _build_conversation_summary_response(conversation: Conversation) -> ConversationSummaryResponse:
    """Serialize one conversation summary."""

    return ConversationSummaryResponse(
        conversation_id=conversation.id,
        document_version_id=conversation.document_version_id,
        title=conversation.title,
        message_count=len(conversation.messages),
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
    )


def _build_conversation_detail_response(conversation: Conversation) -> ConversationDetailResponse:
    """Serialize one full conversation with chronologically ordered messages."""

    messages = sorted(conversation.messages, key=lambda message: (message.created_at, message.id))
    return ConversationDetailResponse(
        conversation_id=conversation.id,
        document_version_id=conversation.document_version_id,
        title=conversation.title,
        message_count=len(messages),
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        messages=[_build_message_response(message) for message in messages],
    )


def _build_message_response(message: ConversationMessage) -> ConversationMessageResponse:
    """Serialize one persisted conversation message."""

    citations_json = message.citations_json or []
    return ConversationMessageResponse(
        message_id=message.id,
        role=message.role,
        content=message.content,
        answer_status=message.answer_status,
        citations=[DocumentCitationResponse(**citation) for citation in citations_json],
        created_at=message.created_at.isoformat(),
        updated_at=message.updated_at.isoformat(),
    )
