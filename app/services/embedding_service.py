"""Embedding helpers backed by the Gemini API."""

from __future__ import annotations

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.db.models import DocumentChunk, DocumentVersion


def build_chunk_embedding_payloads(document_version: DocumentVersion, document_chunks: list[DocumentChunk]) -> list[dict]:
    """Generate embedding payloads for one document version's chunks."""

    settings = get_settings()
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=settings.gemini_api_key)
    payloads: list[dict] = []

    for document_chunk in document_chunks:
        result = client.models.embed_content(
            model=settings.embedding_model,
            contents=_prepare_document_content(document_version.original_filename, document_chunk.text),
            config=types.EmbedContentConfig(output_dimensionality=settings.embedding_output_dimensionality),
        )
        [embedding_obj] = result.embeddings
        values = list(embedding_obj.values)
        payloads.append(
            {
                "document_chunk_id": document_chunk.id,
                "embedding_model": settings.embedding_model,
                "dimensions": len(values),
                "vector": values,
            }
        )

    return payloads


def build_query_embedding(query: str) -> list[float]:
    """Generate an embedding vector for a user search query."""

    settings = get_settings()
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=settings.gemini_api_key)
    result = client.models.embed_content(
        model=settings.embedding_model,
        contents=query,
        config=types.EmbedContentConfig(output_dimensionality=settings.embedding_output_dimensionality),
    )
    [embedding_obj] = result.embeddings
    return list(embedding_obj.values)


def _prepare_document_content(title: str, text: str) -> str:
    """Format document text for retrieval-oriented embeddings."""

    normalized_title = title or "none"
    return f"title: {normalized_title} | text: {text}"
