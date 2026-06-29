from app.schemas.document import DocumentAskResponse
from app.services.retrieval_service import search_document_chunks
from app.services.generation_service import answer_question_with_context

def ask_document_question(db, document_version_id, question: str, top_k: int) -> DocumentAskResponse:
    
    search_response = search_document_chunks(
        db=db,
        document_version_id=document_version_id,
        query=question,
        top_k=top_k
    )
    
    answer = answer_question_with_context(question=question, matches=search_response.matches)
    
    return DocumentAskResponse(
        document_version_id=search_response.document_version_id,
        question=question,
        answer=answer,
        matches=search_response.matches
    )