from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from urllib import error, request

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.events import sse_event
from app.config import settings


router = APIRouter(prefix="/api/model", tags=["model"])

LOCAL_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_LOCAL_MODEL = "qwen3:1.7b"


class LocalModelRequest(BaseModel):
    model: str = DEFAULT_LOCAL_MODEL


def _ollama_request(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 8):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = request.Request(
        f"{LOCAL_OLLAMA_BASE_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    return request.urlopen(req, timeout=timeout)


def _installed_models() -> tuple[bool, list[str], str | None]:
    try:
        with _ollama_request("/api/tags") as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        return False, [], str(exc.reason if hasattr(exc, "reason") else exc)
    except Exception as exc:
        return False, [], str(exc)

    names = []
    for item in payload.get("models", []):
        name = item.get("name") or item.get("model")
        if name:
            names.append(str(name))
    return True, names, None


def _model_matches(installed: list[str], wanted: str) -> bool:
    wanted_name = wanted.strip()
    wanted_family = wanted_name.split(":", 1)[0]
    return any(name == wanted_name or name.split(":", 1)[0] == wanted_family for name in installed)


def _desktop_settings_path() -> Path | None:
    raw = os.getenv("ADALA_DESKTOP_SETTINGS_PATH")
    return Path(raw) if raw else None


def _persist_desktop_settings(model: str) -> None:
    settings_path = _desktop_settings_path()
    if not settings_path:
        return

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if settings_path.exists():
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    payload.update(
        {
            "ollamaBaseUrl": LOCAL_OLLAMA_BASE_URL,
            "llmProvider": "ollama",
            "ollamaModel": model,
            "ragLlmEnabled": False,
        }
    )
    settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/status")
def model_status(model: str = DEFAULT_LOCAL_MODEL) -> dict:
    running, installed, error_message = _installed_models()
    model_available = running and _model_matches(installed, model)
    configured_for_local = (
        settings.llm_provider.lower() == "ollama"
        and settings.ollama_base_url.rstrip("/") == LOCAL_OLLAMA_BASE_URL
    )
    return {
        "ollama_running": running,
        "installed_models": installed,
        "target_model": model,
        "model_available": model_available,
        "llm_provider": settings.llm_provider,
        "local_model_enabled": configured_for_local and model_available,
        "ollama_base_url": settings.ollama_base_url,
        "error": error_message,
    }


@router.post("/enable-local")
def enable_local_model(payload: LocalModelRequest) -> dict:
    model = payload.model.strip() or DEFAULT_LOCAL_MODEL
    settings.llm_provider = "ollama"
    settings.ollama_base_url = LOCAL_OLLAMA_BASE_URL
    settings.ollama_model = model
    settings.rag_llm_enabled = False
    _persist_desktop_settings(model)
    return model_status(model)


def _pull_stream(model: str) -> Iterable[str]:
    try:
        with _ollama_request(
            "/api/pull",
            method="POST",
            payload={"name": model, "stream": True},
            timeout=900,
        ) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line.decode("utf-8"))
                yield sse_event(
                    {
                        "type": "progress",
                        "status": payload.get("status", "Downloading model..."),
                        "completed": payload.get("completed"),
                        "total": payload.get("total"),
                    }
                )
                if payload.get("status") == "success":
                    break
    except Exception as exc:
        yield sse_event({"type": "error", "error": str(exc)})
        return

    enable_local_model(LocalModelRequest(model=model))
    yield sse_event({"type": "done", "model": model})


@router.post("/pull")
def pull_local_model(payload: LocalModelRequest) -> StreamingResponse:
    model = payload.model.strip() or DEFAULT_LOCAL_MODEL
    return StreamingResponse(
        _pull_stream(model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
