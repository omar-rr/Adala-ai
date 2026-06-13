from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pypdf import PdfReader

from app import db
from app.config import settings
from app.models import ChunkOut, DocumentIngestResponse, DocumentOut
from app.rag.ingestion import ingest_pdf
from app.security import assert_pdf_header, sanitize_filename, validate_pdf_metadata


router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
def documents(search: str | None = None) -> list[dict]:
    return db.list_documents(search)


@router.get("/search", response_model=list[DocumentOut])
def search_documents(q: str = "") -> list[dict]:
    return db.list_documents(q.strip() or None)


@router.post("/upload", response_model=DocumentIngestResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...)) -> dict:
    filename = validate_pdf_metadata(file)
    document_id = uuid.uuid4().hex
    target_path = settings.upload_dir / f"{document_id}_{sanitize_filename(filename)}"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    hasher = hashlib.sha256()
    total = 0
    first_chunk = True

    try:
        with target_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                if first_chunk:
                    assert_pdf_header(chunk)
                    first_chunk = False
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"PDF exceeds {settings.max_upload_mb} MB upload limit.",
                    )
                hasher.update(chunk)
                output.write(chunk)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if total == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty upload.")

    sha256 = hasher.hexdigest()
    duplicate = db.get_document_by_sha(sha256)
    if duplicate:
        target_path.unlink(missing_ok=True)
        chunk_count = len(db.list_chunks_for_document(duplicate["id"]))
        return {**duplicate, "chunk_count": chunk_count, "duplicate": True}

    try:
        reader = PdfReader(str(target_path))
        pages = len(reader.pages)
        document = db.create_document(document_id, filename, target_path, sha256, pages)
        chunk_count = ingest_pdf(document_id, filename, target_path)
        if chunk_count == 0:
            db.delete_document(document_id)
            target_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "No searchable text could be extracted from this PDF. "
                    "The built-in OCR pipeline could not recover enough text from it."
                ),
            )
        return {**document, "chunk_count": chunk_count, "duplicate": False}
    except Exception:
        db.delete_document(document_id)
        target_path.unlink(missing_ok=True)
        raise


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str) -> dict:
    document = db.get_document(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


@router.post("/{document_id}/reindex", response_model=DocumentIngestResponse)
def reindex_document(document_id: str) -> dict:
    document = db.get_document(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    path = Path(document["path"])
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF file not found.")

    db.delete_chunks_for_document(document_id)
    chunk_count = ingest_pdf(document_id, document["name"], path)
    if chunk_count == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No searchable text could be extracted from this PDF. "
                "The built-in OCR pipeline could not recover enough text from it."
            ),
        )
    return {**document, "chunk_count": chunk_count, "duplicate": False}


@router.get("/{document_id}/file")
def get_document_file(document_id: str) -> FileResponse:
    document = db.get_document(document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    path = Path(document["path"])
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF file not found.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document["name"],
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/{document_id}/chunks/{chunk_id}", response_model=ChunkOut)
def get_chunk(document_id: str, chunk_id: str) -> dict:
    chunk = db.get_chunk(chunk_id)
    if not chunk or chunk["document_id"] != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found.")
    return chunk
