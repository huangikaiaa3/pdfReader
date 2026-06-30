from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.schemas.document import DocumentSearchMatchResponse, DocumentSearchResponse
from app.services import qa_service


def _build_match(chunk_index: int, text: str, distance: float) -> DocumentSearchMatchResponse:
    return DocumentSearchMatchResponse(
        chunk_id=uuid4(),
        chunk_index=chunk_index,
        start_page_number=chunk_index + 1,
        end_page_number=chunk_index + 1,
        text=text,
        distance=distance,
    )


def test_ask_document_question_combines_retrieval_and_generation(monkeypatch):
    document_version_id = uuid4()
    current_user = SimpleNamespace(id=uuid4())
    matches = [
        _build_match(chunk_index=0, text="Cumulative GPA: 3.582", distance=0.10),
        _build_match(chunk_index=1, text="Master of Science", distance=0.24),
    ]
    search_response = DocumentSearchResponse(
        document_version_id=document_version_id,
        query="What is the cumulative GPA?",
        matches=matches,
    )

    monkeypatch.setattr(
        qa_service,
        "search_document_chunks",
        lambda db, document_version_id, query, top_k, current_user: search_response,
    )
    monkeypatch.setattr(
        qa_service,
        "answer_question_with_context",
        lambda question, matches: "The cumulative GPA is 3.582.",
    )
    monkeypatch.setattr(
        qa_service,
        "get_settings",
        lambda: SimpleNamespace(answer_citation_count=2, retrieval_weak_match_max_distance=0.4),
    )

    response = qa_service.ask_document_question(
        db=None,
        document_version_id=document_version_id,
        question="What is the cumulative GPA?",
        top_k=2,
        current_user=current_user,
    )

    assert response.document_version_id == document_version_id
    assert response.question == "What is the cumulative GPA?"
    assert response.answer_status == "answered"
    assert response.answer == "The cumulative GPA is 3.582."
    assert len(response.citations) == 2
    assert response.citations[0].chunk_id == matches[0].chunk_id
    assert response.matches == matches



def test_ask_document_question_returns_insufficient_context_for_weak_matches(monkeypatch):
    document_version_id = uuid4()
    current_user = SimpleNamespace(id=uuid4())
    weak_matches = [
        _build_match(chunk_index=0, text="General grading policy", distance=0.62),
        _build_match(chunk_index=1, text="Administrative transcript footer", distance=0.67),
    ]
    search_response = DocumentSearchResponse(
        document_version_id=document_version_id,
        query="What is the advisor email address?",
        matches=weak_matches,
    )

    monkeypatch.setattr(
        qa_service,
        "search_document_chunks",
        lambda db, document_version_id, query, top_k, current_user: search_response,
    )
    monkeypatch.setattr(
        qa_service,
        "get_settings",
        lambda: SimpleNamespace(answer_citation_count=2, retrieval_weak_match_max_distance=0.4),
    )

    response = qa_service.ask_document_question(
        db=None,
        document_version_id=document_version_id,
        question="What is the advisor email address?",
        top_k=2,
        current_user=current_user,
    )

    assert response.document_version_id == document_version_id
    assert response.answer_status == "insufficient_context"
    assert response.answer == "I could not find enough support in the document to answer that question."
    assert response.citations == []
    assert response.matches == weak_matches


def test_ask_document_question_marks_generated_no_answer_as_insufficient_context(monkeypatch):
    document_version_id = uuid4()
    current_user = SimpleNamespace(id=uuid4())
    matches = [
        _build_match(chunk_index=0, text="Registrar office email is listed here.", distance=0.31),
        _build_match(chunk_index=1, text="Transcript authenticity language.", distance=0.37),
    ]
    search_response = DocumentSearchResponse(
        document_version_id=document_version_id,
        query="What is the advisor email address?",
        matches=matches,
    )

    monkeypatch.setattr(
        qa_service,
        "search_document_chunks",
        lambda db, document_version_id, query, top_k, current_user: search_response,
    )
    monkeypatch.setattr(
        qa_service,
        "answer_question_with_context",
        lambda question, matches: "I could not find the advisor email address in the document.",
    )
    monkeypatch.setattr(
        qa_service,
        "get_settings",
        lambda: SimpleNamespace(answer_citation_count=2, retrieval_weak_match_max_distance=0.4),
    )

    response = qa_service.ask_document_question(
        db=None,
        document_version_id=document_version_id,
        question="What is the advisor email address?",
        top_k=2,
        current_user=current_user,
    )

    assert response.answer_status == "insufficient_context"
    assert response.answer == "I could not find the advisor email address in the document."
    assert response.citations == []


def test_ask_document_question_allows_summary_style_question_with_weaker_match(monkeypatch):
    document_version_id = uuid4()
    current_user = SimpleNamespace(id=uuid4())
    matches = [
        _build_match(chunk_index=0, text="This is a proof of good standing during tenancy for I-Kai Huang at 485 Marin Blvd.", distance=0.58),
        _build_match(chunk_index=1, text="Authorized agent signature block.", distance=0.66),
    ]
    search_response = DocumentSearchResponse(
        document_version_id=document_version_id,
        query="What is this document about?",
        matches=matches,
    )

    monkeypatch.setattr(
        qa_service,
        "search_document_chunks",
        lambda db, document_version_id, query, top_k, current_user: search_response,
    )
    monkeypatch.setattr(
        qa_service,
        "answer_question_with_context",
        lambda question, matches: "This document is a proof of good standing during tenancy for I-Kai Huang.",
    )
    monkeypatch.setattr(
        qa_service,
        "get_settings",
        lambda: SimpleNamespace(answer_citation_count=2, retrieval_weak_match_max_distance=0.4),
    )

    response = qa_service.ask_document_question(
        db=None,
        document_version_id=document_version_id,
        question="What is this document about?",
        top_k=2,
        current_user=current_user,
    )

    assert response.answer_status == "answered"
    assert response.answer == "This document is a proof of good standing during tenancy for I-Kai Huang."
    assert len(response.citations) == 2
