from __future__ import annotations

from pathlib import Path

from pdfkb import PIPELINE_VERSION

from .config import SimilarityConfig
from .io import read_parquet_records, write_parquet_records


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _language_differs(left: dict, right: dict) -> bool:
    left_langs = {lang for lang in left.get("language") or [] if lang}
    right_langs = {lang for lang in right.get("language") or [] if lang}
    return bool(left_langs and right_langs and left_langs.isdisjoint(right_langs))


def _edge_type(jaccard: float, cosine: float, left: dict, right: dict, cfg: SimilarityConfig) -> str | None:
    if jaccard >= cfg.t_duplicate:
        return "duplicate"
    if jaccard >= cfg.t_clause_reuse:
        return "clause_reuse"
    if cosine >= cfg.t_translation:
        return "translation" if _language_differs(left, right) else "semantic_kin"
    if cosine >= cfg.t_weak_link:
        return "weak_link"
    return None


def fuse_pairs(lexical_pq: Path, semantic_pq: Path, chunks_pq: Path, cfg: SimilarityConfig, out_dir: Path) -> Path:
    chunks = {chunk["chunk_id"]: chunk for chunk in read_parquet_records(chunks_pq)}
    pair_scores: dict[tuple[str, str], dict[str, float]] = {}

    for row in read_parquet_records(lexical_pq):
        a, b = sorted((row["src"], row["dst"]))
        pair_scores.setdefault((a, b), {})["lexical"] = float(row.get("jaccard") or 0)

    for row in read_parquet_records(semantic_pq):
        a, b = sorted((row["src"], row["dst"]))
        pair_scores.setdefault((a, b), {})["semantic"] = float(row.get("cosine") or 0)

    records: list[dict] = []
    for (src, dst), scores in sorted(pair_scores.items()):
        if src == dst or src not in chunks or dst not in chunks:
            continue
        left = chunks[src]
        right = chunks[dst]
        lexical = _clamp01(float(scores.get("lexical", 0.0)))
        semantic = _clamp01(float(scores.get("semantic", 0.0)))
        edge_type = _edge_type(lexical, semantic, left, right, cfg)
        if edge_type is None:
            continue
        combined = _clamp01(cfg.w_lexical * lexical + cfg.w_semantic * semantic)
        quality_weight = _clamp01(min(float(left.get("quality_score") or 0), float(right.get("quality_score") or 0)))
        provisional = bool(left.get("review_required") or right.get("review_required"))
        records.append(
            {
                "src": src,
                "dst": dst,
                "level": "chunk",
                "type": edge_type,
                "lexical": round(lexical, 6),
                "semantic": round(semantic, 6),
                "combined": round(combined, 6),
                "quality_weight": round(quality_weight, 6),
                "provisional": provisional,
                "method": "minhash_lsh+faiss" if semantic else "minhash_lsh",
                "evidence": "chunk_pair",
                "pipeline_version": left.get("pipeline_version") or right.get("pipeline_version") or PIPELINE_VERSION,
            }
        )

    return write_parquet_records(records, out_dir / "edges.parquet")
