from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .config import SimilarityConfig
from .io import read_parquet_records, write_parquet_records


@dataclass(frozen=True)
class EmbeddingStore:
    embeddings_path: Path
    index_path: Path
    cache_index_path: Path
    cache_vectors_path: Path
    model_name: str
    count: int
    dim: int
    encoded_count: int


def _normalise(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim == 1:
        vectors = vectors.reshape(1, -1)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _load_model(cfg: SimilarityConfig) -> tuple[Any, str]:
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(cfg.model), cfg.model
    except Exception:
        return SentenceTransformer(cfg.fallback_model), cfg.fallback_model


def _read_cache(index_path: Path, vectors_path: Path) -> tuple[list[dict], np.ndarray | None]:
    if not index_path.exists() or not vectors_path.exists():
        return [], None
    rows = read_parquet_records(index_path)
    vectors = np.load(vectors_path)
    return rows, np.asarray(vectors, dtype=np.float32)


def embed_chunks(
    chunks_pq: Path,
    cfg: SimilarityConfig,
    out_dir: Path,
    model_factory: Callable[[SimilarityConfig], tuple[Any, str]] | None = None,
) -> EmbeddingStore:
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = read_parquet_records(chunks_pq)
    embeddings_path = out_dir / "embeddings.npy"
    index_path = out_dir / "embeddings_index.parquet"
    cache_index_path = out_dir / "embeddings_cache.parquet"
    cache_vectors_path = out_dir / "embeddings_cache.npy"

    if not chunks:
        np.save(embeddings_path, np.zeros((0, 0), dtype=np.float32))
        write_parquet_records([], index_path)
        write_parquet_records([], cache_index_path)
        np.save(cache_vectors_path, np.zeros((0, 0), dtype=np.float32))
        return EmbeddingStore(embeddings_path, index_path, cache_index_path, cache_vectors_path, cfg.model, 0, 0, 0)

    model, model_name = (model_factory or _load_model)(cfg)
    cache_rows, cache_vectors = _read_cache(cache_index_path, cache_vectors_path)
    cache_by_hash = {row["text_sha256"]: int(row["cache_row"]) for row in cache_rows if row.get("embedding_model") == model_name}

    unique_texts: dict[str, str] = {}
    for chunk in chunks:
        unique_texts.setdefault(chunk["text_sha256"], chunk["text"])

    missing = [(sha, text) for sha, text in unique_texts.items() if sha not in cache_by_hash]
    encoded_count = len(missing)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if missing:
        encoded = model.encode(
            [text for _, text in missing],
            batch_size=cfg.batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        encoded_vectors = _normalise(np.asarray(encoded, dtype=np.float32))
        if cache_vectors is None or cache_vectors.size == 0:
            cache_vectors = encoded_vectors
        else:
            cache_vectors = np.vstack([cache_vectors, encoded_vectors])
        start = len(cache_rows)
        for offset, (sha, _) in enumerate(missing):
            row = start + offset
            cache_rows.append(
                {
                    "text_sha256": sha,
                    "cache_row": row,
                    "embedding_model": model_name,
                    "embedding_created_at": now,
                }
            )
            cache_by_hash[sha] = row
    elif cache_vectors is None:
        cache_vectors = np.zeros((0, 0), dtype=np.float32)

    assert cache_vectors is not None
    full_vectors = np.vstack([cache_vectors[cache_by_hash[chunk["text_sha256"]]] for chunk in chunks]).astype(np.float32)
    full_vectors = _normalise(full_vectors)

    np.save(embeddings_path, full_vectors)
    np.save(cache_vectors_path, cache_vectors.astype(np.float32))
    write_parquet_records(cache_rows, cache_index_path)
    write_parquet_records(
        [
            {
                "row_index": i,
                "chunk_id": chunk["chunk_id"],
                "text_sha256": chunk["text_sha256"],
            }
            for i, chunk in enumerate(chunks)
        ],
        index_path,
    )

    cache_meta_by_hash = {row["text_sha256"]: row for row in cache_rows if row.get("embedding_model") == model_name}
    for chunk in chunks:
        meta = cache_meta_by_hash[chunk["text_sha256"]]
        chunk["embedding_model"] = model_name
        chunk["embedding_created_at"] = meta["embedding_created_at"]
    write_parquet_records(chunks, chunks_pq)

    return EmbeddingStore(
        embeddings_path=embeddings_path,
        index_path=index_path,
        cache_index_path=cache_index_path,
        cache_vectors_path=cache_vectors_path,
        model_name=model_name,
        count=len(chunks),
        dim=int(full_vectors.shape[1]) if full_vectors.ndim == 2 else 0,
        encoded_count=encoded_count,
    )

