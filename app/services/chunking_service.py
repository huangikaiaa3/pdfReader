"""Paragraph-first chunking helpers for extracted document text."""

from __future__ import annotations

import re

from app.db.models import DocumentPage


def split_into_paragraph_units(document_pages: list[DocumentPage]) -> list[dict]:
    """Flatten ordered page text into paragraph units tagged with page numbers."""

    paragraph_units: list[dict] = []
    for page in document_pages:
        blocks = re.split(r"\n\s*\n", page.text)
        for block in blocks:
            paragraph_text = block.strip()
            if paragraph_text:
                paragraph_units.append({"text": paragraph_text, "page_number": page.page_number})
    return paragraph_units


def split_oversized_paragraph(paragraph_text: str, page_number: int, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """Split a single oversized paragraph into overlapping chunk-sized pieces."""

    parts: list[dict] = []
    step = chunk_size - chunk_overlap
    start = 0

    while start < len(paragraph_text):
        end = start + chunk_size
        piece = paragraph_text[start:end].strip()
        if piece:
            parts.append({"text": piece, "page_number": page_number})
        if end >= len(paragraph_text):
            break
        start += step

    return parts


def make_chunk(units: list[dict], chunk_index: int) -> dict:
    """Build one persisted chunk payload from paragraph units."""

    text = "\n\n".join(unit["text"] for unit in units).strip()
    return {
        "chunk_index": chunk_index,
        "start_page_number": units[0]["page_number"],
        "end_page_number": units[-1]["page_number"],
        "text": text,
        "char_count": len(text),
    }


def build_chunks_from_paragraph_units(paragraph_units: list[dict], chunk_size: int, chunk_overlap: int) -> list[dict]:
    """Assemble paragraph units into chunks with overlap fallback for large blocks."""

    chunks: list[dict] = []
    current_units: list[dict] = []
    current_length = 0
    chunk_index = 0

    for unit in paragraph_units:
        paragraph_text = unit["text"]
        page_number = unit["page_number"]

        if len(paragraph_text) > chunk_size:
            if current_units:
                chunks.append(make_chunk(current_units, chunk_index))
                chunk_index += 1
                current_units = []
                current_length = 0

            for part in split_oversized_paragraph(paragraph_text, page_number, chunk_size, chunk_overlap):
                chunks.append(
                    {
                        "chunk_index": chunk_index,
                        "start_page_number": part["page_number"],
                        "end_page_number": part["page_number"],
                        "text": part["text"],
                        "char_count": len(part["text"]),
                    }
                )
                chunk_index += 1
            continue

        added_length = len(paragraph_text) if not current_units else len(paragraph_text) + 2
        if current_length + added_length <= chunk_size:
            current_units.append(unit)
            current_length += added_length
            continue

        chunks.append(make_chunk(current_units, chunk_index))
        chunk_index += 1
        current_units = [unit]
        current_length = len(paragraph_text)

    if current_units:
        chunks.append(make_chunk(current_units, chunk_index))

    return chunks


def build_document_chunks(document_pages: list[DocumentPage], chunk_size: int = 1200, chunk_overlap: int = 200) -> list[dict]:
    """Generate persisted chunk payloads from extracted document pages."""

    paragraph_units = split_into_paragraph_units(document_pages)
    if not paragraph_units:
        return []
    return build_chunks_from_paragraph_units(paragraph_units, chunk_size, chunk_overlap)
