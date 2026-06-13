from __future__ import annotations

import os

import uvicorn

from app.main import app


def main() -> None:
    host = os.getenv("ADALA_API_HOST", "127.0.0.1")
    port = int(os.getenv("ADALA_API_PORT", "8001"))
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
