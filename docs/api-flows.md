# API Flows

## Purpose

This document captures the current API boundary and async pipeline decisions for the PDF reader backend.

The current focus is:
- one temporary PDF chat session per user
- staged ingestion jobs behind the session
- session status tracking
- frontend notification through Server-Sent Events (SSE)
- semantic retrieval
- grounded document answers
- session cleanup after the user ends the session or it expires

## Core Principles

- The upload API returns quickly after metadata is persisted.
- Ingestion runs asynchronously after the upload request completes.
- PostgreSQL is the source of truth for document and job state.
- SSE is a notification channel, not the source of truth.
- `session_id` is the main frontend-facing identifier for an active chat session.
- `document_version_id` is an internal pipeline identifier behind the session.
- `ingestion_job_id` identifies one stage job, not the whole pipeline.
- session artifacts are temporary and are deleted when the session ends or expires.

## Sync vs Async Boundary

### Synchronous work

The following work happens inside `POST /sessions`:

1. Accept the uploaded file.
2. Validate basic file constraints.
3. Enforce the one-active-session-per-user rule.
4. Generate IDs for the document, document version, session, and first ingestion job.
4. Save the raw PDF to local storage.
5. Compute the file checksum.
6. Create the `documents` row.
7. Create the `document_versions` row with `pipeline_status = "pending"`.
8. Create the `sessions` row with `status = "ingesting"`.
9. Create the initial `ingestion_jobs` row with `job_type = "extract_text"` and `status = "pending"`.
10. Enqueue extraction work.
11. Return the session response immediately.

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

## Session Start Endpoint

### Route

`POST /sessions`

### Request

Content type:
- `multipart/form-data`

Fields:
- `file`: uploaded PDF

### Initial validation

- file must be present
- file must not be empty
- file content type should be `application/pdf`
- file must not exceed `MAX_UPLOAD_SIZE_BYTES`

### Response

```json
{
  "session_id": "uuid",
  "document_version_id": "uuid",
  "status": "ingesting"
}
```

### Session start flow

1. Accept the uploaded file.
2. Validate basic file constraints.
3. Expire any stale session for the same user.
4. Reject the request if the user already has an active session.
5. Save the raw file to storage.
6. Create the temporary document rows and ingestion job rows.
7. Create the session row.
8. Enqueue extraction work.
9. Return the response immediately.

## Local Storage

The current implementation uses local filesystem storage.

Suggested path shape:

`local://documents/<document_version_id>.pdf`

Notes:
- do not rely on the original filename for the stored key
- UUID-based file naming avoids collisions and unsafe filenames
- the database stores an opaque storage URI, not a raw local filesystem path

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

A session is considered ready for downstream interaction when:

- `sessions.status = "ready"`

The frontend should use session status as the main readiness condition.

## SSE Endpoint

### Route

`GET /sessions/{session_id}/events`

### Purpose

The frontend subscribes to this endpoint after session creation so it can be notified when ingestion status changes.

### Response type

- `text/event-stream`

### Frontend contract

- The frontend should treat `session_id` as the stable session identifier.
- The frontend should treat `status` as the session status.
- The frontend may inspect `pipeline_status` for ingestion-stage detail.
- The frontend should not treat `ingestion_job_id` as a stable pipeline identifier because it changes across stages.
- Terminal frontend statuses are:
  - `ready`
  - `failed`

### Example events

```text
event: session_status
data: {"session_id":"...","document_version_id":"...","status":"ingesting","pipeline_status":"extracting"}
```

```text
event: session_status
data: {"session_id":"...","document_version_id":"...","status":"ingesting","pipeline_status":"chunking","page_count":12}
```

```text
event: session_status
data: {"session_id":"...","document_version_id":"...","status":"ready","pipeline_status":"ready","page_count":12}
```

```text
event: session_status
data: {"session_id":"...","document_version_id":"...","status":"failed","pipeline_status":"failed","error_message":"text extraction failed"}
```

### Response shape

```json
{
  "document_version_id": "uuid",
  "query": "What is the cumulative GPA?",
  "matches": [
    {
      "chunk_id": "uuid",
      "chunk_index": 4,
      "start_page_number": 2,
      "end_page_number": 2,
      "text": "...",
      "distance": 0.1234
    }
  ]
}
```

### Notes

- Search is currently scoped to one `document_version_id`.
- Lower `distance` means a stronger semantic match.
- The current implementation uses cosine distance over stored pgvector embeddings.

## Ask Endpoint

### Route

`POST /sessions/{session_id}/messages`

### Purpose

This endpoint performs the grounded answer flow inside the user's single active session:

1. retrieve top semantic chunk matches
2. send the question and retrieved context to Gemini
3. return an answer plus supporting citations

### Request shape

```json
{
  "question": "What is the cumulative GPA?",
  "top_k": 3
}
```

### Response shape

```json
{
  "session_id": "uuid",
  "document_version_id": "uuid",
  "status": "ready",
  "user_message": { "...": "..." },
  "assistant_message": { "...": "..." },
  "matches": [ { "...": "..." } ]
}
```

### Weak-context behavior

- If no strong enough retrieval evidence is found, the endpoint returns:
  - `answer_status = "insufficient_context"`
  - a no-answer style fallback instead of forcing a speculative answer
- The current heuristic uses the best match distance against a configurable threshold.

## Session End Endpoint

### Route

`POST /sessions/{session_id}/end`

### Behavior

- deletes session messages
- deletes ingestion artifacts
- deletes document metadata for the session
- deletes the source PDF if it is still present
- after this, the session no longer exists

## Backend Event Flow

1. Session start API enqueues an `extract_text` job.
2. A worker consumes the job.
3. The worker updates `document_versions.pipeline_status` to `extracting` and `sessions.status` to `ingesting`.
4. The worker publishes a session status event.
5. If extraction succeeds, the worker creates and enqueues `chunk_text`.
6. The worker updates `document_versions.pipeline_status` to `chunking`.
7. If chunking succeeds, the worker creates and enqueues `build_embeddings`.
8. The worker updates `document_versions.pipeline_status` to `embedding`.
9. If embeddings succeed, the worker updates `document_versions.pipeline_status` to `ready` and `sessions.status` to `ready`.
10. On any stage failure, the worker updates `document_versions.pipeline_status` to `failed` and `sessions.status` to `failed`.
11. On worker startup, any orphaned `running` jobs left behind by a previous worker process are failed and requeued when retry budget remains.
12. The SSE endpoint forwards matching events to connected frontend clients.

## State Ownership

- PostgreSQL stores the authoritative current state for active sessions.
- SSE provides near-real-time notification to the frontend.
- If an SSE event is missed, the database remains the recovery source of truth.

## Re-run and Retry Rules

- Each stage is idempotent at the artifact level while the session remains active.
- Re-running `extract_text` replaces downstream pages, chunks, and embeddings for that document version.
- Re-running `chunk_text` replaces downstream chunks and embeddings for that document version.
- Re-running `build_embeddings` replaces embeddings for the existing chunks of that document version.
- Retry attempts create a new `ingestion_jobs` row with an incremented `attempt_count`.
- Automatic retries are only used for retryable runtime failures, not for known terminal states such as unreadable extraction output.
- Worker startup performs a recovery sweep for orphaned `running` jobs so deploys or crashes do not leave documents stuck forever.
- Sessions expire after inactivity and their artifacts are deleted.

## Deferred Details

The following are intentionally not finalized yet:
- reconnect behavior for SSE clients
- whether a separate status endpoint should exist alongside SSE
- richer backoff and retry timing
- stronger stuck-job detection
