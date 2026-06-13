from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("ADALA_API_HOST", "127.0.0.1")
    port = int(os.getenv("ADALA_API_PORT", "8001"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
