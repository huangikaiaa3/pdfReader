from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.db.models import Document, DocumentVersion, Session as ChatSession, SessionMessage
from app.services import session_service


def _create_session(db_session, current_user, status: str = "ready", last_activity_at=None) -> ChatSession:
    document = Document(id=uuid4(), owner_user_id=current_user.id, title="Transcript", source_type="session_upload")
    document_version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        original_filename="transcript.pdf",
        storage_path=f"local://documents/{uuid4()}.pdf",
        sha256="a" * 64,
        file_size_bytes=2048,
        mime_type="application/pdf",
        page_count=3,
        pipeline_status="ready" if status == "ready" else "extracting",
    )
    session = ChatSession(
        owner_user_id=current_user.id,
        document_version_id=document_version.id,
        status=status,
        title="Transcript",
        failure_message=None,
        last_activity_at=last_activity_at or datetime.now(timezone.utc),
    )
    db_session.add(document)
    db_session.add(document_version)
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


def test_create_session_route_starts_session(client, db_session, current_user, monkeypatch):
    queued_job_ids: list[str] = []
    monkeypatch.setattr(
        session_service,
        "get_document_storage",
        lambda: SimpleNamespace(
            store_pdf=lambda document_version_id, file_bytes: SimpleNamespace(
                uri=f"local://documents/{document_version_id}.pdf",
                backend="local",
                key=f"documents/{document_version_id}.pdf",
            )
        ),
    )
    monkeypatch.setattr(session_service, "enqueue_ingestion_job", lambda job_id: queued_job_ids.append(str(job_id)))

    response = client.post(
        "/sessions",
        files={"file": ("sample.pdf", b"%PDF-1.4\nsession pdf bytes\n", "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ingesting"
    assert payload["original_filename"] == "sample.pdf"
    assert payload["message_count"] == 0
    assert len(queued_job_ids) == 1


def test_create_session_route_rejects_second_active_session(client, db_session, current_user):
    _create_session(db_session, current_user, status="ready")

    response = client.post(
        "/sessions",
        files={"file": ("sample.pdf", b"%PDF-1.4\nsession pdf bytes\n", "application/pdf")},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "You already have an active session. End it before starting a new one."


def test_create_session_route_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(
        session_service,
        "get_settings",
        lambda: SimpleNamespace(max_upload_size_bytes=4, session_inactivity_timeout_minutes=60),
    )

    response = client.post(
        "/sessions",
        files={"file": ("sample.pdf", b"%PDF-1.4\nthis is too large\n", "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Uploaded file exceeds the maximum allowed size."


def test_create_session_route_expires_stale_session_then_allows_new_one(client, db_session, current_user, monkeypatch):
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=120)
    stale_session = _create_session(db_session, current_user, status="ready", last_activity_at=stale_time)
    stale_storage_path = stale_session.document_version.storage_path

    deleted_uris: list[str] = []
    monkeypatch.setattr(session_service, "delete_pdf", lambda storage_uri: deleted_uris.append(storage_uri))
    monkeypatch.setattr(
        session_service,
        "get_settings",
        lambda: SimpleNamespace(max_upload_size_bytes=10 * 1024 * 1024, session_inactivity_timeout_minutes=60),
    )
    monkeypatch.setattr(
        session_service,
        "get_document_storage",
        lambda: SimpleNamespace(
            store_pdf=lambda document_version_id, file_bytes: SimpleNamespace(
                uri=f"local://documents/{document_version_id}.pdf",
                backend="local",
                key=f"documents/{document_version_id}.pdf",
            )
        ),
    )
    monkeypatch.setattr(session_service, "enqueue_ingestion_job", lambda job_id: None)

    response = client.post(
        "/sessions",
        files={"file": ("sample.pdf", b"%PDF-1.4\nfresh session bytes\n", "application/pdf")},
    )

    assert response.status_code == 200
    assert deleted_uris == [stale_storage_path]


def test_get_current_session_route_returns_current_session(client, db_session, current_user):
    session = _create_session(db_session, current_user, status="ready")

    response = client.get("/sessions/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == str(session.id)
    assert payload["status"] == "ready"


def test_ask_session_question_route_persists_messages(client, db_session, current_user, monkeypatch):
    session = _create_session(db_session, current_user, status="ready")

    def fake_answer_question(db, document_version_id, question, top_k, current_user):
        from app.schemas.document import DocumentAskResponse, DocumentCitationResponse, DocumentSearchMatchResponse

        return DocumentAskResponse(
            document_version_id=document_version_id,
            question=question,
            answer_status="answered",
            answer="The cumulative GPA is 3.582.",
            citations=[DocumentCitationResponse(chunk_id=uuid4(), chunk_index=0, start_page_number=2, end_page_number=2)],
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

    monkeypatch.setattr(session_service, "ask_document_question", fake_answer_question)

    response = client.post(
        f"/sessions/{session.id}/messages",
        json={"question": "What is the cumulative GPA?", "top_k": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["user_message"]["role"] == "user"
    assert payload["assistant_message"]["role"] == "assistant"
    assert len(payload["matches"]) == 1

    messages = db_session.query(SessionMessage).filter(SessionMessage.session_id == session.id).all()
    assert len(messages) == 2


def test_end_session_route_deletes_session_artifacts(client, db_session, current_user, monkeypatch):
    session = _create_session(db_session, current_user, status="ready")
    storage_path = session.document_version.storage_path
    deleted_uris: list[str] = []
    monkeypatch.setattr(session_service, "delete_pdf", lambda storage_uri: deleted_uris.append(storage_uri))

    response = client.post(f"/sessions/{session.id}/end")

    assert response.status_code == 200
    assert response.json()["status"] == "ended"
    assert deleted_uris == [storage_path]
    assert db_session.query(ChatSession).count() == 0
    assert db_session.query(DocumentVersion).count() == 0
