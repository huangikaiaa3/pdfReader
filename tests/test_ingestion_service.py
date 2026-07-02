from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.db.models import ChunkEmbedding, Document, DocumentChunk, DocumentPage, DocumentProfile, DocumentVersion, IngestionJob
from app.services import ingestion_service


def _create_document_version(db_session, current_user, pipeline_status: str = "pending") -> DocumentVersion:
    document = Document(id=uuid4(), owner_user_id=current_user.id, title="Doc", source_type="upload")
    document_version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        original_filename="doc.pdf",
        storage_path="storage/documents/doc.pdf",
        sha256="a" * 64,
        file_size_bytes=123,
        mime_type="application/pdf",
        page_count=1,
        pipeline_status=pipeline_status,
    )
    db_session.add(document)
    db_session.add(document_version)
    db_session.commit()
    return document_version


def test_reset_stage_artifacts_only_removes_stage_outputs(db_session, current_user):
    document_version = _create_document_version(db_session, current_user)
    page = DocumentPage(document_version_id=document_version.id, page_number=1, text="Page one", char_count=8)
    profile = DocumentProfile(
        document_version_id=document_version.id,
        summary="Document summary",
        document_type="letter",
        primary_subject="Test User",
        key_dates_json=["2026-07-02"],
        key_addresses_json=["123 Main St"],
    )
    chunk = DocumentChunk(
        document_version_id=document_version.id,
        chunk_index=0,
        start_page_number=1,
        end_page_number=1,
        text="Chunk one",
        char_count=9,
    )
    db_session.add(page)
    db_session.add(profile)
    db_session.add(chunk)
    db_session.commit()

    embedding = ChunkEmbedding(
        document_chunk_id=chunk.id,
        embedding_model="gemini-embedding-2",
        dimensions=768,
        vector=[0.0] * 768,
    )
    db_session.add(embedding)
    db_session.commit()

    ingestion_service._reset_stage_artifacts(db_session, document_version, "build_embeddings")
    db_session.commit()
    assert db_session.query(DocumentPage).count() == 1
    assert db_session.query(DocumentProfile).count() == 1
    assert db_session.query(DocumentChunk).count() == 1
    assert db_session.query(ChunkEmbedding).count() == 0

    embedding = ChunkEmbedding(
        document_chunk_id=chunk.id,
        embedding_model="gemini-embedding-2",
        dimensions=768,
        vector=[0.0] * 768,
    )
    db_session.add(embedding)
    db_session.commit()

    ingestion_service._reset_stage_artifacts(db_session, document_version, "chunk_text")
    db_session.commit()
    assert db_session.query(DocumentPage).count() == 1
    assert db_session.query(DocumentProfile).count() == 1
    assert db_session.query(DocumentChunk).count() == 0
    assert db_session.query(ChunkEmbedding).count() == 0

    chunk = DocumentChunk(
        document_version_id=document_version.id,
        chunk_index=0,
        start_page_number=1,
        end_page_number=1,
        text="Chunk one",
        char_count=9,
    )
    db_session.add(chunk)
    db_session.commit()

    embedding = ChunkEmbedding(
        document_chunk_id=chunk.id,
        embedding_model="gemini-embedding-2",
        dimensions=768,
        vector=[0.0] * 768,
    )
    db_session.add(embedding)
    db_session.commit()

    ingestion_service._reset_stage_artifacts(db_session, document_version, "extract_text")
    db_session.commit()
    assert db_session.query(DocumentPage).count() == 0
    assert db_session.query(DocumentProfile).count() == 0
    assert db_session.query(DocumentChunk).count() == 0
    assert db_session.query(ChunkEmbedding).count() == 0


def test_mark_job_failed_creates_retry_job_for_retryable_failure(db_session, monkeypatch, current_user):
    queued_job_ids: list[str] = []
    published_payloads: list[dict] = []

    monkeypatch.setattr(
        ingestion_service,
        "enqueue_ingestion_job",
        lambda job_id: queued_job_ids.append(str(job_id)),
    )
    monkeypatch.setattr(
        ingestion_service,
        "publish_ingestion_event",
        lambda payload: published_payloads.append(payload),
    )
    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(ingestion_max_attempts=3),
    )

    document_version = _create_document_version(db_session, current_user, pipeline_status="embedding")
    job = IngestionJob(
        document_version_id=document_version.id,
        job_type="build_embeddings",
        status="running",
        attempt_count=1,
    )
    db_session.add(job)
    db_session.commit()

    ingestion_service._mark_job_failed(db_session, job, "temporary failure", allow_retry=True)

    db_session.expire_all()
    jobs = (
        db_session.query(IngestionJob)
        .filter(IngestionJob.document_version_id == document_version.id)
        .order_by(IngestionJob.created_at.asc())
        .all()
    )
    assert len(jobs) == 2
    assert jobs[0].status == "failed"
    assert jobs[1].job_type == "build_embeddings"
    assert jobs[1].status == "pending"
    assert jobs[1].attempt_count == 2
    assert queued_job_ids == [str(jobs[1].id)]
    assert published_payloads[-1]["status"] == "embedding"


def test_mark_job_failed_stops_retry_for_terminal_failure(db_session, monkeypatch, current_user):
    published_payloads: list[dict] = []

    monkeypatch.setattr(
        ingestion_service,
        "publish_ingestion_event",
        lambda payload: published_payloads.append(payload),
    )
    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(ingestion_max_attempts=3),
    )

    document_version = _create_document_version(db_session, current_user, pipeline_status="extracting")
    job = IngestionJob(
        document_version_id=document_version.id,
        job_type="extract_text",
        status="running",
        attempt_count=1,
    )
    db_session.add(job)
    db_session.commit()

    ingestion_service._mark_job_failed(
        db_session,
        job,
        "No usable text was extracted from this PDF with the current parser.",
        allow_retry=False,
    )

    db_session.expire_all()
    jobs = db_session.query(IngestionJob).filter(IngestionJob.document_version_id == document_version.id).all()
    refreshed_document_version = db_session.query(DocumentVersion).filter(DocumentVersion.id == document_version.id).first()
    assert len(jobs) == 1
    assert jobs[0].status == "failed"
    assert refreshed_document_version.pipeline_status == "failed"
    assert published_payloads[-1]["status"] == "failed"


def test_recover_orphaned_running_jobs_requeues_running_jobs(db_session, monkeypatch, current_user):
    queued_job_ids: list[str] = []
    published_payloads: list[dict] = []

    monkeypatch.setattr(
        ingestion_service,
        "enqueue_ingestion_job",
        lambda job_id: queued_job_ids.append(str(job_id)),
    )
    monkeypatch.setattr(
        ingestion_service,
        "publish_ingestion_event",
        lambda payload: published_payloads.append(payload),
    )
    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(ingestion_max_attempts=3),
    )

    document_version = _create_document_version(db_session, current_user, pipeline_status="chunking")
    running_job = IngestionJob(
        document_version_id=document_version.id,
        job_type="chunk_text",
        status="running",
        attempt_count=1,
    )
    db_session.add(running_job)
    db_session.commit()

    recovered_count = ingestion_service.recover_orphaned_running_jobs(db_session)

    db_session.expire_all()
    jobs = (
        db_session.query(IngestionJob)
        .filter(IngestionJob.document_version_id == document_version.id)
        .order_by(IngestionJob.created_at.asc())
        .all()
    )
    refreshed_document_version = db_session.query(DocumentVersion).filter(DocumentVersion.id == document_version.id).first()

    assert recovered_count == 1
    assert len(jobs) == 2
    assert jobs[0].status == "failed"
    assert jobs[0].error_message == "Worker restarted before completing this job."
    assert jobs[1].job_type == "chunk_text"
    assert jobs[1].status == "pending"
    assert jobs[1].attempt_count == 2
    assert refreshed_document_version.pipeline_status == "chunking"
    assert queued_job_ids == [str(jobs[1].id)]
    assert published_payloads[-1]["status"] == "chunking"


def test_recover_orphaned_running_jobs_ignores_non_running_jobs(db_session, monkeypatch, current_user):
    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(ingestion_max_attempts=3),
    )

    document_version = _create_document_version(db_session, current_user, pipeline_status="ready")
    finished_job = IngestionJob(
        document_version_id=document_version.id,
        job_type="build_embeddings",
        status="succeeded",
        attempt_count=1,
    )
    db_session.add(finished_job)
    db_session.commit()

    recovered_count = ingestion_service.recover_orphaned_running_jobs(db_session)

    jobs = db_session.query(IngestionJob).filter(IngestionJob.document_version_id == document_version.id).all()
    assert recovered_count == 0
    assert len(jobs) == 1
    assert jobs[0].status == "succeeded"


def test_process_extraction_job_fails_when_pdf_exceeds_page_limit(db_session, monkeypatch, current_user):
    document_version = _create_document_version(db_session, current_user, pipeline_status="extracting")
    job = IngestionJob(
        document_version_id=document_version.id,
        job_type="extract_text",
        status="pending",
        attempt_count=1,
    )
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(
        ingestion_service,
        "extract_pdf_text",
        lambda storage_path: {
            "page_count": 150,
            "pages": [],
            "total_char_count": 100,
            "is_readable": True,
            "message": None,
        },
    )
    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(ingestion_max_attempts=3, max_pdf_pages=100),
    )
    monkeypatch.setattr(ingestion_service, "publish_ingestion_event", lambda payload: None)
    monkeypatch.setattr(ingestion_service, "enqueue_ingestion_job", lambda job_id: None)

    ingestion_service.process_extraction_job(db_session, job)

    db_session.expire_all()
    refreshed_job = db_session.query(IngestionJob).filter(IngestionJob.id == job.id).first()
    refreshed_version = db_session.query(DocumentVersion).filter(DocumentVersion.id == document_version.id).first()
    assert refreshed_job.status == "failed"
    assert refreshed_job.error_message == "PDF exceeds the maximum allowed page count of 100."
    assert refreshed_version.pipeline_status == "failed"


def test_process_extraction_job_fails_when_source_pdf_is_missing(db_session, monkeypatch, current_user):
    document_version = _create_document_version(db_session, current_user, pipeline_status="extracting")
    job = IngestionJob(
        document_version_id=document_version.id,
        job_type="extract_text",
        status="pending",
        attempt_count=1,
    )
    db_session.add(job)
    db_session.commit()

    def raise_missing(storage_path):
        raise FileNotFoundError(storage_path)

    monkeypatch.setattr(ingestion_service, "extract_pdf_text", raise_missing)
    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(ingestion_max_attempts=3, max_pdf_pages=100),
    )
    monkeypatch.setattr(ingestion_service, "publish_ingestion_event", lambda payload: None)
    monkeypatch.setattr(ingestion_service, "enqueue_ingestion_job", lambda job_id: None)

    ingestion_service.process_extraction_job(db_session, job)

    db_session.expire_all()
    refreshed_job = db_session.query(IngestionJob).filter(IngestionJob.id == job.id).first()
    refreshed_version = db_session.query(DocumentVersion).filter(DocumentVersion.id == document_version.id).first()
    assert refreshed_job.status == "failed"
    assert refreshed_job.error_message == "Source PDF is no longer available for this session."
    assert refreshed_version.pipeline_status == "failed"


def test_determine_next_job_type_requires_profile_before_advancing(db_session, current_user):
    document_version = _create_document_version(db_session, current_user, pipeline_status="extracting")
    db_session.add(DocumentPage(document_version_id=document_version.id, page_number=1, text="Page one", char_count=8))
    db_session.commit()

    next_job_type = ingestion_service._determine_next_job_type(db_session, document_version)

    assert next_job_type == "extract_text"
