#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pdfkb.similarity.io import read_parquet_records


BANDS = [
    ("very_high_ge_0_95", 0.95, 1.01),
    ("high_0_85_0_95", 0.85, 0.95),
    ("boundary_0_70_0_85", 0.70, 0.85),
    ("low_edge_lt_0_70", 0.0, 0.70),
]

FIELDNAMES = [
    "case_id",
    "score_band",
    "suggested_label",
    "src",
    "dst",
    "src_document_id",
    "dst_document_id",
    "src_title",
    "dst_title",
    "src_doc_type",
    "dst_doc_type",
    "src_year",
    "dst_year",
    "edge_type",
    "expected_type_suggestion",
    "combined",
    "lexical",
    "semantic",
    "quality_weight",
    "src_language",
    "dst_language",
    "src_excerpt",
    "dst_excerpt",
    "label",
    "expected_type",
    "notes",
]


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _excerpt(text: str, limit: int) -> str:
    text = _compact(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _year_group(year: Any) -> str:
    try:
        value = int(year)
    except (TypeError, ValueError):
        return "unknown"
    return f"{value // 100:02d}xx"


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _score(value: Any) -> float:
    return float(value or 0.0)


def _expected_type(edge_type: str | None) -> str:
    if edge_type == "same_instrument_as":
        return "duplicate"
    return edge_type or "null"


def _record(
    *,
    case_id: str,
    score_band: str,
    suggested_label: str,
    src: dict,
    dst: dict,
    edge: dict | None,
    excerpt_chars: int,
) -> dict[str, Any]:
    edge_type = edge.get("type") if edge else None
    return {
        "case_id": case_id,
        "score_band": score_band,
        "suggested_label": suggested_label,
        "src": src["chunk_id"],
        "dst": dst["chunk_id"],
        "src_document_id": src["document_id"],
        "dst_document_id": dst["document_id"],
        "src_title": src.get("title") or "",
        "dst_title": dst.get("title") or "",
        "src_doc_type": src.get("doc_type") or "",
        "dst_doc_type": dst.get("doc_type") or "",
        "src_year": src.get("year"),
        "dst_year": dst.get("year"),
        "edge_type": edge_type or "",
        "expected_type_suggestion": _expected_type(edge_type),
        "combined": round(_score(edge.get("combined") if edge else 0.0), 6),
        "lexical": round(_score(edge.get("lexical") if edge else 0.0), 6),
        "semantic": round(_score(edge.get("semantic") if edge else 0.0), 6),
        "quality_weight": round(_score(edge.get("quality_weight") if edge else min(src.get("quality_score") or 0, dst.get("quality_score") or 0)), 6),
        "src_language": "|".join(src.get("language") or []),
        "dst_language": "|".join(dst.get("language") or []),
        "src_excerpt": _excerpt(src.get("text") or "", excerpt_chars),
        "dst_excerpt": _excerpt(dst.get("text") or "", excerpt_chars),
        "label": "",
        "expected_type": "",
        "notes": "",
    }


def _sample_edges(
    edges: list[dict],
    chunks: dict[str, dict],
    *,
    per_band: int,
    rng: random.Random,
    excerpt_chars: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    used_doc_pairs: set[tuple[str, str]] = set()

    for band_name, low, high in BANDS:
        candidates = [
            edge
            for edge in edges
            if low <= _score(edge.get("combined")) < high
            and edge.get("src") in chunks
            and edge.get("dst") in chunks
            and chunks[edge["src"]].get("document_id") != chunks[edge["dst"]].get("document_id")
        ]
        candidates.sort(key=lambda edge: (-_score(edge.get("combined")), edge["src"], edge["dst"]))
        rng.shuffle(candidates)

        selected: list[dict] = []
        for edge in candidates:
            src = chunks[edge["src"]]
            dst = chunks[edge["dst"]]
            doc_pair = _pair_key(src["document_id"], dst["document_id"])
            if doc_pair in used_doc_pairs:
                continue
            used_doc_pairs.add(doc_pair)
            selected.append(edge)
            if len(selected) >= per_band:
                break

        for idx, edge in enumerate(selected, start=1):
            records.append(
                _record(
                    case_id=f"sim-{band_name}-{idx:03d}",
                    score_band=band_name,
                    suggested_label="review_edge_candidate",
                    src=chunks[edge["src"]],
                    dst=chunks[edge["dst"]],
                    edge=edge,
                    excerpt_chars=excerpt_chars,
                )
            )
    return records


def _representative_chunks(chunks: list[dict]) -> dict[str, dict]:
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        if len(_compact(chunk.get("text") or "")) >= 160:
            by_doc[chunk["document_id"]].append(chunk)
    reps: dict[str, dict] = {}
    for document_id, doc_chunks in by_doc.items():
        doc_chunks.sort(
            key=lambda chunk: (
                -float(chunk.get("quality_score") or 0),
                int(chunk.get("page_number") or 0),
                int(chunk.get("chunk_index") or 0),
                chunk["chunk_id"],
            )
        )
        reps[document_id] = doc_chunks[0]
    return reps


def _sample_no_edge_negatives(
    chunks: list[dict],
    edge_pairs: set[tuple[str, str]],
    *,
    count: int,
    rng: random.Random,
    excerpt_chars: int,
) -> list[dict[str, Any]]:
    reps = _representative_chunks(chunks)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for document_id, chunk in reps.items():
        group_key = (str(chunk.get("doc_type") or "Inconnu"), _year_group(chunk.get("year")))
        groups[group_key].append(document_id)

    viable_groups = [sorted(doc_ids) for doc_ids in groups.values() if len(doc_ids) >= 2]
    viable_groups.sort(key=lambda value: (len(value), value[0]), reverse=True)

    records: list[dict[str, Any]] = []
    used_doc_pairs: set[tuple[str, str]] = set()
    attempts = 0
    max_attempts = max(1000, count * 300)

    while len(records) < count and attempts < max_attempts and viable_groups:
        attempts += 1
        group = rng.choice(viable_groups)
        left_doc, right_doc = rng.sample(group, 2)
        doc_pair = _pair_key(left_doc, right_doc)
        if doc_pair in used_doc_pairs:
            continue
        left = reps[left_doc]
        right = reps[right_doc]
        chunk_pair = _pair_key(left["chunk_id"], right["chunk_id"])
        if chunk_pair in edge_pairs:
            continue
        used_doc_pairs.add(doc_pair)
        records.append(
            _record(
                case_id=f"sim-no_edge_negative-{len(records) + 1:03d}",
                score_band="no_edge_same_type_century",
                suggested_label="negative_candidate",
                src=left,
                dst=right,
                edge=None,
                excerpt_chars=excerpt_chars,
            )
        )

    return records


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(records)


def write_json(path: Path, records: list[dict[str, Any]], args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cases = [
        {
            "case_id": record["case_id"],
            "src": record["src"],
            "dst": record["dst"],
            "label": "",
            "expected_type": "",
            "notes": "",
            "suggested_label": record["suggested_label"],
            "expected_type_suggestion": record["expected_type_suggestion"],
            "score_band": record["score_band"],
            "doc_titles": [record["src_title"], record["dst_title"]],
            "scores": {
                "combined": record["combined"],
                "lexical": record["lexical"],
                "semantic": record["semantic"],
            },
            "excerpts": {
                "src": record["src_excerpt"],
                "dst": record["dst_excerpt"],
            },
        }
        for record in records
    ]
    payload = {
        "schema_version": "0.1-draft",
        "description": "Human review candidates for similarity calibration. Copy validated cases into benchmarks/similarity_cases.json with label positive/negative and expected_type.",
        "source_similarity_dir": str(args.similarity_dir),
        "seed": args.seed,
        "positive_edge_candidates_per_band": args.edge_candidates_per_band,
        "negative_no_edge_candidates": args.no_edge_negatives,
        "cases": cases,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample human-readable candidates for similarity calibration.")
    parser.add_argument("--similarity-dir", type=Path, default=Path("outputs_v2/similarity"))
    parser.add_argument("--output-csv", type=Path, default=Path("outputs_v2/similarity/calibration_candidates.csv"))
    parser.add_argument("--output-json", type=Path, default=Path("outputs_v2/similarity/calibration_candidates.json"))
    parser.add_argument("--edge-candidates-per-band", type=int, default=20)
    parser.add_argument("--no-edge-negatives", type=int, default=40)
    parser.add_argument("--excerpt-chars", type=int, default=700)
    parser.add_argument("--seed", type=int, default=20260701)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    chunks_list = read_parquet_records(args.similarity_dir / "chunks.parquet")
    chunks = {chunk["chunk_id"]: chunk for chunk in chunks_list}
    edges = read_parquet_records(args.similarity_dir / "edges.parquet")
    edge_pairs = {_pair_key(edge["src"], edge["dst"]) for edge in edges}

    records = _sample_edges(
        edges,
        chunks,
        per_band=args.edge_candidates_per_band,
        rng=rng,
        excerpt_chars=args.excerpt_chars,
    )
    records.extend(
        _sample_no_edge_negatives(
            chunks_list,
            edge_pairs,
            count=args.no_edge_negatives,
            rng=rng,
            excerpt_chars=args.excerpt_chars,
        )
    )

    write_csv(args.output_csv, records)
    write_json(args.output_json, records, args)
    summary = {
        "records": len(records),
        "csv": str(args.output_csv),
        "json": str(args.output_json),
        "by_band": {band: sum(1 for record in records if record["score_band"] == band) for band, *_ in BANDS}
        | {"no_edge_same_type_century": sum(1 for record in records if record["score_band"] == "no_edge_same_type_century")},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
