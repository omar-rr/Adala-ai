from functools import lru_cache

from langchain_chroma import Chroma

from app.config import settings
from app.rag.embeddings import get_embeddings


COLLECTION_NAME = "egyptian_legal_chunks"


@lru_cache
def get_vectorstore() -> Chroma:
    settings.ensure_dirs()
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(settings.chroma_dir),
    )

