#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from jsonschema import Draft202012Validator

from pdfkb import PIPELINE_VERSION
from pdfkb.ids import text_sha256
from pdfkb.similarity.io import read_jsonl, read_parquet_records, write_parquet_records


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "metadata_design"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_mapping() -> dict[str, dict]:
    return load_json(SCHEMAS / "doc_type_mapping.json").get("mappings", {})


def period_from_year(year: int | None) -> str:
    if year is None:
        return "unknown"
    if 1516 <= year <= 1788:
        return "early_modern_1516_1788"
    if 1789 <= year <= 1815:
        return "revolutionary_napoleonic_1789_1815"
    if 1816 <= year <= 1913:
        return "nineteenth_century_1816_1913"
    if 1914 <= year <= 1938:
        return "world_war_i_and_interwar_1914_1938"
    if 1939 <= year <= 1989:
        return "world_war_ii_and_postwar_1939_1989"
    if year >= 1990:
        return "contemporary_1990_present"
    return "unknown"


def century_from_year(year: int | None) -> str:
    if year is None:
        return "unknown"
    century = (year - 1) // 100 + 1
    if 16 <= century <= 21:
        return f"c{century}"
    return "unknown"


def quality_band(score: float) -> str:
    if score >= 0.85:
        return "accepted_ge_0_85"
    if score >= 0.65:
        return "review_0_65_0_85"
    return "priority_review_lt_0_65"


def page_tags(page: dict) -> list[str]:
    tags = set(page.get("tags") or [])
    for lang in page.get("language") or []:
        tags.add(f"language:{lang}")
    for script in page.get("script") or []:
        tags.add(f"script:{script}")
    method = str(page.get("method") or "unknown")
    if method.startswith("native"):
        tags.add("ocr_method:native_pymupdf")
    elif method.startswith("apple"):
        tags.add("ocr_method:apple_vision")
    elif method.startswith("tesseract"):
        tags.add("ocr_method:tesseract")
    else:
        tags.add("ocr_method:unknown")
    tags.add(f"quality:{quality_band(float(page.get('quality_score') or 0))}")
    if page.get("review_required"):
        tags.add("review:required_high" if page.get("review_priority") == "high" else "review:required_normal")
    else:
        tags.add("review:not_required")
    return sorted(tags)


def document_tags(doc_type: str, year: int | None, mapping: dict[str, dict]) -> list[str]:
    mapped = mapping.get(doc_type, {"instrument_type": "unknown", "legal_force": "unknown"})
    return sorted(
        {
            "corpus:traites",
            "stage:live_snapshot",
            f"doc_type:{doc_type}",
            f"instrument_type:{mapped.get('instrument_type', 'unknown')}",
            f"legal_force:{mapped.get('legal_force', 'unknown')}",
            "source_db:traites_mineae",
            f"period:{period_from_year(year)}",
            f"century:{century_from_year(year)}",
            "rights_status:to_review",
        }
    )


def build_documents(pages: list[dict], mapping: dict[str, dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for page in pages:
        grouped[page["document_id"]].append(page)

    docs: list[dict] = []
    for document_id, doc_pages in sorted(grouped.items()):
        first = doc_pages[0]
        metadata = (first.get("metadata_records") or [{}])[0]
        doc_type = first.get("doc_type") or "Inconnu"
        year = first.get("year")
        docs.append(
            {
                "schema_version": "0.1-draft",
                "document_id": document_id,
                "source_filename": first.get("source_filename") or "",
                "canonical_filename": first.get("canonical_filename") or first.get("source_filename") or "",
                "source_sha256": first["source_sha256"],
                "source_url": metadata.get("url"),
                "treaty_id": first.get("treaty_id"),
                "treaty_number": first.get("treaty_number"),
                "title": first.get("title") or document_id,
                "doc_type": doc_type,
                "year": year,
                "page_count": int(first.get("page_count") or len(doc_pages)),
                "file_size_bytes": metadata.get("file_size"),
                "aliases": sorted({page.get("source_filename") for page in doc_pages if page.get("source_filename")}),
                "pipeline_version": first.get("pipeline_version") or PIPELINE_VERSION,
                "rights_status": "to_review",
                "tags": document_tags(doc_type, year, mapping),
                "notes": None,
            }
        )
    return docs


def prepare_pages(pages: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for page in pages:
        row = dict(page)
        row.setdefault("quality_band", quality_band(float(row.get("quality_score") or 0)))
        row.setdefault("review_priority", "normal" if row.get("review_required") else "none")
        row.setdefault("review_reasons", [])
        row.setdefault("text_sha256", text_sha256(row.get("text") or ""))
        row["tags"] = page_tags(row)
        rows.append(row)
    return rows


def read_optional_parquet(path: Path) -> list[dict]:
    return read_parquet_records(path) if path.exists() else []


def dedupe_edges(rows: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for row in rows:
        key = (row.get("src"), row.get("dst"), row.get("level"), row.get("type"), row.get("method"))
        seen.setdefault(key, row)
    return sorted(seen.values(), key=lambda row: (row.get("level") or "", row.get("type") or "", row.get("src") or "", row.get("dst") or ""))


def validate_rows(rows: list[dict], schema_name: str) -> None:
    schema = load_json(SCHEMAS / schema_name)
    validator = Draft202012Validator(schema)
    for index, row in enumerate(rows):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            error = errors[0]
            path = ".".join(str(part) for part in error.path) or "<root>"
            raise ValueError(f"{schema_name} row {index} invalid at {path}: {error.message}")


def write_table(name: str, rows: list[dict], output: Path) -> Path:
    table_dir = output / name
    if table_dir.exists():
        shutil.rmtree(table_dir)
    table_dir.mkdir(parents=True)
    return write_parquet_records(rows, table_dir / "part-000.parquet")


def checksums(output: Path) -> dict[str, str]:
    digest_by_path: dict[str, str] = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "CHECKSUMS.sha256":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            digest_by_path[str(path.relative_to(output))] = digest
    lines = [f"{digest}  {rel}" for rel, digest in sorted(digest_by_path.items())]
    (output / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return digest_by_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Lexis Mollis release Parquet tables.")
    parser.add_argument("--kb", type=Path, default=Path("outputs_v2/kb/pages.jsonl"))
    parser.add_argument("--similarity", type=Path, default=Path("outputs_v2/similarity"))
    parser.add_argument("--graph", type=Path, default=Path("outputs_v2/graph"))
    parser.add_argument("--output", type=Path, default=Path("outputs_v2/release"))
    parser.add_argument("--scope", default="live_snapshot")
    args = parser.parse_args()

    pages = prepare_pages(read_jsonl(args.kb))
    mapping = load_mapping()
    documents = build_documents(pages, mapping)
    chunks = read_optional_parquet(args.similarity / "chunks.parquet")
    edges = dedupe_edges(
        read_optional_parquet(args.similarity / "edges.parquet")
        + read_optional_parquet(args.similarity / "doc_edges.parquet")
        + read_optional_parquet(args.graph / "edges.parquet")
    )
    nodes = read_optional_parquet(args.graph / "nodes.parquet")

    validate_rows(documents, "document.schema.json")
    validate_rows(pages[:1000], "page.schema.json")
    if chunks:
        validate_rows(chunks[:1000], "chunk.schema.json")
    if edges:
        validate_rows(edges[:1000], "edge.schema.json")
    if nodes:
        validate_rows(nodes[:1000], "node.schema.json")

    args.output.mkdir(parents=True, exist_ok=True)
    written = {
        "documents": write_table("documents", documents, args.output),
        "pages": write_table("pages", pages, args.output),
    }
    if chunks:
        written["chunks"] = write_table("chunks", chunks, args.output)
    if edges:
        written["edges"] = write_table("edges", edges, args.output)
    if nodes:
        written["nodes"] = write_table("nodes", nodes, args.output)

    graph_dir = args.output / "graph"
    if graph_dir.exists():
        shutil.rmtree(graph_dir)
    graph_dir.mkdir()
    for name in ["graph.ttl", "graph.jsonld", "graph.sigma.json", "summary.json"]:
        src = args.graph / name
        if src.exists():
            shutil.copy2(src, graph_dir / name)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pipeline_version": PIPELINE_VERSION,
        "scope": args.scope,
        "tables": {
            "documents": len(documents),
            "pages": len(pages),
            "chunks": len(chunks),
            "edges": len(edges),
            "nodes": len(nodes),
        },
        "paths": {key: str(path) for key, path in written.items()},
    }
    (args.output / "release_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["checksums"] = checksums(args.output)
    (args.output / "release_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

