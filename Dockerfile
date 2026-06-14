FROM node:24-bookworm AS web-builder

WORKDIR /workspace
COPY package.json package-lock.json* ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm install
COPY apps/web ./apps/web
ARG NEXT_PUBLIC_API_BASE_URL=/api
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV INTERNAL_API_BASE_URL=http://127.0.0.1:8000
RUN npm --workspace apps/web run build

FROM node:24-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=space \
    PORT=7860 \
    DATA_DIR=/data \
    SEED_DOCUMENTS_DIR=/app/seed-documents \
    VECTOR_BACKEND=local \
    LLM_PROVIDER=extractive \
    RAG_LLM_ENABLED=false \
    OCR_ENABLED=true \
    OCR_ON_UPLOAD=true \
    NEXT_PUBLIC_API_BASE_URL=/api \
    INTERNAL_API_BASE_URL=http://127.0.0.1:8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    python3 \
    python3-pip \
    python3-venv \
  && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt /app/api/requirements.txt
RUN python3 -m venv /opt/venv \
  && /opt/venv/bin/pip install --upgrade pip \
  && /opt/venv/bin/pip install -r /app/api/requirements.txt

COPY apps/api/app /app/api/app
COPY assets/seed-documents /app/seed-documents
COPY --from=web-builder /workspace/apps/web/.next/standalone /app/web
COPY --from=web-builder /workspace/apps/web/.next/static /app/web/apps/web/.next/static
COPY --from=web-builder /workspace/apps/web/public /app/web/apps/web/public
COPY deploy/huggingface/start.sh /app/start.sh

RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

EXPOSE 7860
CMD ["/app/start.sh"]
