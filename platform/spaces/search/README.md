# Lexis Mollis search Space

FastAPI scaffold for the public Hugging Face Space. It exposes the EPIC F API surface now,
with deterministic lexical fallback until the FAISS/LaBSE assets from EPIC C/E are
published.

```bash
python -m pip install -r requirements.txt
uvicorn app:app --reload --port 7860
```

Environment variables:

- `SITE_DATA_DIR`: optional path to the static site data directory.
- `HF_DATASET_ID`: defaults to `lexis-mollis/soft-law-corpus`.
- `CORS_ORIGINS`: comma-separated allowed origins, defaults to `*`.

Endpoints:

- `GET /health`
- `GET /search?q=&k=&filters=`
- `GET /similar?document_id=`
