from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  pages INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  article_number TEXT,
  text TEXT NOT NULL,
  chroma_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_chunks_article ON chunks(article_number);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  citations_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def connect() -> sqlite3.Connection:
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def create_document(document_id: str, name: str, path: Path, sha256: str, pages: int) -> dict[str, Any]:
    now = utcnow()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO documents (id, name, path, sha256, pages, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, name, str(path), sha256, pages, now),
        )
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return dict(row)


def delete_document(document_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))


def get_document(document_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return row_to_dict(row)


def get_document_by_sha(sha256: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
    return row_to_dict(row)


def update_document_name(document_id: str, name: str) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("UPDATE documents SET name = ? WHERE id = ?", (name, document_id))
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return row_to_dict(row)


def list_documents(search: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if search:
            rows = conn.execute(
                """
                SELECT * FROM documents
                WHERE lower(name) LIKE lower(?)
                ORDER BY created_at DESC
                """,
                (f"%{search}%",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def insert_chunks(chunks: Iterable[dict[str, Any]]) -> None:
    now = utcnow()
    rows = [
        (
            chunk["id"],
            chunk["document_id"],
            chunk["page_number"],
            chunk.get("article_number"),
            chunk["text"],
            chunk["chroma_id"],
            now,
        )
        for chunk in chunks
    ]
    if not rows:
        return
    with connect() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO chunks
              (id, document_id, page_number, article_number, text, chroma_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def get_chunk(chunk_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    return row_to_dict(row)


def list_chunks_for_document(document_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY page_number ASC",
            (document_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_chunks_for_document(document_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))


def delete_chunks_for_document_pages(document_id: str, page_numbers: Iterable[int]) -> None:
    pages = sorted({int(page) for page in page_numbers})
    if not pages:
        return
    placeholders = ",".join("?" for _ in pages)
    with connect() as conn:
        conn.execute(
            f"DELETE FROM chunks WHERE document_id = ? AND page_number IN ({placeholders})",
            (document_id, *pages),
        )


def list_searchable_chunks() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
              chunks.id,
              chunks.document_id,
              documents.name AS document_name,
              chunks.page_number,
              chunks.article_number,
              chunks.text,
              chunks.chroma_id
            FROM chunks
            JOIN documents ON documents.id = chunks.document_id
            ORDER BY documents.created_at DESC, chunks.page_number ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_article_numbers_for_document(document_id: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT article_number
            FROM chunks
            WHERE document_id = ? AND article_number IS NOT NULL AND article_number != ''
            """,
            (document_id,),
        ).fetchall()
    return [str(row["article_number"]) for row in rows]


def find_chunks_by_article(article_number: str, limit: int | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT
          chunks.id,
          chunks.document_id,
          documents.name AS document_name,
          chunks.page_number,
          chunks.article_number,
          chunks.text,
          chunks.chroma_id
        FROM chunks
        JOIN documents ON documents.id = chunks.document_id
        WHERE chunks.article_number = ?
        ORDER BY documents.created_at DESC, chunks.page_number ASC, chunks.id ASC
    """
    params: tuple[Any, ...]
    if limit is not None:
        query += " LIMIT ?"
        params = (article_number, limit)
    else:
        params = (article_number,)
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def find_highest_article_chunks(limit: int = 3) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
              chunks.id,
              chunks.document_id,
              documents.name AS document_name,
              chunks.page_number,
              chunks.article_number,
              chunks.text,
              chunks.chroma_id
            FROM chunks
            JOIN documents ON documents.id = chunks.document_id
            WHERE chunks.article_number GLOB '[0-9]*'
            ORDER BY CAST(chunks.article_number AS INTEGER) DESC, documents.created_at DESC, chunks.page_number DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_conversation(conversation_id: str, title: str) -> dict[str, Any]:
    now = utcnow()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, title, now, now),
        )
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return dict(row)


def touch_conversation(conversation_id: str, title: str | None = None) -> None:
    with connect() as conn:
        if title:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, utcnow(), conversation_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (utcnow(), conversation_id),
            )


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return row_to_dict(row)


def list_conversations() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 50",
        ).fetchall()
    return [dict(row) for row in rows]


def add_message(
    message_id: str,
    conversation_id: str,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = utcnow()
    citations_json = json.dumps(citations or [], ensure_ascii=False)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, citations_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, conversation_id, role, content, citations_json, now),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return dict(row)


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()
    messages = []
    for row in rows:
        item = dict(row)
        item["citations"] = json.loads(item.pop("citations_json") or "[]")
        messages.append(item)
    return messages
