from app.core.config import get_settings
from app.db.models import User
from app.schemas.document import DocumentAskResponse, DocumentCitationResponse
from app.services.retrieval_service import search_document_chunks
from app.services.generation_service import answer_question_with_context


def ask_document_question(db, document_version_id, question: str, top_k: int, current_user: User) -> DocumentAskResponse:
    search_response = search_document_chunks(
        db=db,
        document_version_id=document_version_id,
        query=question,
        top_k=top_k,
        current_user=current_user,
    )

    citations = _build_citations(search_response.matches)
    if not _has_sufficient_context(search_response.matches, question):
        return DocumentAskResponse(
            document_version_id=search_response.document_version_id,
            question=question,
            answer_status="insufficient_context",
            answer="I could not find enough support in the document to answer that question.",
            citations=[],
            matches=search_response.matches,
        )

    answer = answer_question_with_context(question=question, matches=search_response.matches)
    if _is_no_answer_response(answer):
        return DocumentAskResponse(
            document_version_id=search_response.document_version_id,
            question=question,
            answer_status="insufficient_context",
            answer=answer,
            citations=[],
            matches=search_response.matches,
        )

    return DocumentAskResponse(
        document_version_id=search_response.document_version_id,
        question=question,
        answer_status="answered",
        answer=answer,
        citations=citations,
        matches=search_response.matches,
    )


def _build_citations(matches) -> list[DocumentCitationResponse]:
    """Return the top citation records derived from the strongest retrieval matches."""

    settings = get_settings()
    citation_matches = matches[: settings.answer_citation_count]
    return [
        DocumentCitationResponse(
            chunk_id=match.chunk_id,
            chunk_index=match.chunk_index,
            start_page_number=match.start_page_number,
            end_page_number=match.end_page_number,
        )
        for match in citation_matches
    ]


def _has_sufficient_context(matches, question: str) -> bool:
    """Return whether the retrieved matches look strong enough to ground an answer."""

    if not matches:
        return False

    settings = get_settings()
    best_distance = min(match.distance for match in matches)
    if _is_summary_style_question(question):
        return best_distance <= max(settings.retrieval_weak_match_max_distance, 0.7)
    return best_distance <= settings.retrieval_weak_match_max_distance


def _is_summary_style_question(question: str) -> bool:
    """Return whether a question is asking for a broad summary of the document."""

    normalized_question = question.lower()
    summary_markers = [
        "what is this document about",
        "what's this document about",
        "what is the document about",
        "what's the document about",
        "summarize this document",
        "summarise this document",
        "give me a summary",
        "what does this document say",
        "what is this about",
    ]
    return any(marker in normalized_question for marker in summary_markers)


def _is_no_answer_response(answer: str) -> bool:
    """Return whether the generated answer is explicitly declining due to missing support."""

    normalized_answer = answer.lower()
    no_answer_markers = [
        "could not find",
        "not found in the document",
        "not present in the context",
        "not in the document",
        "not enough information",
    ]
    return any(marker in normalized_answer for marker in no_answer_markers)
