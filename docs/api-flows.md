# API Flows

## Purpose

This document captures the current API boundary and async pipeline decisions for the PDF reader backend.

The current focus is:
- document upload
- staged ingestion jobs
- pipeline status tracking
- frontend notification through Server-Sent Events (SSE)

## Core Principles

- The upload API returns quickly after metadata is persisted.
- Ingestion runs asynchronously after the upload request completes.
- PostgreSQL is the source of truth for document and job state.
- SSE is a notification channel, not the source of truth.
- `document_version_id` is the stable identifier for one uploaded file version.
- `ingestion_job_id` identifies one stage job, not the whole pipeline.

## Sync vs Async Boundary

### Synchronous work

The following work happens inside `POST /documents/upload`:

1. Accept the uploaded file.
2. Validate basic file constraints.
3. Generate IDs for the document, document version, and first ingestion job.
4. Save the raw PDF to local storage.
5. Compute the file checksum.
6. Create the `documents` row.
7. Create the `document_versions` row with `pipeline_status = "pending"`.
8. Create the initial `ingestion_jobs` row with `job_type = "extract_text"` and `status = "pending"`.
9. Enqueue extraction work.
10. Return the upload response immediately.

### Asynchronous work

The following work happens after the upload response has already been returned:

1. A worker receives the `extract_text` job.
2. The worker extracts text from the stored PDF.
3. If extraction succeeds, the worker creates a `chunk_text` job.
4. The worker chunks the extracted text.
5. If chunking succeeds, the worker creates a `build_embeddings` job.
6. The worker generates embeddings for the chunks.
7. The worker updates `document_versions.pipeline_status` as the document moves through the pipeline.
8. The worker emits SSE notifications for frontend clients.

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
  "pipeline_status": "pending"
}
```

### Upload flow

1. Accept the uploaded file.
2. Validate basic file constraints.
3. Save the raw file to local storage.
4. Compute the file SHA-256 checksum.
5. Create a `documents` row.
6. Create a `document_versions` row with `pipeline_status = "pending"`.
7. Create an `ingestion_jobs` row with `job_type = "extract_text"` and `status = "pending"`.
8. Enqueue extraction work.
9. Return the response immediately.

### Duplicate upload behavior

- Upload deduplication is checksum-based.
- If the same PDF bytes are uploaded again, the API returns the existing `document_version_id`.
- The API does not create a second stored file or a duplicate pipeline for the same checksum.

## Local Storage

The current implementation uses local filesystem storage.

Suggested path shape:

`storage/documents/<document_version_id>.pdf`

Notes:
- do not rely on the original filename for the stored path
- UUID-based file naming avoids collisions and unsafe filenames

## Pipeline Status Lifecycle

### document_versions.pipeline_status

- `pending`
- `extracting`
- `chunking`
- `embedding`
- `ready`
- `failed`

### ingestion_jobs.status

- `pending`
- `running`
- `succeeded`
- `failed`

### ingestion_jobs.job_type

- `extract_text`
- `chunk_text`
- `build_embeddings`

### State transitions

#### document_versions.pipeline_status

- `pending -> extracting -> chunking -> embedding -> ready`
- `pending -> extracting -> failed`
- `pending -> extracting -> chunking -> failed`
- `pending -> extracting -> chunking -> embedding -> failed`

#### ingestion_jobs.status

- `pending -> running -> succeeded`
- `pending -> running -> failed`

## Ready for Interaction

A document version is considered ready for downstream interaction when:

- `document_versions.pipeline_status = "ready"`

This is the main readiness condition the frontend should use before enabling chat or document interaction features.

## SSE Endpoint

### Route

`GET /document-versions/{document_version_id}/events`

### Purpose

The frontend subscribes to this endpoint after upload so it can be notified when pipeline status changes.

### Response type

- `text/event-stream`

### Frontend contract

- The frontend should treat `document_version_id` as the stable pipeline identifier.
- The frontend should treat `status` as `document_versions.pipeline_status`.
- The frontend should not treat `ingestion_job_id` as a stable pipeline identifier because it changes across stages.
- Terminal frontend statuses are:
  - `ready`
  - `failed`

### Example events

```text
event: pipeline_status
data: {"document_version_id":"...","status":"extracting"}
```

```text
event: pipeline_status
data: {"document_version_id":"...","status":"chunking","page_count":12}
```

```text
event: pipeline_status
data: {"document_version_id":"...","status":"embedding","page_count":12}
```

```text
event: pipeline_status
data: {"document_version_id":"...","status":"ready","page_count":12}
```

```text
event: pipeline_status
data: {"document_version_id":"...","status":"failed","error_message":"text extraction failed"}
```

## Recovery Endpoint

### Route

`POST /document-versions/{document_version_id}/recover`

### Purpose

This endpoint requeues the next missing ingestion stage based on persisted database state.

### Behavior

- If no extracted pages exist, it enqueues `extract_text`.
- If pages exist but no chunks exist, it enqueues `chunk_text`.
- If chunks exist but embeddings are missing, it enqueues `build_embeddings`.
- If the document version is already complete, it returns a no-op response.
- If an active pending or running job already exists for the required stage, it returns that job instead of creating another one.

### Response shape

```json
{
  "document_version_id": "uuid",
  "ingestion_job_id": "uuid-or-null",
  "pipeline_status": "embedding",
  "message": "Enqueued recovery job for stage 'build_embeddings'."
}
```

## Backend Event Flow

1. Upload API enqueues an `extract_text` job.
2. A worker consumes the job.
3. The worker updates `document_versions.pipeline_status` to `extracting`.
4. The worker publishes a pipeline status event.
5. If extraction succeeds, the worker creates and enqueues `chunk_text`.
6. The worker updates `document_versions.pipeline_status` to `chunking`.
7. If chunking succeeds, the worker creates and enqueues `build_embeddings`.
8. The worker updates `document_versions.pipeline_status` to `embedding`.
9. If embeddings succeed, the worker updates `document_versions.pipeline_status` to `ready`.
10. On any stage failure, the worker updates `document_versions.pipeline_status` to `failed`.
11. The SSE endpoint forwards matching events to connected frontend clients.

## State Ownership

- PostgreSQL stores the authoritative current state.
- SSE provides near-real-time notification to the frontend.
- If an SSE event is missed, the database remains the recovery source of truth.

## Re-run and Retry Rules

- Each stage is idempotent at the artifact level.
- Re-running `extract_text` replaces downstream pages, chunks, and embeddings for that document version.
- Re-running `chunk_text` replaces downstream chunks and embeddings for that document version.
- Re-running `build_embeddings` replaces embeddings for the existing chunks of that document version.
- Retry attempts create a new `ingestion_jobs` row with an incremented `attempt_count`.
- Automatic retries are only used for retryable runtime failures, not for known terminal states such as unreadable extraction output.

## Deferred Details

The following are intentionally not finalized yet:
- reconnect behavior for SSE clients
- whether a separate status endpoint should exist alongside SSE
- richer backoff and retry timing
- stronger stuck-job detection
