from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import fitz

from .models import DocumentRecord


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_metadata(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    by_filename: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        filename = str(record.get("filename", ""))
        if filename:
            by_filename[filename.casefold()].append(record)
    return dict(by_filename)


def inventory_documents(
    source: Path,
    metadata_path: Path,
    selected: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[DocumentRecord]:
    metadata = load_metadata(metadata_path)
    pdfs = sorted(
        (p for p in source.iterdir() if p.is_file() and p.suffix.casefold() == ".pdf"),
        key=lambda p: p.name.casefold(),
    )
    if selected:
        wanted = {item.casefold() for item in selected}
        pdfs = [p for p in pdfs if p.name.casefold() in wanted or p.stem.casefold() in wanted]
    if limit is not None:
        pdfs = pdfs[:limit]

    preliminary: list[tuple[Path, str, int]] = []
    canonical_by_hash: dict[str, str] = {}
    for path in pdfs:
        digest = sha256_file(path)
        with fitz.open(path) as document:
            page_count = document.page_count
        canonical_by_hash.setdefault(digest, path.name)
        preliminary.append((path, digest, page_count))

    return [
        DocumentRecord(
            filename=path.name,
            path=str(path.resolve()),
            sha256=digest,
            canonical_filename=canonical_by_hash[digest],
            page_count=page_count,
            metadata=metadata.get(path.name.casefold(), []),
        )
        for path, digest, page_count in preliminary
    ]

