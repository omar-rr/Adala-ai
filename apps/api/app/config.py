from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "adala ai"
    app_env: str = "development"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ]
    )

    data_dir: Path = Path("./data")
    max_upload_mb: int = 80

    embedding_model: str = "BAAI/bge-m3"
    qwen_model_id: str = "Qwen/Qwen3-4B-Instruct-2507"
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: str | None = None
    ollama_model: str = "qwen3:1.7b"
    ollama_request_timeout: int = 300
    vector_backend: str = "local"
    llm_provider: str = "extractive"
    rag_llm_enabled: bool = False
    ocr_enabled: bool = True
    ocr_on_upload: bool = True
    ocr_scale: float = 1.25
    ocr_canvas_size: int = 1600

    top_k: int = 6
    min_relevance: float = 0.25
    max_new_tokens: int = 1300
    temperature: float = 0.15

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def ocr_dir(self) -> Path:
        return self.data_dir / "ocr"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "legal_ai.sqlite3"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.ocr_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
