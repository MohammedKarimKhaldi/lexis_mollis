from __future__ import annotations

from pathlib import Path
import re
import unicodedata

from datasketch import MinHash, MinHashLSH

from .config import SimilarityConfig
from .io import read_parquet_records, write_parquet_records


ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalise_lexical(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = ALNUM_RE.sub(" ", normalized)
    return " ".join(normalized.split())


def char_ngrams(text: str, n: int) -> set[str]:
    clean = normalise_lexical(text)
    compact = clean.replace(" ", "")
    if not compact:
        return set()
    if len(compact) <= n:
        return {compact}
    return {compact[i : i + n] for i in range(len(compact) - n + 1)}


def _minhash(grams: set[str], cfg: SimilarityConfig) -> MinHash:
    signature = MinHash(num_perm=cfg.minhash_perm, seed=cfg.seed)
    for gram in sorted(grams):
        signature.update(gram.encode("utf-8"))
    return signature


def lexical_pairs(chunks_pq: Path, cfg: SimilarityConfig, out_dir: Path) -> Path:
    chunks = read_parquet_records(chunks_pq)
    signatures: dict[str, MinHash] = {}
    lsh = MinHashLSH(threshold=cfg.lsh_threshold, num_perm=cfg.minhash_perm)

    for chunk in chunks:
        grams = char_ngrams(chunk.get("text") or "", cfg.char_ngram)
        if not grams:
            continue
        chunk_key = chunk["chunk_id"]
        signature = _minhash(grams, cfg)
        signatures[chunk_key] = signature
        lsh.insert(chunk_key, signature)

    pairs: dict[tuple[str, str], float] = {}
    for src, signature in signatures.items():
        for dst in lsh.query(signature):
            if src == dst:
                continue
            a, b = sorted((src, dst))
            if (a, b) not in pairs:
                pairs[(a, b)] = float(signatures[a].jaccard(signatures[b]))

    records = [
        {"src": src, "dst": dst, "jaccard": round(score, 6)}
        for (src, dst), score in sorted(pairs.items())
    ]
    return write_parquet_records(records, out_dir / "lexical_pairs.parquet")
