from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


DATASET_ID = os.getenv("HF_DATASET_ID", "lexis-mollis/soft-law-corpus")
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "site" / "public" / "data"
DATA_DIR = Path(os.getenv("SITE_DATA_DIR", DEFAULT_DATA_DIR))


class SearchResult(BaseModel):
  document_id: str
  title: str
  score: float
  year: int | None = None
  doc_type: str | None = None
  languages: list[str] = []
  quality_score: float | None = None
  review_required: bool = False
  review_priority: str | None = None
  summary: str = ""


class SearchResponse(BaseModel):
  query: str
  mode: str
  dataset_id: str
  results: list[SearchResult]


def load_json(path: Path, fallback: Any) -> Any:
  if not path.exists():
    return fallback
  return json.loads(path.read_text(encoding="utf-8"))


def tokenize(text: str) -> list[str]:
  return re.findall(r"[\wÀ-ÖØ-öø-ÿ]+", text.lower())


def load_documents() -> list[dict[str, Any]]:
  payload = load_json(DATA_DIR / "search.json", {"documents": []})
  docs = payload.get("documents") or []
  if docs:
    return docs
  return [
    {
      "id": "sample",
      "document_id": "sample",
      "title": "Lexis Mollis sample",
      "summary": "Fallback sample used before static site data is mounted.",
      "text": "soft law corpus OCR audit search",
      "languages": ["en"],
      "review_required": False,
    }
  ]


DOCUMENTS = load_documents()
DOC_TOKENS = {doc["document_id"]: Counter(tokenize(" ".join(str(doc.get(key, "")) for key in ("title", "summary", "text", "tags")))) for doc in DOCUMENTS}


app = FastAPI(
  title="Lexis Mollis Search",
  description="Hybrid search API scaffold for the Lexis Mollis corpus.",
  version="0.1.0",
)

origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]
app.add_middleware(
  CORSMiddleware,
  allow_origins=origins,
  allow_credentials=False,
  allow_methods=["GET"],
  allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
  return {
    "ok": True,
    "mode": "lexical_fallback",
    "dataset_id": DATASET_ID,
    "document_count": len(DOCUMENTS),
    "data_dir": str(DATA_DIR),
  }


def parse_filters(filters: str | None) -> dict[str, str]:
  parsed: dict[str, str] = {}
  if not filters:
    return parsed
  for item in filters.split(","):
    if ":" in item:
      key, value = item.split(":", 1)
      parsed[key.strip()] = value.strip()
  return parsed


def passes_filters(doc: dict[str, Any], filters: dict[str, str]) -> bool:
  for key, value in filters.items():
    if key == "language" and value not in (doc.get("languages") or []):
      return False
    if key == "doc_type" and value != doc.get("doc_type"):
      return False
    if key == "year" and str(doc.get("year")) != value:
      return False
  return True


def lexical_score(query: str, doc_id: str) -> float:
  q_tokens = tokenize(query)
  if not q_tokens:
    return 0.0
  counts = DOC_TOKENS.get(doc_id, Counter())
  return sum(counts[token] for token in q_tokens) / len(q_tokens)


@app.get("/search", response_model=SearchResponse)
def search(
  q: Annotated[str, Query(description="Search query")] = "",
  k: Annotated[int, Query(ge=1, le=100)] = 10,
  filters: Annotated[
    str | None,
    Query(description="Comma-separated filters, e.g. language:fr,year:1948"),
  ] = None,
) -> SearchResponse:
  parsed_filters = parse_filters(filters)
  scored: list[tuple[float, dict[str, Any]]] = []
  for doc in DOCUMENTS:
    if not passes_filters(doc, parsed_filters):
      continue
    score = lexical_score(q, doc["document_id"]) if q else 1.0
    if score > 0:
      scored.append((score, doc))
  scored.sort(key=lambda item: item[0], reverse=True)
  results = [
    SearchResult(
      document_id=doc["document_id"],
      title=doc.get("title") or doc["document_id"],
      score=float(score),
      year=doc.get("year"),
      doc_type=doc.get("doc_type"),
      languages=doc.get("languages") or [],
      quality_score=doc.get("quality_score"),
      review_required=bool(doc.get("review_required")),
      review_priority=doc.get("review_priority"),
      summary=doc.get("summary") or doc.get("text_preview") or "",
    )
    for score, doc in scored[:k]
  ]
  return SearchResponse(query=q, mode="lexical_fallback", dataset_id=DATASET_ID, results=results)


@app.get("/similar")
def similar(
  document_id: Annotated[str, Query()],
  k: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, Any]:
  doc = load_json(DATA_DIR / "docs" / f"{document_id}.json", {})
  items = (doc.get("similar_documents") or [])[:k]
  return {"document_id": document_id, "mode": "precomputed_edges", "results": items}
