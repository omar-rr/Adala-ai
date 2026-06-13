from typing import Literal

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: str
    name: str
    pages: int
    created_at: str


class DocumentIngestResponse(DocumentOut):
    chunk_count: int
    duplicate: bool = False


class ChunkOut(BaseModel):
    id: str
    document_id: str
    page_number: int
    article_number: str | None
    text: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class Citation(BaseModel):
    source_index: int
    document_id: str
    document_name: str
    page_number: int
    article_number: str | None = None
    chunk_id: str
    quote: str
    score: float = 0.0


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=12)


class HealthOut(BaseModel):
    status: Literal["ok"]
    app: str
    environment: str

