from __future__ import annotations

import json
from collections.abc import Iterator
from threading import Thread
from urllib import request

from app.config import settings


_tokenizer = None
_model = None


def _load_transformers_model():
    global _model, _tokenizer
    if _model is not None and _tokenizer is not None:
        return _tokenizer, _model

    from transformers import AutoModelForCausalLM, AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained(settings.qwen_model_id, trust_remote_code=True)
    _model = AutoModelForCausalLM.from_pretrained(
        settings.qwen_model_id,
        torch_dtype="auto",
        device_map="auto",
        trust_remote_code=True,
    )
    return _tokenizer, _model


def _mock_stream(messages: list[dict[str, str]]) -> Iterator[str]:
    text = (
        "Mock LLM mode is enabled. The retrieval layer is connected, but Qwen generation is "
        "disabled for this environment. Switch LLM_PROVIDER=transformers to use the configured "
        f"{settings.qwen_model_id} model."
    )
    for token in text.split(" "):
        yield token + " "


def _without_thinking(text: str, state: dict[str, bool]) -> str:
    output = []
    cursor = 0
    while cursor < len(text):
        if state.get("in_think", False):
            end = text.find("</think>", cursor)
            if end == -1:
                return "".join(output)
            state["in_think"] = False
            cursor = end + len("</think>")
            continue
        start = text.find("<think>", cursor)
        if start == -1:
            output.append(text[cursor:])
            break
        output.append(text[cursor:start])
        state["in_think"] = True
        cursor = start + len("<think>")
    return "".join(output)


def _ollama_stream(messages: list[dict[str, str]]) -> Iterator[str]:
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": True,
        "think": False,
        "options": {
            "temperature": settings.temperature,
            "num_predict": settings.max_new_tokens,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings.ollama_api_key:
        headers["Authorization"] = f"Bearer {settings.ollama_api_key}"
    req = request.Request(
        f"{settings.ollama_base_url.rstrip('/')}/api/chat",
        data=body,
        headers=headers,
        method="POST",
    )
    state = {"in_think": False}
    with request.urlopen(req, timeout=settings.ollama_request_timeout) as response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            event = json.loads(raw_line.decode("utf-8"))
            if event.get("done"):
                break
            token = str((event.get("message") or {}).get("content") or "")
            visible = _without_thinking(token, state)
            if visible:
                yield visible


def stream_answer(messages: list[dict[str, str]]) -> Iterator[str]:
    provider = settings.llm_provider.lower()
    if provider == "mock":
        yield from _mock_stream(messages)
        return
    if provider == "ollama":
        yield from _ollama_stream(messages)
        return

    tokenizer, model = _load_transformers_model()
    try:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    inputs = tokenizer([prompt], return_tensors="pt").to(model.device)

    from transformers import TextIteratorStreamer

    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    generation_kwargs = {
        **inputs,
        "streamer": streamer,
        "max_new_tokens": settings.max_new_tokens,
        "temperature": settings.temperature,
        "do_sample": settings.temperature > 0,
    }
    thread = Thread(target=model.generate, kwargs=generation_kwargs, daemon=True)
    thread.start()
    for token in streamer:
        yield token
    thread.join(timeout=1)
