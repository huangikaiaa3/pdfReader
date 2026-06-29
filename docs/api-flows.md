# API Flows

## Purpose

This document captures the current API boundary and async pipeline decisions for the PDF reader backend.

The current focus is:
- document upload
- staged ingestion jobs
- pipeline status tracking
- frontend notification through Server-Sent Events (SSE)
- semantic retrieval
- grounded document answers
- persisted document conversations

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

## Search Endpoint

### Route

`POST /document-versions/{document_version_id}/search`

### Purpose

This endpoint embeds a user query, searches the stored chunk embeddings for one document version, and returns the top matching chunks.

### Request shape

```json
{
  "query": "What is the cumulative GPA?",
  "top_k": 5
}
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

`POST /document-versions/{document_version_id}/ask`

### Purpose

This endpoint performs the first grounded RAG answer flow:

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
  "document_version_id": "uuid",
  "question": "What is the cumulative GPA?",
  "answer_status": "answered",
  "answer": "Cumulative GPA: 3.582",
  "citations": [
    {
      "chunk_id": "uuid",
      "chunk_index": 4,
      "start_page_number": 2,
      "end_page_number": 2
    }
  ],
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

### Answer status values

- `answered`
- `insufficient_context`

### Weak-context behavior

- If no strong enough retrieval evidence is found, the endpoint returns:
  - `answer_status = "insufficient_context"`
  - a no-answer style fallback instead of forcing a speculative answer
- The current heuristic uses the best match distance against a configurable threshold.

## Conversation Endpoints

### Purpose

These endpoints persist chat state on the backend so the frontend does not have to keep the entire conversation in browser memory only.

### Create conversation

Route:

`POST /conversations`

Request shape:

```json
{
  "document_version_id": "uuid",
  "title": "Optional custom title"
}
```

Behavior:

- verifies the document version belongs to the current user
- requires `document_versions.pipeline_status = "ready"`
- creates a new conversation row with zero messages

### List conversations

Route:

`GET /conversations`

Optional query params:

- `document_version_id`

Behavior:

- returns only conversations owned by the authenticated user
- can be filtered down to one document version

### Get conversation

Route:

`GET /conversations/{conversation_id}`

Behavior:

- returns the persisted conversation with all stored messages
- rejects access to conversations owned by another user

### Append question/answer turn

Route:

`POST /conversations/{conversation_id}/messages`

Request shape:

```json
{
  "question": "What is the cumulative GPA?",
  "top_k": 3
}
```

Behavior:

1. persist the user message
2. run the existing retrieval + grounded answer flow against the conversation's `document_version_id`
3. persist the assistant response with answer status and citations
4. return both newly created message records plus retrieval matches

Notes:

- this keeps the original `/document-versions/{document_version_id}/ask` endpoint available as a stateless primitive
- the conversation route is the stateful wrapper that makes the chat history deployable

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
11. On worker startup, any orphaned `running` jobs left behind by a previous worker process are failed and requeued when retry budget remains.
12. The SSE endpoint forwards matching events to connected frontend clients.

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
- Worker startup performs a recovery sweep for orphaned `running` jobs so deploys or crashes do not leave documents stuck forever.

## Deferred Details

The following are intentionally not finalized yet:
- reconnect behavior for SSE clients
- whether a separate status endpoint should exist alongside SSE
- richer backoff and retry timing
- stronger stuck-job detection
