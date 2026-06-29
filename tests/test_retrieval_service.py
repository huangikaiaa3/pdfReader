from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.db.models import Document, DocumentChunk, DocumentVersion
from app.services import retrieval_service


def _create_document_version(db_session, current_user, pipeline_status: str = "ready") -> DocumentVersion:
    document = Document(id=uuid4(), owner_user_id=current_user.id, title="Searchable Doc", source_type="upload")
    document_version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        original_filename="searchable.pdf",
        storage_path="storage/documents/searchable.pdf",
        sha256="c" * 64,
        file_size_bytes=999,
        mime_type="application/pdf",
        page_count=3,
        pipeline_status=pipeline_status,
    )
    db_session.add(document)
    db_session.add(document_version)
    db_session.commit()
    return document_version


def test_search_document_chunks_returns_ranked_matches(db_session, monkeypatch, current_user):
    document_version = _create_document_version(db_session, current_user, pipeline_status="ready")
    chunk_a = DocumentChunk(
        id=uuid4(),
        document_version_id=document_version.id,
        chunk_index=0,
        start_page_number=1,
        end_page_number=1,
        text="Alpha chunk",
        char_count=11,
    )
    chunk_b = DocumentChunk(
        id=uuid4(),
        document_version_id=document_version.id,
        chunk_index=1,
        start_page_number=2,
        end_page_number=2,
        text="Beta chunk",
        char_count=10,
    )
    db_session.add_all([chunk_a, chunk_b])
    db_session.commit()

    monkeypatch.setattr(retrieval_service, "build_query_embedding", lambda query: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        retrieval_service,
        "_search_document_chunk_rows",
        lambda db, document_version_id, query_vector, top_k: [
            SimpleNamespace(
                chunk_id=chunk_b.id,
                chunk_index=chunk_b.chunk_index,
                start_page_number=chunk_b.start_page_number,
                end_page_number=chunk_b.end_page_number,
                text=chunk_b.text,
                distance=0.12,
            ),
            SimpleNamespace(
                chunk_id=chunk_a.id,
                chunk_index=chunk_a.chunk_index,
                start_page_number=chunk_a.start_page_number,
                end_page_number=chunk_a.end_page_number,
                text=chunk_a.text,
                distance=0.34,
            ),
        ],
    )

    response = retrieval_service.search_document_chunks(
        db=db_session,
        document_version_id=document_version.id,
        query="What is in beta?",
        top_k=2,
        current_user=current_user,
    )

    assert response.document_version_id == document_version.id
    assert response.query == "What is in beta?"
    assert len(response.matches) == 2
    assert response.matches[0].chunk_index == 1
    assert response.matches[0].distance == 0.12
    assert response.matches[1].chunk_index == 0


def test_search_document_chunks_rejects_non_ready_document(db_session, monkeypatch, current_user):
    document_version = _create_document_version(db_session, current_user, pipeline_status="embedding")
    monkeypatch.setattr(retrieval_service, "build_query_embedding", lambda query: [0.1, 0.2, 0.3])

    with pytest.raises(HTTPException) as exc_info:
        retrieval_service.search_document_chunks(
            db=db_session,
            document_version_id=document_version.id,
            query="Can I search yet?",
            top_k=3,
            current_user=current_user,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Document version is not ready for retrieval."


def test_search_document_chunks_raises_for_unknown_document_version(db_session, monkeypatch, current_user):
    monkeypatch.setattr(retrieval_service, "build_query_embedding", lambda query: [0.1, 0.2, 0.3])

    with pytest.raises(HTTPException) as exc_info:
        retrieval_service.search_document_chunks(
            db=db_session,
            document_version_id=uuid4(),
            query="Unknown doc?",
            top_k=3,
            current_user=current_user,
        )

    assert exc_info.value.status_code == 404
