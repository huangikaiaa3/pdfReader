from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.db.models import ChunkEmbedding, Document, DocumentChunk, DocumentPage, DocumentVersion, IngestionJob
from app.services import document_service


def test_upload_document_deduplicates_by_checksum(client, db_session, monkeypatch, tmp_path):
    queued_job_ids: list[str] = []

    monkeypatch.setattr(
        document_service,
        "get_settings",
        lambda: SimpleNamespace(storage_root=str(tmp_path)),
    )
    monkeypatch.setattr(
        document_service,
        "enqueue_ingestion_job",
        lambda job_id: queued_job_ids.append(str(job_id)),
    )

    file_payload = {
        "file": ("sample.pdf", b"%PDF-1.4\nfake pdf bytes\n", "application/pdf"),
    }

    first_response = client.post("/documents/upload", files=file_payload)
    second_response = client.post("/documents/upload", files=file_payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_json = first_response.json()
    second_json = second_response.json()

    assert second_json["document_id"] == first_json["document_id"]
    assert second_json["document_version_id"] == first_json["document_version_id"]
    assert second_json["ingestion_job_id"] == first_json["ingestion_job_id"]
    assert len(queued_job_ids) == 1

    assert db_session.query(Document).count() == 1
    assert db_session.query(DocumentVersion).count() == 1
    assert db_session.query(IngestionJob).count() == 1


def test_get_document_version_returns_status_snapshot(client, db_session, current_user):
    now = datetime.now(timezone.utc)
    document = Document(id=uuid4(), owner_user_id=current_user.id, title="My Transcript", source_type="upload")
    document_version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        original_filename="transcript.pdf",
        storage_path="storage/documents/transcript.pdf",
        sha256="b" * 64,
        file_size_bytes=2048,
        mime_type="application/pdf",
        page_count=3,
        pipeline_status="ready",
        created_at=now,
        updated_at=now,
    )
    db_session.add(document)
    db_session.add(document_version)
    db_session.commit()

    db_session.add_all(
        [
            DocumentPage(document_version_id=document_version.id, page_number=1, text="Page 1", char_count=6),
            DocumentPage(document_version_id=document_version.id, page_number=2, text="Page 2", char_count=6),
            DocumentPage(document_version_id=document_version.id, page_number=3, text="Page 3", char_count=6),
        ]
    )
    db_session.commit()

    chunk_a = DocumentChunk(
        document_version_id=document_version.id,
        chunk_index=0,
        start_page_number=1,
        end_page_number=2,
        text="Chunk A",
        char_count=7,
    )
    chunk_b = DocumentChunk(
        document_version_id=document_version.id,
        chunk_index=1,
        start_page_number=3,
        end_page_number=3,
        text="Chunk B",
        char_count=7,
    )
    db_session.add_all([chunk_a, chunk_b])
    db_session.commit()

    db_session.add_all(
        [
            ChunkEmbedding(document_chunk_id=chunk_a.id, embedding_model="gemini-embedding-2", dimensions=768, vector=[0.0] * 768),
            ChunkEmbedding(document_chunk_id=chunk_b.id, embedding_model="gemini-embedding-2", dimensions=768, vector=[0.0] * 768),
        ]
    )
    latest_job = IngestionJob(
        document_version_id=document_version.id,
        job_type="build_embeddings",
        status="succeeded",
        attempt_count=2,
        error_message=None,
        started_at=now,
        finished_at=now,
    )
    db_session.add(latest_job)
    db_session.commit()

    response = client.get(f"/document-versions/{document_version.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == str(document.id)
    assert payload["document_version_id"] == str(document_version.id)
    assert payload["title"] == "My Transcript"
    assert payload["original_filename"] == "transcript.pdf"
    assert payload["pipeline_status"] == "ready"
    assert payload["page_count"] == 3
    assert payload["file_size_bytes"] == 2048
    assert payload["mime_type"] == "application/pdf"
    assert payload["latest_job"]["job_type"] == "build_embeddings"
    assert payload["latest_job"]["status"] == "succeeded"
    assert payload["latest_job"]["attempt_count"] == 2
    assert payload["artifact_counts"] == {"pages": 3, "chunks": 2, "embeddings": 2}
