from pathlib import Path
from pypdf import PdfReader

def extract_pdf_text(storage_path: str) -> dict:
    """Extract text from a PDF file and return page-level results."""

    pdf_path = Path(storage_path)
    reader = PdfReader(pdf_path)

    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = extract_page_text(page)
        pages.append(
            {
                "page_number": index,
                "text": text,
                "char_count": len(text),
            }
        )

    total_char_count = sum(page["char_count"] for page in pages)
    is_readable = total_char_count > 0
    message = None
    if not is_readable:
        message = "No usable text was extracted from this PDF with the current parser."

    return {
        "page_count": len(reader.pages),
        "pages": pages,
        "total_char_count": total_char_count,
        "is_readable": is_readable,
        "message": message,
    }


def extract_page_text(page) -> str:
    """Extract text from a single PDF page."""

    text = page.extract_text()
    return text or ""
