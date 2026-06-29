from google import genai
from app.core.config import get_settings
from app.schemas.document import DocumentSearchMatchResponse

def build_grounded_prompt(question: str, matches: list[DocumentSearchMatchResponse]) -> str:
    context_blocks = []
    
    for match in matches:
        context_blocks.append(
            f"[Chunk {match.chunk_index} | pages {match.start_page_number}-{match.end_page_number}]\n{match.text}"
        )
    
    context = "\n\n".join(context_blocks)
    
    return (
        "You are answering questions about a PDF.\n"
        "Use only the provided context.\n"
        "If the answer is not present in the context, say you could not find it in the document.\n\n"
        f"Question:\n{question}\n\n"
        f"Context:\n{context}"
    )


def answer_question_with_context(question: str, matches: list[DocumentSearchMatchResponse]) -> str:
    if len(matches) == 0:
        return "I could not find relevant context in the document."
    
    settings = get_settings()
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    prompt = build_grounded_prompt(question, matches)
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

    response = client.models.generate_content(
        model=settings.generation_model,
        contents=prompt,
    )

    return response.text or "I could not generate an answer from the retrieved context."
