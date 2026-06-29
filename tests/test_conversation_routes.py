from __future__ import annotations

from uuid import uuid4

from app.db.models import Conversation, ConversationMessage, Document, DocumentVersion, User
from app.services import conversation_service


def _create_document_version(db_session, owner_user_id, pipeline_status: str = "ready") -> DocumentVersion:
    document = Document(id=uuid4(), owner_user_id=owner_user_id, title="Transcript", source_type="upload")
    document_version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        original_filename="transcript.pdf",
        storage_path="storage/documents/transcript.pdf",
        sha256="d" * 64,
        file_size_bytes=4096,
        mime_type="application/pdf",
        page_count=3,
        pipeline_status=pipeline_status,
    )
    db_session.add(document)
    db_session.add(document_version)
    db_session.commit()
    return document_version


def _create_conversation(db_session, owner_user_id, document_version_id, title: str = "Existing chat") -> Conversation:
    conversation = Conversation(
        owner_user_id=owner_user_id,
        document_version_id=document_version_id,
        title=title,
    )
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)
    return conversation


def test_create_conversation_route_creates_empty_conversation(client, db_session, current_user):
    document_version = _create_document_version(db_session, current_user.id, pipeline_status="ready")

    response = client.post("/conversations", json={"document_version_id": str(document_version.id)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_version_id"] == str(document_version.id)
    assert payload["title"] == "Chat about Transcript"
    assert payload["message_count"] == 0
    assert payload["messages"] == []
    assert db_session.query(Conversation).count() == 1


def test_create_conversation_route_rejects_non_ready_document(client, db_session, current_user):
    document_version = _create_document_version(db_session, current_user.id, pipeline_status="embedding")

    response = client.post("/conversations", json={"document_version_id": str(document_version.id)})

    assert response.status_code == 409
    assert response.json()["detail"] == "Document version is not ready for conversation."


def test_get_conversation_route_rejects_other_users_conversation(client, db_session):
    other_user = User(email="other@example.com", display_name="Other User")
    db_session.add(other_user)
    db_session.commit()
    db_session.refresh(other_user)

    document_version = _create_document_version(db_session, other_user.id, pipeline_status="ready")
    conversation = _create_conversation(db_session, other_user.id, document_version.id)

    response = client.get(f"/conversations/{conversation.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found."


def test_ask_conversation_question_route_persists_messages(client, db_session, current_user, monkeypatch):
    document_version = _create_document_version(db_session, current_user.id, pipeline_status="ready")
    conversation = _create_conversation(db_session, current_user.id, document_version.id)

    def fake_ask_document_question(db, document_version_id, question, top_k, current_user):
        from app.schemas.document import DocumentAskResponse, DocumentCitationResponse, DocumentSearchMatchResponse

        return DocumentAskResponse(
            document_version_id=document_version_id,
            question=question,
            answer_status="answered",
            answer="The cumulative GPA is 3.582.",
            citations=[
                DocumentCitationResponse(
                    chunk_id=uuid4(),
                    chunk_index=0,
                    start_page_number=2,
                    end_page_number=2,
                )
            ],
            matches=[
                DocumentSearchMatchResponse(
                    chunk_id=uuid4(),
                    chunk_index=0,
                    start_page_number=2,
                    end_page_number=2,
                    text="Cumulative GPA: 3.582",
                    distance=0.08,
                )
            ],
        )

    monkeypatch.setattr(conversation_service, "ask_document_question", fake_ask_document_question)

    response = client.post(
        f"/conversations/{conversation.id}/messages",
        json={"question": "What is the cumulative GPA?", "top_k": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == str(conversation.id)
    assert payload["document_version_id"] == str(document_version.id)
    assert payload["user_message"]["role"] == "user"
    assert payload["user_message"]["content"] == "What is the cumulative GPA?"
    assert payload["assistant_message"]["role"] == "assistant"
    assert payload["assistant_message"]["content"] == "The cumulative GPA is 3.582."
    assert payload["assistant_message"]["answer_status"] == "answered"
    assert len(payload["assistant_message"]["citations"]) == 1
    assert len(payload["matches"]) == 1

    messages = (
        db_session.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at.asc())
        .all()
    )
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


def test_list_conversations_route_filters_by_document_version(client, db_session, current_user):
    document_version_a = _create_document_version(db_session, current_user.id, pipeline_status="ready")
    document_version_b = _create_document_version(db_session, current_user.id, pipeline_status="ready")

    _create_conversation(db_session, current_user.id, document_version_a.id, title="A")
    _create_conversation(db_session, current_user.id, document_version_b.id, title="B")

    response = client.get(f"/conversations?document_version_id={document_version_a.id}")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["document_version_id"] == str(document_version_a.id)
    assert payload[0]["title"] == "A"
