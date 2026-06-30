from __future__ import annotations

import hashlib
import re
import unicodedata


SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
WIKIDATA_QID_RE = re.compile(r"^Q[0-9]+$")

SYMMETRIC_EDGE_TYPES = {
    "duplicate",
    "semantic_kin",
    "translation",
    "weak_link",
    "similar_to",
    "same_instrument_as",
    "clause_reuse",
}


def text_sha256(text: str) -> str:
    """Return the SHA-256 hash of UTF-8 text."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slug(text: str) -> str:
    """Return a deterministic ASCII slug for entity identifiers.

    The canonicalisation is intentionally conservative: Unicode normalisation,
    case folding, accent stripping, non-alphanumeric collapse, and underscore
    trimming. Empty strings become ``unknown`` so identifiers never end with an
    empty segment.
    """

    normalized = unicodedata.normalize("NFKC", text).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return value or "unknown"


def _require_sha256(source_sha256: str) -> None:
    if not SHA256_RE.fullmatch(source_sha256):
        raise ValueError(f"expected lowercase SHA-256, got {source_sha256!r}")


def chunk_id(source_sha256: str, page: int, idx: int) -> str:
    """Return the stable chunk identifier ``<sha>:p####:c###``."""

    _require_sha256(source_sha256)
    if page < 1:
        raise ValueError("page must be >= 1")
    if idx < 0:
        raise ValueError("idx must be >= 0")
    return f"{source_sha256}:p{page:04d}:c{idx:03d}"


def node_id(
    node_type: str,
    *,
    label: str | None = None,
    document_id: str | None = None,
    treaty_id: str | None = None,
    source_sha256: str | None = None,
    page: int | None = None,
    idx: int | None = None,
    wikidata_qid: str | None = None,
) -> str:
    """Build a deterministic node identifier for the Lexis Mollis graph."""

    if node_type == "Document":
        if not document_id:
            raise ValueError("Document nodes require document_id")
        return f"doc:{document_id}"

    if node_type == "Instrument":
        if treaty_id:
            return f"instr:{treaty_id}"
        if not label:
            raise ValueError("Instrument nodes require treaty_id or label")
        return f"instr:{slug(label)}:{text_sha256(label)[:12]}"

    if node_type == "Clause":
        if source_sha256 is None or page is None or idx is None:
            raise ValueError("Clause nodes require source_sha256, page and idx")
        return f"clause:{chunk_id(source_sha256, page, idx)}"

    if wikidata_qid is not None:
        if not WIKIDATA_QID_RE.fullmatch(wikidata_qid):
            raise ValueError(f"invalid Wikidata QID: {wikidata_qid!r}")
        return f"ent:wd:{wikidata_qid}"

    if not label:
        raise ValueError(f"{node_type} nodes require label or wikidata_qid")
    return f"ent:{node_type}:{slug(label)}"


def edge_key(src: str, dst: str, edge_type: str) -> str:
    """Return a deterministic edge key.

    Symmetric edge types are stored once by lexicographically ordering endpoints.
    Directed relation types preserve their input direction.
    """

    if edge_type in SYMMETRIC_EDGE_TYPES and dst < src:
        src, dst = dst, src
    return f"{edge_type}:{src}->{dst}"

