from __future__ import annotations

from typing import Any

import orjson


def sse_event(payload: dict[str, Any]) -> str:
    return f"data: {orjson.dumps(payload).decode('utf-8')}\n\n"

