# Schema Notes

## Purpose

This document captures the initial persistence model for the PDF reader backend.

The goal of this first schema pass is to support:
- logical document identity
- uploaded file traceability
- ingestion job tracking

This schema intentionally does not include chunks, embeddings, conversations, or OCR-specific structures yet.

## Shared Decisions

- Use `UUID` primary keys for all core tables.
- Use `TIMESTAMP WITH TIME ZONE` for all timestamps.
- Use plain string columns for statuses and job types for now.
- Add only the most obvious indexes in the first pass.

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

Purpose: exact uploaded file plus file-level metadata.

Columns:
- `id`: `UUID`, primary key, not null
- `document_id`: `UUID`, foreign key to `documents.id`, not null
- `original_filename`: `TEXT`, not null
- `storage_path`: `TEXT`, not null
- `sha256`: `TEXT`, not null
- `file_size_bytes`: `BIGINT`, not null
- `mime_type`: `TEXT`, not null
- `page_count`: `INTEGER`, null
- `extraction_status`: `TEXT`, not null
- `created_at`: `TIMESTAMPTZ`, not null
- `updated_at`: `TIMESTAMPTZ`, not null

Indexes:
- index on `document_id`
- index on `sha256`

Suggested `extraction_status` values:
- `pending`
- `running`
- `succeeded`
- `failed`

Notes:
- `page_count` is nullable because it may only be known after PDF inspection or extraction.
- `sha256` is indexed for duplicate detection and file identity checks.
- File-specific metadata belongs here, not on `documents`.

## ingestion_jobs

Purpose: processing attempts and ingestion history for a specific file version.

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

Suggested `status` values:
- `pending`
- `running`
- `succeeded`
- `failed`

Notes:
- This table is append-mostly.
- Each row represents one job attempt, not one permanent job slot.
- A row may be updated during its own lifecycle, but retries should create a new row.

## Relationships

- `documents 1 -> many document_versions`
- `document_versions 1 -> many ingestion_jobs`

## Nullability Summary

Nullable:
- `document_versions.page_count`
- `ingestion_jobs.error_message`
- `ingestion_jobs.started_at`
- `ingestion_jobs.finished_at`

Everything else in this first pass is not null.

## Deferred for Later

The following are intentionally out of scope for this first persistence pass:
- chunk tables
- embedding or vector fields
- conversation and message tables
- OCR-specific fields
- extraction quality metrics tables
- business constraints that depend on unresolved product behavior
