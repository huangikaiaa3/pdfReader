"""Document-level profile generation and answering."""

from __future__ import annotations

import json
from typing import Any

from google import genai

from app.core.config import get_settings
from app.db.models import DocumentProfile, DocumentVersion
from app.schemas.document import DocumentAskResponse


def build_document_profile_payload(page_texts: list[str]) -> dict[str, Any]:
    """Generate structured document-level metadata from extracted text."""

    settings = get_settings()
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    combined_text = "\n\n".join(page_texts)
    prompt = (
        "You are extracting document-level metadata for a PDF chat application.\n"
        "Return valid JSON only with these keys:\n"
        "summary, document_type, primary_subject, key_dates, key_addresses\n\n"
        "Rules:\n"
        "- summary: one concise paragraph\n"
        "- document_type: short snake_case style label if possible\n"
        "- primary_subject: main person or entity if clear, otherwise null\n"
        "- key_dates: array of important date strings mentioned in the document\n"
        "- key_addresses: array of address strings mentioned in the document\n"
        "- Do not include markdown fences.\n\n"
        f"Document text:\n{combined_text}"
    )

    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    response = client.models.generate_content(
        model=settings.generation_model,
        contents=prompt,
    )
    payload = _parse_json_payload(response.text or "")
    return {
        "summary": str(payload.get("summary") or "").strip(),
        "document_type": str(payload.get("document_type") or "document").strip(),
        "primary_subject": _normalize_optional_string(payload.get("primary_subject")),
        "key_dates": _normalize_string_list(payload.get("key_dates")),
        "key_addresses": _normalize_string_list(payload.get("key_addresses")),
    }


def create_document_profile(document_version: DocumentVersion, page_texts: list[str]) -> DocumentProfile:
    """Build one persisted document profile from extracted text."""

    payload = build_document_profile_payload(page_texts)
    if not payload["summary"]:
        raise ValueError("Document profile summary generation returned an empty summary.")

    return DocumentProfile(
        document_version_id=document_version.id,
        summary=payload["summary"],
        document_type=payload["document_type"],
        primary_subject=payload["primary_subject"],
        key_dates_json=payload["key_dates"],
        key_addresses_json=payload["key_addresses"],
    )


def answer_document_level_question(document_version_id, question: str, profile: DocumentProfile) -> DocumentAskResponse:
    """Answer one broad document-level question from the persisted profile."""

    answer = _generate_profile_answer(question=question, profile=profile)
    return DocumentAskResponse(
        document_version_id=document_version_id,
        question=question,
        answer_status="answered",
        answer=answer,
        citations=[],
        matches=[],
    )


def _generate_profile_answer(question: str, profile: DocumentProfile) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    prompt = (
        "You are answering a broad question about a PDF using only the provided document profile.\n"
        "If the profile does not support the answer, say you could not find enough support in the document.\n\n"
        f"Question:\n{question}\n\n"
        f"Document summary:\n{profile.summary}\n\n"
        f"Document type:\n{profile.document_type}\n\n"
        f"Primary subject:\n{profile.primary_subject or 'Unknown'}\n\n"
        f"Key dates:\n{json.dumps(profile.key_dates_json)}\n\n"
        f"Key addresses:\n{json.dumps(profile.key_addresses_json)}"
    )
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    response = client.models.generate_content(
        model=settings.generation_model,
        contents=prompt,
    )
    return response.text or "I could not find enough support in the document to answer that question."


def _parse_json_payload(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()
    return json.loads(cleaned)


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
