from __future__ import annotations

from pdfkb.ids import text_sha256

from .config import GraphConfig
from .dates import extract_dates
from .gazetteers import Matcher


def extract_mentions(page: dict, matcher: Matcher, cfg: GraphConfig) -> list[dict]:
    text = page.get("text") or ""
    if not text.strip():
        return []
    provisional = bool(page.get("review_required") or page.get("review_priority") == "high")
    mentions: list[dict] = []
    for match in matcher.find(text):
        mentions.append(
            {
                "mention_id": _mention_id(page, match.start, match.end, match.entry.type, match.surface),
                "type": match.entry.type,
                "surface": match.surface,
                "canonical_hint": match.entry.label,
                "qid": match.entry.qid,
                "document_id": page["document_id"],
                "treaty_id": page.get("treaty_id"),
                "source_sha256": page["source_sha256"],
                "page_number": page["page_number"],
                "char_start": match.start,
                "char_end": match.end,
                "confidence": 0.95,
                "provisional": provisional,
                "method": "gazetteer",
                "pipeline_version": page.get("pipeline_version") or "",
            }
        )

    for date in extract_dates(text):
        mentions.append(
            {
                "mention_id": _mention_id(page, date.start, date.end, "TopicConcept", date.surface),
                "type": "TopicConcept",
                "surface": date.surface,
                "canonical_hint": f"date:{date.iso_date}",
                "qid": None,
                "document_id": page["document_id"],
                "treaty_id": page.get("treaty_id"),
                "source_sha256": page["source_sha256"],
                "page_number": page["page_number"],
                "char_start": date.start,
                "char_end": date.end,
                "confidence": date.confidence,
                "provisional": provisional,
                "method": "date_regex",
                "pipeline_version": page.get("pipeline_version") or "",
            }
        )
    return [mention for mention in mentions if float(mention["confidence"]) >= cfg.min_confidence]


def _mention_id(page: dict, start: int, end: int, mention_type: str, surface: str) -> str:
    payload = f"{page['document_id']}:{page['page_number']}:{start}:{end}:{mention_type}:{surface}"
    return text_sha256(payload)

