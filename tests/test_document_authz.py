from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.db.models import Document, DocumentVersion, User


def test_document_status_route_rejects_access_to_other_users_document(client, db_session):
    other_user = User(email="other@example.com", display_name="Other User")
    db_session.add(other_user)
    db_session.commit()
    db_session.refresh(other_user)

    document = Document(id=uuid4(), owner_user_id=other_user.id, title="Private Doc", source_type="upload")
    document_version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        original_filename="private.pdf",
        storage_path="storage/documents/private.pdf",
        sha256="d" * 64,
        file_size_bytes=1024,
        mime_type="application/pdf",
        page_count=1,
        pipeline_status="ready",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(document)
    db_session.add(document_version)
    db_session.commit()

    response = client.get(f"/document-versions/{document_version.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document version not found."


def test_upload_deduplicates_only_within_same_owner(client, db_session, monkeypatch):
    from app.services import document_service

    queued_job_ids: list[str] = []
    monkeypatch.setattr(
        document_service,
        "get_document_storage",
        lambda: type(
            "Storage",
            (),
            {
                "store_pdf": lambda self, document_version_id, file_bytes: type(
                    "StoredObject",
                    (),
                    {
                        "uri": f"local://documents/{document_version_id}.pdf",
                        "backend": "local",
                        "key": f"documents/{document_version_id}.pdf",
                    },
                )()
            },
        )(),
    )
    monkeypatch.setattr(document_service, "enqueue_ingestion_job", lambda job_id: queued_job_ids.append(str(job_id)))

    file_payload = {
        "file": ("shared.pdf", b"%PDF-1.4\nshared bytes\n", "application/pdf"),
    }
    first_response = client.post("/documents/upload", files=file_payload)
    assert first_response.status_code == 200

    other_user = User(email="second@example.com", display_name="Second User")
    db_session.add(other_user)
    db_session.commit()
    db_session.refresh(other_user)

    from app.api.deps.auth import get_current_user
    from app.main import app as fastapi_app

    def override_other_user():
        return other_user

    fastapi_app.dependency_overrides[get_current_user] = override_other_user
    try:
        second_response = client.post("/documents/upload", files=file_payload)
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)

    assert second_response.status_code == 200
    first_json = first_response.json()
    second_json = second_response.json()
    assert first_json["document_version_id"] != second_json["document_version_id"]
