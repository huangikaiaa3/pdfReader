"""Document ingestion event stream routes."""

from __future__ import annotations

import json
import time
from typing import Iterator
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.db.models import DocumentVersion, IngestionJob
from app.db.session import SessionLocal
from app.services.queue_service import get_redis_client

router = APIRouter(tags=["document-events"])

TERMINAL_STATUSES = {"ready", "failed"}


@router.get("/document-versions/{document_version_id}/events")
def stream_document_version_events(document_version_id: UUID) -> StreamingResponse:
    """Stream pipeline status events for a specific document version."""

    def event_stream() -> Iterator[str]:
        db = SessionLocal()
        settings = get_settings()
        redis_client = get_redis_client()
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(settings.ingestion_event_channel)
        try:
            current_version = db.query(DocumentVersion).filter(DocumentVersion.id == document_version_id).first()
            if current_version is None:
                yield _format_sse(
                    {
                        "event": "pipeline_status",
                        "document_version_id": str(document_version_id),
                        "ingestion_job_id": "",
                        "status": "failed",
                        "page_count": None,
                        "error_message": "Document version not found.",
                    }
                )
                return

            current_job = (
                db.query(IngestionJob)
                .filter(IngestionJob.document_version_id == document_version_id)
                .order_by(IngestionJob.created_at.desc())
                .first()
            )
            if current_job is None:
                yield _format_sse(
                    {
                        "event": "pipeline_status",
                        "document_version_id": str(document_version_id),
                        "ingestion_job_id": "",
                        "status": "failed",
                        "page_count": current_version.page_count,
                        "error_message": "Ingestion job not found for document version.",
                    }
                )
                return

            initial_payload = _build_event_payload(current_version, current_job)
            if current_version.pipeline_status in TERMINAL_STATUSES:
                yield _format_sse(initial_payload)
                return

            yield _format_sse(initial_payload)

            while True:
                message = pubsub.get_message(timeout=1.0)
                if not message:
                    time.sleep(0.25)
                    continue

                payload = json.loads(message["data"])
                if payload.get("document_version_id") != str(document_version_id):
                    continue

                yield _format_sse(payload)
                if payload.get("status") in TERMINAL_STATUSES:
                    break
        finally:
            pubsub.close()
            db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


def _build_event_payload(document_version: DocumentVersion, ingestion_job: IngestionJob) -> dict:
    """Build the current SSE payload from database state."""

    return {
        "event": "pipeline_status",
        "document_version_id": str(document_version.id),
        "ingestion_job_id": str(ingestion_job.id),
        "status": document_version.pipeline_status,
        "page_count": document_version.page_count,
        "error_message": ingestion_job.error_message,
    }


def _format_sse(payload: dict) -> str:
    """Format a payload as an SSE event."""

    return f"event: {payload['event']}\ndata: {json.dumps(payload)}\n\n"
