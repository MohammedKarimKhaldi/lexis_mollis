from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
import re
from typing import Any

from pdfkb.ids import chunk_id as make_chunk_id
from pdfkb.ids import text_sha256

from .config import SimilarityConfig
from .io import read_jsonl, write_parquet_records


TOKEN_RE = re.compile(r"\S+")


def quality_band(score: float) -> str:
    if score >= 0.85:
        return "accepted_ge_0_85"
    if score >= 0.65:
        return "review_0_65_0_85"
    return "priority_review_lt_0_65"


def _token_offsets_regex(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in TOKEN_RE.finditer(text)]


def token_offsets(text: str, tokenizer: Any | None) -> list[tuple[int, int]]:
    if not text:
        return []
    if tokenizer is not None:
        try:
            encoded = tokenizer(
                text,
                add_special_tokens=False,
                return_offsets_mapping=True,
                truncation=False,
            )
            offsets = encoded.get("offset_mapping") if isinstance(encoded, dict) else None
            if offsets:
                clean_offsets = [(int(start), int(end)) for start, end in offsets if int(end) > int(start)]
                if clean_offsets:
                    return clean_offsets
        except Exception:
            pass
    return _token_offsets_regex(text)


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int, str]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end, text[start:end]


def _page_tags(page: dict) -> list[str]:
    tags = set(page.get("tags") or [])
    for lang in page.get("language") or []:
        if lang:
            tags.add(f"language:{lang}")
    for script in page.get("script") or []:
        if script:
            tags.add(f"script:{script}")
    score = float(page.get("quality_score") or 0)
    tags.add(f"quality:{quality_band(score)}")
    review_priority = page.get("review_priority") or ("normal" if page.get("review_required") else "none")
    if page.get("review_required"):
        tags.add("review:required_high" if review_priority == "high" else "review:required_normal")
    else:
        tags.add("review:not_required")
    return sorted(tags)


def chunk_pages(pages: Iterable[dict], cfg: SimilarityConfig, tokenizer: Any | None) -> Iterator[dict]:
    if cfg.target_tokens <= 0:
        raise ValueError("target_tokens must be > 0")
    if cfg.overlap_tokens < 0:
        raise ValueError("overlap_tokens must be >= 0")
    step = max(1, cfg.target_tokens - min(cfg.overlap_tokens, cfg.target_tokens - 1))

    for page in pages:
        text = page.get("text") or ""
        if not text.strip():
            continue
        offsets = token_offsets(text, tokenizer)
        if not offsets:
            continue

        chunk_index = 0
        start_token = 0
        while start_token < len(offsets):
            end_token = min(len(offsets), start_token + cfg.target_tokens)
            char_start = offsets[start_token][0]
            char_end = offsets[end_token - 1][1]
            char_start, char_end, chunk_text = _trimmed_span(text, char_start, char_end)
            if chunk_text:
                yield {
                    "chunk_id": make_chunk_id(page["source_sha256"], int(page["page_number"]), chunk_index),
                    "source_sha256": page["source_sha256"],
                    "document_id": page["document_id"],
                    "source_filename": page.get("source_filename") or "",
                    "title": page.get("title") or "",
                    "treaty_id": page.get("treaty_id"),
                    "year": page.get("year"),
                    "doc_type": page.get("doc_type") or "Inconnu",
                    "page_number": int(page["page_number"]),
                    "chunk_index": chunk_index,
                    "char_start": char_start,
                    "char_end": char_end,
                    "text": chunk_text,
                    "text_sha256": text_sha256(chunk_text),
                    "language": list(page.get("language") or []),
                    "script": list(page.get("script") or []),
                    "quality_score": float(page.get("quality_score") or 0),
                    "review_required": bool(page.get("review_required")),
                    "review_priority": page.get("review_priority") or "none",
                    "embedding_model": None,
                    "embedding_created_at": None,
                    "pipeline_version": page.get("pipeline_version") or "",
                    "tags": _page_tags(page),
                }
                chunk_index += 1
            if end_token >= len(offsets):
                break
            start_token += step


def chunks_from_jsonl(kb: Path, cfg: SimilarityConfig, tokenizer: Any | None, out_dir: Path) -> Path:
    pages = read_jsonl(kb, limit=cfg.limit_pages)
    chunks = list(chunk_pages(pages, cfg, tokenizer))
    return write_parquet_records(chunks, out_dir / "chunks.parquet")

