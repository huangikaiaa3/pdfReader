from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services import storage_service


def test_local_document_storage_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(
        storage_service,
        "get_settings",
        lambda: SimpleNamespace(storage_root=str(tmp_path), storage_key_prefix="documents", storage_bucket=None, storage_backend="local"),
    )

    storage = storage_service.LocalDocumentStorage()
    document_version_id = uuid4()
    stored_object = storage.store_pdf(document_version_id=document_version_id, file_bytes=b"%PDF-1.4\nhello\n")

    assert stored_object.uri == f"local://documents/{document_version_id}.pdf"
    assert stored_object.key == f"documents/{document_version_id}.pdf"
    assert storage.read_pdf_bytes(stored_object.uri) == b"%PDF-1.4\nhello\n"


def test_s3_document_storage_formats_object_uri(monkeypatch):
    monkeypatch.setattr(
        storage_service,
        "get_settings",
        lambda: SimpleNamespace(storage_root="storage", storage_key_prefix="documents", storage_bucket="pdfreader-bucket", storage_backend="s3"),
    )

    storage = storage_service.S3DocumentStorage()
    document_version_id = uuid4()
    stored_object = storage.store_pdf(document_version_id=document_version_id, file_bytes=b"ignored")

    assert stored_object.uri == f"s3://pdfreader-bucket/documents/{document_version_id}.pdf"
    assert stored_object.key == f"documents/{document_version_id}.pdf"


def test_settings_require_bucket_for_s3_backend():
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://postgres:postgres@localhost:5432/pdfreader",
            redis_url="redis://localhost:6379/0",
            storage_backend="s3",
        )


def test_settings_require_gemini_key_in_production():
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg://postgres:postgres@localhost:5432/pdfreader",
            redis_url="redis://localhost:6379/0",
        )
