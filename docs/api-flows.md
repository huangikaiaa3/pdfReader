# API Flows

## Purpose

This document captures the first API boundary and async flow decisions for the PDF reader backend.

The current focus is:
- document upload
- ingestion job creation
- extraction status tracking
- frontend notification through Server-Sent Events (SSE)

## Core Principles

- The API returns quickly after upload metadata is persisted.
- Extraction runs asynchronously after the upload request completes.
- PostgreSQL is the source of truth for document and job state.
- SSE is a notification channel, not the source of truth.

## Upload Endpoint

### Route

`POST /documents/upload`

### Request

Content type:
- `multipart/form-data`

Fields:
- `file`: uploaded PDF

### Initial validation

- file must be present
- file must not be empty
- file content type should be `application/pdf`

### Response

```json
{
  "document_id": "uuid",
  "document_version_id": "uuid",
  "ingestion_job_id": "uuid",
  "extraction_status": "pending"
}
```

### Upload flow

1. Accept the uploaded file.
2. Validate basic file constraints.
3. Save the raw file to local storage.
4. Compute the file SHA-256 checksum.
5. Create a `documents` row.
6. Create a `document_versions` row with `extraction_status = "pending"`.
7. Create an `ingestion_jobs` row with `job_type = "extract_text"` and `status = "pending"`.
8. Enqueue extraction work.
9. Return the response immediately.

## Local Storage

The first implementation uses local filesystem storage.

Suggested path shape:

`storage/documents/<document_version_id>.pdf`

Notes:
- do not rely on the original filename for the stored path
- UUID-based file naming avoids collisions and unsafe filenames

## Extraction Status Lifecycle

### document_versions.extraction_status

- `pending`
- `running`
- `succeeded`
- `failed`

### ingestion_jobs.status

- `pending`
- `running`
- `succeeded`
- `failed`

## SSE Endpoint

### Route

`GET /document-versions/{document_version_id}/events`

### Purpose

The frontend subscribes to this endpoint after upload so it can be notified when extraction status changes.

### Response type

- `text/event-stream`

### Example events

```text
event: extraction_status
data: {"document_version_id":"...","status":"running"}
```

```text
event: extraction_status
data: {"document_version_id":"...","status":"succeeded","page_count":12}
```

```text
event: extraction_status
data: {"document_version_id":"...","status":"failed","error":"text extraction failed"}
```

## Backend Event Flow

1. Upload API enqueues an extraction job.
2. A worker consumes the job.
3. The worker updates `document_versions.extraction_status` to `running`.
4. The worker publishes an extraction status event.
5. The worker completes extraction.
6. The worker updates:
   - `document_versions.extraction_status`
   - `ingestion_jobs.status`
   - optionally `page_count`
   - optionally `error_message`
7. The worker publishes the final extraction event.
8. The SSE endpoint forwards the event to connected frontend clients.

## State Ownership

- PostgreSQL stores the authoritative current state.
- SSE provides near-real-time notification to the frontend.
- If an SSE event is missed, the database remains the recovery source of truth.

## Deferred Details

The following are intentionally not finalized yet:
- exact queue implementation
- exact worker implementation
- retry policy
- reconnect behavior for SSE clients
- whether a separate status endpoint should exist alongside SSE
