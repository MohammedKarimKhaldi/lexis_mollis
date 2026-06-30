from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .chunking import chunks_from_jsonl
from .config import SimilarityConfig
from .embeddings import embed_chunks
from .graph import cluster_documents, document_edges
from .index import semantic_pairs
from .io import read_parquet_records, write_parquet_records
from .lexical import lexical_pairs
from .pairs import fuse_pairs


class RegexTokenizer:
    """Small deterministic fallback tokenizer used only when model tokenizers are unavailable."""

    def __call__(self, text: str, **_: Any) -> dict[str, list]:
        import re

        offsets = [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}


def load_tokenizer(cfg: SimilarityConfig) -> tuple[Any, str]:
    try:
        from transformers import AutoTokenizer

        try:
            return AutoTokenizer.from_pretrained(cfg.model), cfg.model
        except Exception:
            return AutoTokenizer.from_pretrained(cfg.fallback_model), cfg.fallback_model
    except Exception:
        return RegexTokenizer(), "regex_fallback"


def _empty_semantic(out_dir: Path) -> Path:
    return write_parquet_records([], out_dir / "semantic_pairs.parquet")


def build(kb: Path, output: Path, cfg: SimilarityConfig) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if cfg.lexical_only:
        tokenizer, tokenizer_name = RegexTokenizer(), "regex_fallback"
    else:
        tokenizer, tokenizer_name = load_tokenizer(cfg)
    chunks_pq = chunks_from_jsonl(kb, cfg, tokenizer, output)
    lexical_pq = lexical_pairs(chunks_pq, cfg, output)

    embedding_manifest: dict[str, Any] = {
        "lexical_only": cfg.lexical_only,
        "embedding_model": None,
        "encoded_count": 0,
        "embedding_dim": 0,
    }
    if cfg.lexical_only:
        semantic_pq = _empty_semantic(output)
    else:
        store = embed_chunks(chunks_pq, cfg, output)
        semantic_pq = semantic_pairs(store.embeddings_path, store.index_path, cfg, output)
        embedding_manifest = {
            "lexical_only": False,
            "embedding_model": store.model_name,
            "encoded_count": store.encoded_count,
            "embedding_dim": store.dim,
        }

    edges_pq = fuse_pairs(lexical_pq, semantic_pq, chunks_pq, cfg, output)
    doc_edges_pq = document_edges(edges_pq, chunks_pq, cfg, output)
    clusters_path, summary_path = cluster_documents(doc_edges_pq, cfg, output, chunks_pq=chunks_pq)

    chunks = read_parquet_records(chunks_pq)
    lexical = read_parquet_records(lexical_pq)
    semantic = read_parquet_records(semantic_pq)
    edges = read_parquet_records(edges_pq)
    doc_edges = read_parquet_records(doc_edges_pq)

    run_config_path = output / "run_config.json"
    run_config = cfg.to_dict() | {"tokenizer": tokenizer_name}
    run_config_path.write_text(json.dumps(run_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "chunks": len(chunks),
        "lexical_pairs": len(lexical),
        "semantic_pairs": len(semantic),
        "chunk_edges": len(edges),
        "document_edges": len(doc_edges),
        "clusters_path": str(clusters_path),
        "summary_path": str(summary_path),
        "run_config": str(run_config_path),
        **embedding_manifest,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
