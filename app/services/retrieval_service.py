"""Semantic retrieval service for embedded document chunks."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.db.models import ChunkEmbedding, DocumentChunk, DocumentVersion
from app.schemas.document import DocumentSearchMatchResponse, DocumentSearchResponse
from app.services.embedding_service import build_query_embedding


def search_document_chunks(db, document_version_id, query: str, top_k: int) -> DocumentSearchResponse:
    """Embed a query, search one document version's chunks, and return the best matches."""

    document_version = db.query(DocumentVersion).filter(DocumentVersion.id == document_version_id).first()
    if document_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found.")
    if document_version.pipeline_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document version is not ready for retrieval.",
        )

    query_vector = build_query_embedding(query)
    rows = _search_document_chunk_rows(db, document_version.id, query_vector, top_k)
    matches = [
        DocumentSearchMatchResponse(
            chunk_id=row.chunk_id,
            chunk_index=row.chunk_index,
            start_page_number=row.start_page_number,
            end_page_number=row.end_page_number,
            text=row.text,
            distance=float(row.distance),
        )
        for row in rows
    ]

    return DocumentSearchResponse(
        document_version_id=document_version.id,
        query=query,
        matches=matches,
    )


def _search_document_chunk_rows(db, document_version_id, query_vector: list[float], top_k: int):
    """Run the pgvector similarity query for one document version."""

    distance = ChunkEmbedding.vector.cosine_distance(query_vector)
    return (
        db.query(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.chunk_index.label("chunk_index"),
            DocumentChunk.start_page_number.label("start_page_number"),
            DocumentChunk.end_page_number.label("end_page_number"),
            DocumentChunk.text.label("text"),
            distance.label("distance"),
        )
        .join(ChunkEmbedding, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
        .filter(DocumentChunk.document_version_id == document_version_id)
        .order_by(distance.asc(), DocumentChunk.chunk_index.asc())
        .limit(top_k)
        .all()
    )
