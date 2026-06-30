# Lexis Mollis SPARQL Space

Optional read-only SPARQL scaffold for EPIC F. It loads a Turtle graph when available and
falls back to a tiny sample graph so the Space can boot before the full RDF export exists.

```bash
python -m pip install -r requirements.txt
uvicorn app:app --reload --port 7861
```

Environment variables:

- `RDF_PATH`: optional path to `graph.ttl`.
- `CORS_ORIGINS`: comma-separated allowed origins, defaults to `*`.

Endpoints:

- `GET /health`
- `GET /sparql?query=...`
- `POST /sparql`
