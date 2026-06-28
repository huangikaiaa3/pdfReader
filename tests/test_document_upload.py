from __future__ import annotations

from types import SimpleNamespace

from app.db.models import Document, DocumentVersion, IngestionJob
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
