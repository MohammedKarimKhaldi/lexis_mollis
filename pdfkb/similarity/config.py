from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SimilarityConfig:
    model: str = "sentence-transformers/LaBSE"
    fallback_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    target_tokens: int = 384
    overlap_tokens: int = 64
    minhash_perm: int = 128
    char_ngram: int = 5
    lsh_threshold: float = 0.5
    knn: int = 20
    w_lexical: float = 0.5
    w_semantic: float = 0.5
    t_duplicate: float = 0.90
    t_clause_reuse: float = 0.60
    t_translation: float = 0.80
    t_weak_link: float = 0.70
    faiss_ivf_threshold: int = 500_000
    seed: int = 20260701
    batch_size: int = 64
    lexical_only: bool = False
    limit_pages: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

