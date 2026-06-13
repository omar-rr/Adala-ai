from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from app import db
from app.config import settings
from app.rag.articles import split_article_sections


def repair_arabic_extraction(text: str) -> str:
    # Some legacy Arabic PDFs map the kaf glyph to alef-madda during text extraction.
    text = re.sub(r"(?<=[\u0600-\u06FF])آ(?=[\u0600-\u06FF])", "ك", text)
    text = re.sub(r"(?<![\u0600-\u06FF])آ(?=(?:ل|ان|افة|يف|ون|ما|ذا|ذلك|لمة|ثير|تاب|تب))", "ك", text)
    return text


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = repair_arabic_extraction(text)
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extraction_quality(text: str) -> float:
    if not text:
        return 0.0
    normalized = normalize_text(text)
    arabic = len(re.findall(r"[\u0600-\u06FF]", normalized))
    latin = len(re.findall(r"[A-Za-z]", normalized))
    digits = len(re.findall(r"\d", normalized))
    weird = len(re.findall(r"[\u0100-\u024F\u0250-\u02AF\u0370-\u03FF]", normalized))
    replacement = normalized.count("\ufffd")
    words = len(re.findall(r"[\w\u0600-\u06FF]+", normalized))
    return (arabic * 2.0) + latin + (digits * 0.25) + (words * 0.3) - (weird * 2.8) - (replacement * 10)


def extraction_is_corrupted(text: str) -> bool:
    normalized = normalize_text(text)
    if len(normalized) < 40:
        return True
    arabic = len(re.findall(r"[\u0600-\u06FF]", normalized))
    weird = len(re.findall(r"[\u0100-\u024F\u0250-\u02AF\u0370-\u03FF]", normalized))
    article_markers = len(re.findall(r"(?:المادة|الماده|مادة|ماده)\s*[\(\)]*\s*[0-9٠-٩]+", normalized))
    if article_markers:
        return False
    return weird > max(25, arabic * 0.55)


def extract_with_pymupdf(pdf_path: Path) -> list[str] | None:
    try:
        import fitz
    except ModuleNotFoundError:
        return None

    try:
        with fitz.open(pdf_path) as document:
            return [page.get_text("text") or "" for page in document]
    except Exception:
        return None


def chunk_id_for(document_id: str, page_number: int, chunk_index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{document_id}:p{page_number}:c{chunk_index}:{digest}"


def split_text(text: str, chunk_size: int = 1100, overlap: int = 180) -> list[str]:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", "۔", "؛", "،", ".", "?", "؟", " ", ""],
        )
        return splitter.split_text(text)
    except ModuleNotFoundError:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            boundary = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
        return chunks


def add_to_chroma(rows: list[dict[str, str | int | None]], document_name: str) -> None:
    if settings.vector_backend.lower() != "chroma" or not rows:
        return

    try:
        from langchain_core.documents import Document

        from app.rag.vectorstore import get_vectorstore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "VECTOR_BACKEND=chroma requires langchain, langchain-chroma, and embedding dependencies."
        ) from exc

    vector_docs = [
        Document(
            page_content=str(row["text"]),
            metadata={
                "document_id": row["document_id"],
                "document_name": document_name,
                "page_number": row["page_number"],
                "article_number": row["article_number"] or "",
                "chunk_id": row["id"],
                "original_text": row["text"],
            },
        )
        for row in rows
    ]
    vector_ids = [str(row["id"]) for row in rows]
    get_vectorstore().add_documents(vector_docs, ids=vector_ids)


def rows_for_page_text(
    document_id: str,
    page_index: int,
    page_text: str,
    current_article_number: str | None = None,
) -> tuple[list[dict[str, str | int | None]], str | None]:
    rows: list[dict[str, str | int | None]] = []
    page_chunk_index = 0
    for section_article_number, section_text in split_article_sections(page_text):
        article_number = section_article_number or current_article_number
        if section_article_number:
            current_article_number = section_article_number
        for chunk_text in split_text(section_text):
            chunk_text = normalize_text(chunk_text)
            if len(chunk_text) < 30:
                continue
            page_chunk_index += 1
            chunk_id = chunk_id_for(document_id, page_index, page_chunk_index, chunk_text)
            rows.append(
                {
                    "id": chunk_id,
                    "document_id": document_id,
                    "page_number": page_index,
                    "article_number": article_number,
                    "text": chunk_text,
                    "chroma_id": chunk_id,
                }
            )
    return rows, current_article_number


def best_extracted_page_text(
    pdf_path: Path,
    page,
    page_index: int,
    pymupdf_pages: list[str] | None,
) -> str:
    pypdf_text = page.extract_text() or ""
    pymupdf_text = ""
    if pymupdf_pages and page_index <= len(pymupdf_pages):
        pymupdf_text = pymupdf_pages[page_index - 1]
    return normalize_text(
        pymupdf_text if extraction_quality(pymupdf_text) > extraction_quality(pypdf_text) else pypdf_text
    )


def ocr_index_pages(
    document_id: str,
    document_name: str,
    pdf_path: Path,
    page_numbers: list[int],
) -> int:
    if not settings.ocr_enabled:
        return 0

    from app.rag.ocr import ocr_pdf_page

    rows: list[dict[str, str | int | None]] = []
    for page_number in page_numbers:
        page_text = normalize_text(ocr_pdf_page(document_id, pdf_path, page_number))
        if not page_text:
            continue
        page_rows, _ = rows_for_page_text(document_id, page_number, page_text)
        rows.extend(page_rows)

    if rows:
        db.delete_chunks_for_document_pages(document_id, page_numbers)
        add_to_chroma(rows, document_name)
        db.insert_chunks(rows)
    return len(rows)


def candidate_pages_for_article(article_number: str, page_count: int) -> list[int]:
    try:
        number = int(re.sub(r"\D", "", article_number))
    except ValueError:
        return []

    if page_count <= 0:
        return []

    estimated = max(1, min(page_count, round((number / 254) * page_count)))
    candidates: list[int] = []
    for delta in [0, -1, 1, -2, 2, -3, 3, -4, 4]:
        page = estimated + delta
        if 1 <= page <= page_count:
            candidates.append(page)

    if number >= 220:
        candidates.extend(range(max(1, page_count - 7), page_count + 1))
    if number <= 40:
        candidates.extend(range(1, min(page_count, 10) + 1))

    deduped: list[int] = []
    seen: set[int] = set()
    for page in candidates:
        if page not in seen:
            deduped.append(page)
            seen.add(page)
    return deduped


def ingest_pdf(document_id: str, document_name: str, pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    pymupdf_pages = extract_with_pymupdf(pdf_path)

    rows: list[dict[str, str | int | None]] = []

    current_article_number: str | None = None
    for page_index, page in enumerate(reader.pages, start=1):
        page_text = best_extracted_page_text(pdf_path, page, page_index, pymupdf_pages)
        if settings.ocr_enabled and settings.ocr_on_upload and extraction_is_corrupted(page_text):
            from app.rag.ocr import ocr_pdf_page

            page_text = normalize_text(ocr_pdf_page(document_id, pdf_path, page_index))
        if not page_text:
            continue

        page_rows, current_article_number = rows_for_page_text(
            document_id,
            page_index,
            page_text,
            current_article_number,
        )
        rows.extend(page_rows)

    if rows:
        add_to_chroma(rows, document_name)
        db.insert_chunks(rows)

    return len(rows)
