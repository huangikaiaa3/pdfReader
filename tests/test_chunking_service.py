from app.db.models import DocumentPage
from app.services.chunking_service import build_document_chunks


def test_build_document_chunks_tracks_page_ranges_across_paragraphs():
    pages = [
        DocumentPage(document_version_id="v1", page_number=1, text="Alpha\n\nBeta", char_count=10),
        DocumentPage(document_version_id="v1", page_number=2, text="Gamma", char_count=5),
    ]

    chunks = build_document_chunks(pages, chunk_size=100, chunk_overlap=20)

    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["start_page_number"] == 1
    assert chunks[0]["end_page_number"] == 2
    assert chunks[0]["text"] == "Alpha\n\nBeta\n\nGamma"


def test_build_document_chunks_splits_oversized_paragraph_with_overlap():
    oversized_text = "A" * 18
    pages = [
        DocumentPage(document_version_id="v1", page_number=3, text=oversized_text, char_count=len(oversized_text)),
    ]

    chunks = build_document_chunks(pages, chunk_size=10, chunk_overlap=2)

    assert len(chunks) == 2
    assert chunks[0]["text"] == "A" * 10
    assert chunks[1]["text"] == "A" * 10
    assert chunks[0]["start_page_number"] == 3
    assert chunks[1]["end_page_number"] == 3
