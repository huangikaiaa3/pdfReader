"""Intent and scope classification for session questions."""

from __future__ import annotations

from typing import Literal

from google import genai

from app.core.config import get_settings

QuestionIntent = Literal["document_question", "non_document"]
DocumentQuestionScope = Literal["document_level", "local_detail"]


def classify_question_intent(question: str) -> QuestionIntent:
    """Classify whether one question is about the uploaded PDF."""

    prompt = (
        "You are classifying messages in a PDF question-answering application.\n\n"
        "Return only one label:\n"
        "document_question\n"
        "non_document\n\n"
        "Choose document_question only if the user is asking about the uploaded PDF, its contents, summary, meaning, wording, facts, dates, addresses, entities, or details that should be answered from the document.\n"
        "Choose non_document if the user is greeting, making small talk, asking general knowledge, or asking for something unrelated to the uploaded PDF.\n\n"
        f"User message:\n{question}"
    )
    result = _generate_label(prompt)
    return "document_question" if result == "document_question" else "non_document"


def classify_document_question_scope(question: str) -> DocumentQuestionScope:
    """Classify whether one document question is broad or detail-oriented."""

    prompt = (
        "You are classifying the scope of a question about an uploaded PDF.\n\n"
        "Return only one label:\n"
        "document_level\n"
        "local_detail\n\n"
        "Choose document_level if the question asks about the document as a whole, such as its summary, overall purpose, main subject, listed dates, listed addresses, or broad themes.\n"
        "Choose local_detail if the question asks for a specific fact, wording, amount, clause, signature, or a detail likely answered by one or a few passages.\n\n"
        f"User question:\n{question}"
    )
    result = _generate_label(prompt)
    return "document_level" if result == "document_level" else "local_detail"


def _generate_label(prompt: str) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    response = client.models.generate_content(
        model=settings.generation_model,
        contents=prompt,
    )
    return (response.text or "").strip().lower()
