#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/venv/bin:${PATH}"
mkdir -p "${DATA_DIR:-/data}"

uvicorn app.main:app --app-dir /app/api --host 0.0.0.0 --port 8000 &

cd /app/web
HOSTNAME=0.0.0.0 PORT="${PORT:-7860}" node apps/web/server.js

