# Schema Notes

## Purpose

This document captures the current persistence model for the PDF reader backend.

The goal of the current schema is to support:
- temporary session-owned document identity
- uploaded file traceability
- staged ingestion jobs
- extracted page persistence
- chunk persistence
- embedding persistence
- temporary sessions and session messages

## Shared Decisions

- Use `UUID` primary keys for all core tables.
- Use `TIMESTAMP WITH TIME ZONE` for all timestamps.
- Use plain string columns for statuses and job types for now.
- Add obvious indexes and a few uniqueness constraints where stage outputs must be stable.

## documents

Purpose: logical document identity.

Columns:
- `id`: `UUID`, primary key, not null
- `title`: `TEXT`, not null
- `source_type`: `TEXT`, not null
- `created_at`: `TIMESTAMPTZ`, not null
- `updated_at`: `TIMESTAMPTZ`, not null

Notes:
- `title` can default from the first uploaded filename.
- `source_type` can start with values like `upload`.
- This table should stay small and avoid file-specific metadata.

## document_versions

Purpose: exact uploaded file plus file-level metadata and overall pipeline state.

Columns:
- `id`: `UUID`, primary key, not null
- `document_id`: `UUID`, foreign key to `documents.id`, not null
- `original_filename`: `TEXT`, not null
- `storage_path`: `TEXT`, not null
- `sha256`: `TEXT`, not null
- `file_size_bytes`: `BIGINT`, not null
- `mime_type`: `TEXT`, not null
- `page_count`: `INTEGER`, null
- `pipeline_status`: `TEXT`, not null
- `created_at`: `TIMESTAMPTZ`, not null
- `updated_at`: `TIMESTAMPTZ`, not null

Indexes:
- index on `document_id`
- index on `sha256`

Suggested `pipeline_status` values:
- `pending`
- `extracting`
- `chunking`
- `embedding`
- `ready`
- `failed`

Notes:
- `page_count` is nullable because it may only be known after PDF inspection or extraction.
- `sha256` is indexed for duplicate detection and file identity checks.
- `pipeline_status` is the frontend-facing readiness signal.
- File-specific metadata belongs here, not on `documents`.
- `storage_path` should be treated as an opaque storage URI such as `local://documents/<uuid>.pdf` rather than a literal local path.

## document_pages

Purpose: extracted text persisted one page at a time.

Columns:
- `id`: `UUID`, primary key, not null
- `document_version_id`: `UUID`, foreign key to `document_versions.id`, not null
- `page_number`: `INTEGER`, not null
- `text`: `TEXT`, not null
- `char_count`: `INTEGER`, not null
- `created_at`: `TIMESTAMPTZ`, not null

Indexes / constraints:
- index on `document_version_id`
- unique constraint on `(document_version_id, page_number)`

Notes:
- page persistence preserves extraction output for debugging, chunking, and citation tracing.

## document_chunks

Purpose: retrieval-ready text chunks derived from extracted pages.

Columns:
- `id`: `UUID`, primary key, not null
- `document_version_id`: `UUID`, foreign key to `document_versions.id`, not null
- `chunk_index`: `INTEGER`, not null
- `start_page_number`: `INTEGER`, not null
- `end_page_number`: `INTEGER`, not null
- `text`: `TEXT`, not null
- `char_count`: `INTEGER`, not null
- `created_at`: `TIMESTAMPTZ`, not null
- `updated_at`: `TIMESTAMPTZ`, not null

Indexes / constraints:
- index on `document_version_id`
- unique constraint on `(document_version_id, chunk_index)`

Notes:
- chunks are paragraph-first and can span page boundaries.
- page ranges support traceability back to the source PDF.

## chunk_embeddings

Purpose: embeddings generated for document chunks.

Columns:
- `id`: `UUID`, primary key, not null
- `document_chunk_id`: `UUID`, foreign key to `document_chunks.id`, not null
- `embedding_model`: `TEXT`, not null
- `dimensions`: `INTEGER`, not null
- `vector`: `VECTOR(768)`, not null
- `created_at`: `TIMESTAMPTZ`, not null
- `updated_at`: `TIMESTAMPTZ`, not null

Indexes / constraints:
- index on `document_chunk_id`
- HNSW vector index on `vector` using cosine operations
- unique constraint on `(document_chunk_id, embedding_model)`

Notes:
- a separate embeddings table allows re-embedding chunks with different models later.
- embeddings are stored with the PostgreSQL `pgvector` extension.
- the current dimensionality is 768 for `gemini-embedding-2`.
- nearest-neighbor retrieval is now backed by an HNSW index for cosine-distance search.

## ingestion_jobs

Purpose: processing attempts and stage history for a specific document version.

Columns:
- `id`: `UUID`, primary key, not null
- `document_version_id`: `UUID`, foreign key to `document_versions.id`, not null
- `job_type`: `TEXT`, not null
- `status`: `TEXT`, not null
- `attempt_count`: `INTEGER`, not null
- `error_message`: `TEXT`, null
- `started_at`: `TIMESTAMPTZ`, null
- `finished_at`: `TIMESTAMPTZ`, null
- `created_at`: `TIMESTAMPTZ`, not null
- `updated_at`: `TIMESTAMPTZ`, not null

Indexes:
- index on `document_version_id`
- optional composite index on `(document_version_id, job_type, created_at)`

Suggested `job_type` values:
- `extract_text`
- `chunk_text`
- `build_embeddings`

Suggested `status` values:
- `pending`
- `running`
- `succeeded`
- `failed`

Notes:
- this table is append-mostly.
- each row represents one stage attempt, not one permanent pipeline slot.
- a row may be updated during its own lifecycle, but retries should create a new row.
- retries increment `attempt_count` on a new row for the same `job_type`.
- the frontend should not treat `ingestion_job_id` as the stable document lifecycle identifier.

## sessions

Purpose: one temporary active-or-failed PDF chat session for one user.

Columns:
- `id`: `UUID`, primary key, not null
- `owner_user_id`: `UUID`, foreign key to `users.id`, not null
- `document_version_id`: `UUID`, foreign key to `document_versions.id`, not null
- `status`: `TEXT`, not null
- `title`: `TEXT`, not null
- `failure_message`: `TEXT`, null
- `last_activity_at`: `TIMESTAMPTZ`, not null
- `created_at`: `TIMESTAMPTZ`, not null
- `updated_at`: `TIMESTAMPTZ`, not null

Indexes:
- index on `owner_user_id`
- unique index on `document_version_id`

Notes:
- one user should only have one active session at a time.
- one session belongs to exactly one user and one document version.
- sessions are temporary and are deleted along with their artifacts when they end or expire.

## session_messages

Purpose: persisted user and assistant turns within one temporary session.

Columns:
- `id`: `UUID`, primary key, not null
- `session_id`: `UUID`, foreign key to `sessions.id`, not null
- `role`: `TEXT`, not null
- `content`: `TEXT`, not null
- `answer_status`: `TEXT`, null
- `citations_json`: `JSON`, null
- `created_at`: `TIMESTAMPTZ`, not null
- `updated_at`: `TIMESTAMPTZ`, not null

Indexes:
- index on `session_id`

Suggested `role` values:
- `user`
- `assistant`

Suggested `answer_status` values:
- `answered`
- `insufficient_context`

Notes:
- user messages have `answer_status = null` and `citations_json = null`.
- assistant messages can persist citations from the retrieval-backed answer path.
- messages are temporary and deleted when the session ends or expires.

## legacy_conversations

The older `conversations` and `conversation_messages` tables may still exist in the schema during the transition, but the current public product flow is session-based, not conversation-library-based.

## Relationships

- `documents 1 -> many document_versions`
- `users 1 -> many documents`
- `users 1 -> many api_keys`
- `users 1 -> many sessions`
- `document_versions 1 -> many document_pages`
- `document_versions 1 -> many document_chunks`
- `document_versions 1 -> 1 sessions`
- `document_versions 1 -> many ingestion_jobs`
- `document_chunks 1 -> many chunk_embeddings`
- `sessions 1 -> many session_messages`

## Nullability Summary

Nullable:
- `document_versions.page_count`
- `sessions.failure_message`
- `session_messages.answer_status`
- `session_messages.citations_json`
- `ingestion_jobs.error_message`
- `ingestion_jobs.started_at`
- `ingestion_jobs.finished_at`

Everything else in this current pass is not null.

## Deferred for Later

The following are intentionally out of scope for this schema pass:
- OCR-specific fields
- richer extraction quality metrics
- business constraints that depend on unresolved product behavior

## Runtime Guardrails

The current temporary-session backend expects the following operational limits from configuration:

- `MAX_UPLOAD_SIZE_BYTES`
- `MAX_PDF_PAGES`
- `MAX_SESSION_QUESTION_CHARS`
- `SESSION_INACTIVITY_TIMEOUT_MINUTES`
- `SESSION_CLEANUP_INTERVAL_SECONDS`

These are runtime controls rather than schema fields, but they are part of the current product behavior.
