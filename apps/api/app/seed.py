from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app import db
from app.config import settings
from app.rag.ingestion import ingest_pdf
from app.security import sanitize_filename


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_manifest(seed_dir: Path) -> list[dict[str, Any]]:
    manifest_path = seed_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _seed_document_id(digest: str) -> str:
    return f"seed_{digest[:24]}"


def seed_documents() -> list[dict[str, Any]]:
    seed_dir = settings.seed_documents_dir
    if not seed_dir or not seed_dir.exists():
        return []

    seeded: list[dict[str, Any]] = []
    original_ocr_on_upload = settings.ocr_on_upload
    settings.ocr_on_upload = False
    try:
        for item in _read_manifest(seed_dir):
            source_path = seed_dir / str(item.get("file") or "")
            display_name = str(item.get("name") or source_path.name).strip()
            if not source_path.exists() or source_path.suffix.lower() != ".pdf":
                continue

            digest = _sha256(source_path)
            existing = db.get_document_by_sha(digest)
            if existing and not Path(existing["path"]).exists():
                db.delete_document(existing["id"])
                existing = None

            if existing:
                if existing["name"] != display_name:
                    existing = db.update_document_name(existing["id"], display_name) or existing
                if not db.list_chunks_for_document(existing["id"]):
                    ingest_pdf(existing["id"], display_name, Path(existing["path"]))
                seeded.append(existing)
                continue

            document_id = _seed_document_id(digest)
            target_path = settings.upload_dir / f"{document_id}_{sanitize_filename(source_path.name)}"
            shutil.copyfile(source_path, target_path)
            pages = len(PdfReader(str(target_path)).pages)
            document = db.create_document(document_id, display_name, target_path, digest, pages)
            chunk_count = ingest_pdf(document_id, display_name, target_path)
            if chunk_count == 0:
                db.delete_document(document_id)
                target_path.unlink(missing_ok=True)
                continue
            seeded.append(document)
    finally:
        settings.ocr_on_upload = original_ocr_on_upload
    return seeded
