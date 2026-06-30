from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import SimilarityConfig
from .io import read_parquet_records, write_parquet_records


def _normalise(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def build_index(embeddings_npy: Path, embeddings_index_pq: Path, cfg: SimilarityConfig, out_dir: Path) -> Path:
    import faiss

    out_dir.mkdir(parents=True, exist_ok=True)
    vectors = np.load(embeddings_npy).astype(np.float32)
    if vectors.size == 0:
        vectors = vectors.reshape(0, 0)
    if vectors.ndim != 2:
        raise ValueError("embeddings.npy must be a 2D array")

    index_path = out_dir / "faiss.index"
    id_map_path = out_dir / "id_map.parquet"
    id_map = read_parquet_records(embeddings_index_pq)
    write_parquet_records(id_map, id_map_path)

    dim = int(vectors.shape[1]) if len(vectors) else 1
    index = faiss.IndexFlatIP(dim)
    if len(vectors):
        index.add(_normalise(vectors))
    faiss.write_index(index, str(index_path))
    return index_path


def semantic_pairs(embeddings_npy: Path, embeddings_index_pq: Path, cfg: SimilarityConfig, out_dir: Path) -> Path:
    import faiss

    index_path = build_index(embeddings_npy, embeddings_index_pq, cfg, out_dir)
    vectors = np.load(embeddings_npy).astype(np.float32)
    id_rows = read_parquet_records(embeddings_index_pq)
    pairs: dict[tuple[str, str], float] = {}

    if len(vectors) > 1:
        vectors = _normalise(vectors)
        index = faiss.read_index(str(index_path))
        k = min(len(vectors), max(2, cfg.knn + 1))
        scores, indices = index.search(vectors, k)
        for src_row, (row_scores, row_indices) in enumerate(zip(scores, indices, strict=True)):
            src = id_rows[src_row]["chunk_id"]
            for score, dst_row in zip(row_scores, row_indices, strict=True):
                if dst_row < 0 or int(dst_row) == src_row:
                    continue
                dst = id_rows[int(dst_row)]["chunk_id"]
                a, b = sorted((src, dst))
                score_value = float(score)
                previous = pairs.get((a, b))
                if previous is None or score_value > previous:
                    pairs[(a, b)] = score_value

    records = [
        {"src": src, "dst": dst, "cosine": round(score, 6)}
        for (src, dst), score in sorted(pairs.items())
    ]
    return write_parquet_records(records, out_dir / "semantic_pairs.parquet")

