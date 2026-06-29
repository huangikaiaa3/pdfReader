from __future__ import annotations

from uuid import uuid4

from app.api.routes import documents as document_routes
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
        lambda db, document_version_id, query, top_k: search_response,
    )
    monkeypatch.setattr(
        qa_service,
        "answer_question_with_context",
        lambda question, matches: "The cumulative GPA is 3.582.",
    )

    response = qa_service.ask_document_question(
        db=None,
        document_version_id=document_version_id,
        question="What is the cumulative GPA?",
        top_k=2,
    )

    assert response.document_version_id == document_version_id
    assert response.question == "What is the cumulative GPA?"
    assert response.answer == "The cumulative GPA is 3.582."
    assert response.matches == matches


def test_ask_document_version_route_returns_answer_payload(client, monkeypatch):
    document_version_id = uuid4()
    matches = [
        {
            "chunk_id": str(uuid4()),
            "chunk_index": 0,
            "start_page_number": 2,
            "end_page_number": 2,
            "text": "Cumulative GPA: 3.582",
            "distance": 0.08,
        }
    ]

    monkeypatch.setattr(
        document_routes,
        "ask_document_question",
        lambda db, document_version_id, question, top_k: {
            "document_version_id": str(document_version_id),
            "question": question,
            "answer": "The cumulative GPA is 3.582.",
            "matches": matches,
        },
    )

    response = client.post(
        f"/document-versions/{document_version_id}/ask",
        json={"question": "What is the cumulative GPA?", "top_k": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_version_id"] == str(document_version_id)
    assert payload["question"] == "What is the cumulative GPA?"
    assert payload["answer"] == "The cumulative GPA is 3.582."
    assert len(payload["matches"]) == 1
    assert payload["matches"][0]["distance"] == 0.08
