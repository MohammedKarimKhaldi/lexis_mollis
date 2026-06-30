#!/usr/bin/env python3
"""Build lightweight static-site data from a Lexis Mollis release export."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> Any:
  if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
    return None
  if hasattr(value, "as_py"):
    return value.as_py()
  return str(value)


def write_json(path: Path, data: Any) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_suffix(path.suffix + ".tmp")
  tmp.write_text(
    json.dumps(data, ensure_ascii=False, indent=2, default=_json_default) + "\n",
    encoding="utf-8",
  )
  tmp.replace(path)


def read_parquet_dir(path: Path) -> list[dict[str, Any]]:
  try:
    import pyarrow.parquet as pq
  except ImportError as exc:  # pragma: no cover - exercised in environments without derive deps
    raise SystemExit("pyarrow is required: install the project with .[derive]") from exc

  if path.is_file():
    files = [path]
  else:
    files = sorted(path.glob("*.parquet")) if path.exists() else []
  rows: list[dict[str, Any]] = []
  for file in files:
    rows.extend(pq.read_table(file).to_pylist())
  return rows


def first_existing(paths: list[Path]) -> Path | None:
  for path in paths:
    if path.exists():
      return path
  return None


def as_list(value: Any) -> list[Any]:
  if value is None:
    return []
  if isinstance(value, list):
    return value
  if isinstance(value, tuple):
    return list(value)
  return [value]


def compact_text(text: str | None, limit: int = 420) -> str:
  normalized = re.sub(r"\s+", " ", text or "").strip()
  if len(normalized) <= limit:
    return normalized
  return normalized[: limit - 1].rstrip() + "…"


def tag_value(tags: list[str], namespace: str) -> str | None:
  prefix = f"{namespace}:"
  for tag in tags:
    if tag.startswith(prefix):
      return tag[len(prefix) :]
  return None


def load_release(release: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
  documents_path = first_existing([release / "documents", release / "documents.parquet"])
  pages_path = first_existing([release / "pages", release / "pages.parquet"])
  chunks_path = first_existing([release / "chunks", release / "chunks.parquet"])
  edges_path = first_existing([release / "edges", release / "edges.parquet", release / "similarity" / "doc_edges.parquet"])
  graph_path = first_existing([release / "graph" / "graph.sigma.json", release / "graph.sigma.json"])

  documents = read_parquet_dir(documents_path) if documents_path else []
  pages = read_parquet_dir(pages_path) if pages_path else []
  chunks = read_parquet_dir(chunks_path) if chunks_path else []
  edges = read_parquet_dir(edges_path) if edges_path else []
  graph = json.loads(graph_path.read_text(encoding="utf-8")) if graph_path else {"nodes": [], "edges": []}
  return documents, pages, chunks, edges, graph


def build_similarity(edges: list[dict[str, Any]], chunks: list[dict[str, Any]], titles: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
  chunk_to_doc = {row.get("chunk_id"): row.get("document_id") for row in chunks if row.get("chunk_id")}
  best: dict[tuple[str, str], dict[str, Any]] = {}

  for edge in edges:
    src = edge.get("src")
    dst = edge.get("dst")
    if not src or not dst:
      continue
    src_doc = src.replace("doc:", "") if str(src).startswith("doc:") else chunk_to_doc.get(src)
    dst_doc = dst.replace("doc:", "") if str(dst).startswith("doc:") else chunk_to_doc.get(dst)
    if not src_doc or not dst_doc or src_doc == dst_doc:
      continue
    key = tuple(sorted((str(src_doc), str(dst_doc))))
    score = edge.get("combined") or edge.get("semantic") or edge.get("lexical") or edge.get("weight") or 0
    try:
      numeric_score = float(score)
    except (TypeError, ValueError):
      numeric_score = 0.0
    current = best.get(key)
    if current is None or numeric_score > current["score"]:
      best[key] = {
        "src": str(src_doc),
        "dst": str(dst_doc),
        "score": numeric_score,
        "type": edge.get("type") or "similar_to",
        "provisional": bool(edge.get("provisional", False)),
      }

  grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
  for item in best.values():
    grouped[item["src"]].append(
      {
        "document_id": item["dst"],
        "title": titles.get(item["dst"], item["dst"]),
        "score": item["score"],
        "type": item["type"],
        "provisional": item["provisional"],
      }
    )
    grouped[item["dst"]].append(
      {
        "document_id": item["src"],
        "title": titles.get(item["src"], item["src"]),
        "score": item["score"],
        "type": item["type"],
        "provisional": item["provisional"],
      }
    )
  for doc_id in grouped:
    grouped[doc_id].sort(key=lambda row: row.get("score", 0), reverse=True)
  return grouped


def reduce_graph(graph: dict[str, Any], max_nodes: int) -> dict[str, Any]:
  nodes = graph.get("nodes") or []
  edges = graph.get("edges") or []
  selected = nodes[:max_nodes]
  selected_ids = {node.get("id") for node in selected}
  selected_edges = [
    edge
    for edge in edges
    if edge.get("source") in selected_ids and edge.get("target") in selected_ids
  ][: max_nodes * 3]
  return {"nodes": selected, "edges": selected_edges}


def build(args: argparse.Namespace) -> dict[str, Any]:
  release = Path(args.release)
  site = Path(args.site)
  documents, pages, chunks, edges, graph = load_release(release)
  documents = documents[: args.max_documents]
  selected_ids = {row.get("document_id") for row in documents}
  pages_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
  for page in pages:
    if page.get("document_id") in selected_ids:
      pages_by_doc[str(page["document_id"])].append(page)
  for page_list in pages_by_doc.values():
    page_list.sort(key=lambda row: row.get("page_number") or 0)

  titles = {str(row.get("document_id")): row.get("title") or str(row.get("document_id")) for row in documents}
  similar = build_similarity(edges, chunks, titles)

  summaries: list[dict[str, Any]] = []
  search_docs: list[dict[str, Any]] = []
  facets: dict[str, set[Any]] = {
    "languages": set(),
    "doc_types": set(),
    "years": set(),
    "instrument_types": set(),
    "legal_force": set(),
    "source_db": set(),
  }
  page_count = 0
  docs_dir = site / "docs"
  docs_dir.mkdir(parents=True, exist_ok=True)
  for stale in docs_dir.glob("*.json"):
    stale.unlink()

  for doc in documents:
    doc_id = str(doc.get("document_id"))
    doc_pages = pages_by_doc.get(doc_id, [])
    page_count += len(doc_pages)
    tags = [str(tag) for tag in as_list(doc.get("tags"))]
    languages = sorted(
      {
        str(language)
        for page in doc_pages
        for language in as_list(page.get("language"))
        if language
      }
    )
    if not languages:
      languages = sorted(str(tag).split(":", 1)[1] for tag in tags if str(tag).startswith("language:"))
    quality_scores = [
      float(page["quality_score"])
      for page in doc_pages
      if isinstance(page.get("quality_score"), (int, float))
    ]
    quality_score = round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else None
    review_required = bool(doc.get("review_required")) or any(bool(page.get("review_required")) for page in doc_pages)
    priorities = [str(page.get("review_priority")) for page in doc_pages if page.get("review_priority")]
    review_priority = "high" if "high" in priorities else ("normal" if review_required else "none")
    full_text = "\n\n".join(str(page.get("text") or "") for page in doc_pages).strip()
    preview = compact_text(full_text or doc.get("notes") or doc.get("title") or doc_id)
    doc_type = doc.get("doc_type") or tag_value(tags, "doc_type")
    year = doc.get("year")
    summary = {
      "document_id": doc_id,
      "title": doc.get("title") or doc_id,
      "year": year,
      "doc_type": doc_type,
      "languages": languages,
      "quality_score": quality_score,
      "review_required": review_required,
      "review_priority": review_priority,
      "text_preview": preview,
      "tags": tags,
      "source_url": doc.get("source_url"),
    }
    summaries.append(summary)

    for language in languages:
      facets["languages"].add(language)
    if doc_type:
      facets["doc_types"].add(doc_type)
    if year:
      facets["years"].add(int(year))
    for namespace in ("instrument_type", "legal_force", "source_db"):
      value = tag_value(tags, namespace)
      if value:
        facets[f"{namespace}s" if namespace == "instrument_type" else namespace].add(value)

    page_records = [
      {
        "page_number": page.get("page_number"),
        "text": page.get("text") or "",
        "quality_score": page.get("quality_score"),
        "review_required": page.get("review_required"),
        "review_priority": page.get("review_priority"),
        "method": page.get("method"),
        "language": as_list(page.get("language")),
        "review_reasons": as_list(page.get("review_reasons")),
      }
      for page in doc_pages
    ]
    write_json(
      docs_dir / f"{doc_id}.json",
      {
        **summary,
        "source_filename": doc.get("source_filename"),
        "source_sha256": doc.get("source_sha256"),
        "treaty_id": doc.get("treaty_id"),
        "treaty_number": doc.get("treaty_number"),
        "rights_status": doc.get("rights_status") or "to_review",
        "pages": page_records,
        "similar_documents": similar.get(doc_id, [])[:10],
      },
    )
    search_docs.append(
      {
        "id": doc_id,
        **summary,
        "summary": preview,
        "text": compact_text(full_text, limit=args.search_text_chars),
        "tags": " ".join(tags),
      }
    )

  summaries.sort(key=lambda row: (row.get("year") or 99999, row.get("title") or ""))
  graph_reduced = reduce_graph(graph, args.max_graph_nodes)
  manifest = {
    "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "source": str(release),
    "document_count": len(summaries),
    "page_count": page_count,
    "graph_node_count": len(graph_reduced.get("nodes", [])),
    "graph_edge_count": len(graph_reduced.get("edges", [])),
    "pipeline_version": documents[0].get("pipeline_version") if documents else None,
  }

  write_json(site / "manifest.json", manifest)
  write_json(site / "documents.json", summaries)
  write_json(site / "search.json", {"documents": search_docs})
  write_json(
    site / "facets.json",
    {
      "languages": sorted(facets["languages"]),
      "doc_types": sorted(facets["doc_types"]),
      "years": sorted(facets["years"]),
      "instrument_types": sorted(facets["instrument_types"]),
      "legal_force": sorted(facets["legal_force"]),
      "source_db": sorted(facets["source_db"]),
    },
  )
  write_json(site / "graph.sigma.json", graph_reduced)
  return manifest


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--release", default="outputs_v2/release_pilot", help="Release export directory.")
  parser.add_argument("--site", default="platform/site/public/data", help="Output data directory.")
  parser.add_argument("--max-documents", type=int, default=500, help="Maximum documents to include.")
  parser.add_argument("--max-graph-nodes", type=int, default=3000, help="Maximum graph nodes for the static view.")
  parser.add_argument("--search-text-chars", type=int, default=2200, help="Text characters per document in client search data.")
  return parser.parse_args()


def main() -> int:
  manifest = build(parse_args())
  print(json.dumps(manifest, ensure_ascii=False, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
