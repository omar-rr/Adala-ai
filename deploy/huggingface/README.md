# Hugging Face Spaces Deployment

Use the Docker Space runtime.

1. Create a new Hugging Face Space with **Docker** as the SDK.
2. Copy this repository into the Space.
3. In the Space settings, add persistent storage if you want uploaded PDFs and Chroma indexes to survive restarts.
4. Set these variables as needed:

```bash
DATA_DIR=/data
MAX_UPLOAD_MB=80
EMBEDDING_MODEL=BAAI/bge-m3
QWEN_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
VECTOR_BACKEND=chroma
LLM_PROVIDER=transformers
TOP_K=6
MIN_RELEVANCE=0.25
NEXT_PUBLIC_API_BASE_URL=/api
INTERNAL_API_BASE_URL=http://127.0.0.1:8000
```

For small CPU Spaces, set `LLM_PROVIDER=mock` while validating upload/retrieval, then switch to a GPU Space for Qwen generation.
