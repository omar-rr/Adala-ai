from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException, UploadFile, status


PDF_MIME_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._\-\u0600-\u06FF ]+")


def sanitize_filename(filename: str | None) -> str:
    raw = Path(filename or "document.pdf").name.strip()
    cleaned = SAFE_FILENAME.sub("_", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "document.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:160]


def sanitize_query(text: str) -> str:
    cleaned = CONTROL_CHARS.sub(" ", text)
    cleaned = re.sub(r"\s{3,}", "  ", cleaned).strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message is empty.")
    return cleaned[:8000]


def validate_pdf_metadata(file: UploadFile) -> str:
    filename = sanitize_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF files are supported.",
        )
    if file.content_type and file.content_type not in PDF_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload rejected: content type must be application/pdf.",
        )
    return filename


def assert_pdf_header(first_chunk: bytes) -> None:
    if not first_chunk.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload rejected: file signature is not a PDF.",
        )

