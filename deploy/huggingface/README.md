# Hugging Face Spaces Deployment

Use the Docker Space runtime.

1. Create a new Hugging Face Space with **Docker** as the SDK.
2. Push this repository to the Space. The root `Dockerfile` is the Space entrypoint.
3. In the Space settings, add persistent storage if you want uploaded PDFs and Chroma indexes to survive restarts.
4. Set these variables as needed:

```bash
DATA_DIR=/data
MAX_UPLOAD_MB=80
EMBEDDING_MODEL=BAAI/bge-m3
QWEN_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
SEED_DOCUMENTS_DIR=/app/seed-documents
VECTOR_BACKEND=local
LLM_PROVIDER=extractive
RAG_LLM_ENABLED=false
OCR_ENABLED=true
OCR_ON_UPLOAD=true
TOP_K=6
MIN_RELEVANCE=0.25
NEXT_PUBLIC_API_BASE_URL=/api
INTERNAL_API_BASE_URL=http://127.0.0.1:8000
```

The default Docker image uses the local extractive legal-answer engine so it can run on CPU Spaces without a paid GPU. The two bundled constitution PDFs are seeded automatically from `/app/seed-documents`.

For full Qwen generation on Hugging Face, use a GPU Space and switch `LLM_PROVIDER=transformers` after validating resource limits.
