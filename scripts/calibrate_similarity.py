#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from pdfkb.similarity.config import SimilarityConfig
from pdfkb.similarity.io import read_parquet_records
from pdfkb.similarity.pairs import _edge_type


DEFAULT_WEIGHTS = [(0.5, 0.5), (0.6, 0.4), (0.4, 0.6)]
DEFAULT_DUPLICATE = [0.88, 0.90, 0.92]
DEFAULT_CLAUSE = [0.55, 0.60, 0.65]
DEFAULT_TRANSLATION = [0.78, 0.80, 0.82]
DEFAULT_WEAK = [0.68, 0.70, 0.72]


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError(f"{path}: 'cases' must be a list")
    return cases


def load_scores(similarity_dir: Path) -> dict[tuple[str, str], dict[str, float]]:
    scores: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"lexical": 0.0, "semantic": 0.0})
    for row in read_parquet_records(similarity_dir / "lexical_pairs.parquet"):
        a, b = sorted((row["src"], row["dst"]))
        scores[(a, b)]["lexical"] = float(row.get("jaccard") or 0)
    for row in read_parquet_records(similarity_dir / "semantic_pairs.parquet"):
        a, b = sorted((row["src"], row["dst"]))
        scores[(a, b)]["semantic"] = float(row.get("cosine") or 0)
    return dict(scores)


def load_chunks(similarity_dir: Path) -> dict[str, dict]:
    return {row["chunk_id"]: row for row in read_parquet_records(similarity_dir / "chunks.parquet")}


def score_config(cases: list[dict[str, Any]], scores: dict[tuple[str, str], dict[str, float]], chunks: dict[str, dict], cfg: SimilarityConfig) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    by_type: dict[str, Counter] = defaultdict(Counter)
    missing_pairs = 0

    for case in cases:
        a, b = sorted((case["src"], case["dst"]))
        pair_scores = scores.get((a, b), {"lexical": 0.0, "semantic": 0.0})
        if (a, b) not in scores:
            missing_pairs += 1
        left = chunks.get(a, {"language": []})
        right = chunks.get(b, {"language": []})
        predicted = _edge_type(pair_scores["lexical"], pair_scores["semantic"], left, right, cfg)
        label = case.get("label")
        expected = case.get("expected_type")

        if label == "negative":
            if predicted is None:
                tn += 1
                by_type["negative"]["tn"] += 1
            else:
                fp += 1
                by_type[predicted]["fp"] += 1
        elif label == "positive":
            if predicted == expected or expected == "any":
                tp += 1
                by_type[str(expected)]["tp"] += 1
            else:
                fn += 1
                by_type[str(expected)]["fn"] += 1
                if predicted is not None:
                    fp += 1
                    by_type[predicted]["fp"] += 1
        else:
            raise ValueError(f"{case.get('case_id', '<unknown>')}: label must be positive or negative")

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "missing_pairs": missing_pairs,
        "by_type": {key: dict(value) for key, value in sorted(by_type.items())},
    }


def sweep(cases: list[dict[str, Any]], scores: dict[tuple[str, str], dict[str, float]], chunks: dict[str, dict]) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    for w_lexical, w_semantic in DEFAULT_WEIGHTS:
        for duplicate in DEFAULT_DUPLICATE:
            for clause in DEFAULT_CLAUSE:
                if clause >= duplicate:
                    continue
                for translation in DEFAULT_TRANSLATION:
                    for weak in DEFAULT_WEAK:
                        if weak >= translation:
                            continue
                        cfg = replace(
                            SimilarityConfig(),
                            w_lexical=w_lexical,
                            w_semantic=w_semantic,
                            t_duplicate=duplicate,
                            t_clause_reuse=clause,
                            t_translation=translation,
                            t_weak_link=weak,
                        )
                        result = score_config(cases, scores, chunks, cfg)
                        candidate = {"config": cfg.to_dict(), **result}
                        if best is None or (candidate["f1"], candidate["precision"], candidate["recall"]) > (
                            best["f1"],
                            best["precision"],
                            best["recall"],
                        ):
                            best = candidate
    assert best is not None
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate Lexis Mollis similarity thresholds on human annotations.")
    parser.add_argument("--cases", type=Path, default=Path("benchmarks/similarity_cases.json"))
    parser.add_argument("--similarity-dir", type=Path, default=Path("outputs_v2/similarity"))
    parser.add_argument("--output", type=Path, default=Path("outputs_v2/similarity/calibration_report.json"))
    args = parser.parse_args()

    cases = load_cases(args.cases)
    positive = sum(1 for case in cases if case.get("label") == "positive")
    negative = sum(1 for case in cases if case.get("label") == "negative")
    report: dict[str, Any] = {
        "cases": len(cases),
        "positive": positive,
        "negative": negative,
        "minimum_positive": 30,
        "minimum_negative": 30,
    }

    if positive < 30 or negative < 30:
        report["status"] = "insufficient_annotations"
        report["message"] = "Add at least 30 positive and 30 negative human-validated real pairs before claiming calibrated thresholds."
    else:
        scores = load_scores(args.similarity_dir)
        chunks = load_chunks(args.similarity_dir)
        report["status"] = "calibrated"
        report["best"] = sweep(cases, scores, chunks)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

