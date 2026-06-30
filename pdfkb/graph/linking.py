from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from pdfkb import PIPELINE_VERSION
from pdfkb.ids import node_id, slug


def load_doc_type_mapping(path: Path = Path("metadata_design/doc_type_mapping.json")) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("mappings", {})


def document_records_from_pages(pages: list[dict]) -> list[dict]:
    by_doc: dict[str, dict] = {}
    quality: dict[str, list[float]] = defaultdict(list)
    review: dict[str, bool] = defaultdict(bool)
    for page in pages:
        doc_id = page["document_id"]
        quality[doc_id].append(float(page.get("quality_score") or 0))
        review[doc_id] = review[doc_id] or bool(page.get("review_required"))
        if doc_id not in by_doc:
            by_doc[doc_id] = {
                "document_id": doc_id,
                "source_sha256": page["source_sha256"],
                "title": page.get("title") or doc_id,
                "treaty_id": page.get("treaty_id"),
                "doc_type": page.get("doc_type") or "Inconnu",
                "year": page.get("year"),
                "pipeline_version": page.get("pipeline_version") or PIPELINE_VERSION,
            }
    for doc_id, doc in by_doc.items():
        scores = quality[doc_id]
        doc["confidence"] = sum(scores) / len(scores) if scores else None
        doc["provisional"] = review[doc_id]
    return list(by_doc.values())


def resolve_nodes(mentions: list[dict], documents: list[dict], mapping: dict[str, dict] | None = None) -> tuple[list[dict], list[dict]]:
    mapping = mapping or {}
    nodes: dict[str, dict] = {}
    mention_links: list[dict] = []

    for doc in documents:
        doc_type = doc.get("doc_type") or "Inconnu"
        mapped = mapping.get(doc_type, {"instrument_type": "unknown", "legal_force": "unknown"})
        tags = [
            f"doc_type:{doc_type}",
            f"instrument_type:{mapped.get('instrument_type', 'unknown')}",
            f"legal_force:{mapped.get('legal_force', 'unknown')}",
            "source_db:traites_mineae",
        ]
        doc_node = node_id("Document", document_id=doc["document_id"])
        nodes[doc_node] = {
            "node_id": doc_node,
            "type": "Document",
            "label": doc.get("title") or doc["document_id"],
            "aliases": [doc["document_id"]],
            "wikidata_qid": None,
            "document_id": doc["document_id"],
            "source_sha256": doc.get("source_sha256"),
            "year": doc.get("year"),
            "confidence": doc.get("confidence"),
            "provisional": bool(doc.get("provisional")),
            "pipeline_version": doc.get("pipeline_version") or PIPELINE_VERSION,
            "tags": sorted(tags),
        }
        if doc.get("treaty_id"):
            instr_node = node_id("Instrument", treaty_id=doc["treaty_id"])
            existing = nodes.get(instr_node)
            nodes[instr_node] = {
                "node_id": instr_node,
                "type": "Instrument",
                "label": (existing or {}).get("label") or doc.get("title") or doc["treaty_id"],
                "aliases": sorted(set(((existing or {}).get("aliases") or []) + [doc["treaty_id"]])),
                "wikidata_qid": None,
                "document_id": None,
                "source_sha256": None,
                "year": doc.get("year") or (existing or {}).get("year"),
                "confidence": doc.get("confidence"),
                "provisional": bool(doc.get("provisional") or (existing or {}).get("provisional")),
                "pipeline_version": doc.get("pipeline_version") or PIPELINE_VERSION,
                "tags": sorted(set(tags + ((existing or {}).get("tags") or []))),
            }
            topic_id = f"ent:TopicConcept:instrument_type_{slug(mapped.get('instrument_type', 'unknown'))}"
            nodes.setdefault(
                topic_id,
                {
                    "node_id": topic_id,
                    "type": "TopicConcept",
                    "label": f"instrument_type:{mapped.get('instrument_type', 'unknown')}",
                    "aliases": [],
                    "wikidata_qid": None,
                    "document_id": None,
                    "source_sha256": None,
                    "year": None,
                    "confidence": 1.0,
                    "provisional": False,
                    "pipeline_version": PIPELINE_VERSION,
                    "tags": [f"instrument_type:{mapped.get('instrument_type', 'unknown')}"],
                },
            )

    for mention in mentions:
        mention_type = mention["type"]
        if mention_type == "TopicConcept" and str(mention["canonical_hint"]).startswith("date:"):
            current_node_id = f"ent:TopicConcept:{slug(mention['canonical_hint'])}"
        else:
            current_node_id = node_id(mention_type, label=mention["canonical_hint"], wikidata_qid=mention.get("qid"))
        existing = nodes.get(current_node_id)
        aliases = set((existing or {}).get("aliases") or [])
        aliases.add(mention["surface"])
        nodes[current_node_id] = {
            "node_id": current_node_id,
            "type": mention_type,
            "label": (existing or {}).get("label") or str(mention["canonical_hint"]).replace("date:", ""),
            "aliases": sorted(aliases),
            "wikidata_qid": mention.get("qid"),
            "document_id": None,
            "source_sha256": None,
            "year": None,
            "confidence": max(float(mention.get("confidence") or 0), float((existing or {}).get("confidence") or 0)),
            "provisional": bool(mention.get("provisional") or (existing or {}).get("provisional")),
            "pipeline_version": mention.get("pipeline_version") or PIPELINE_VERSION,
            "tags": sorted(set((existing or {}).get("tags") or [])),
        }
        mention_links.append(
            {
                "mention_id": mention["mention_id"],
                "node_id": current_node_id,
                "type": mention_type,
                "document_id": mention["document_id"],
                "treaty_id": mention.get("treaty_id"),
                "page_number": mention["page_number"],
                "char_start": mention["char_start"],
                "char_end": mention["char_end"],
                "surface": mention["surface"],
                "confidence": mention["confidence"],
                "provisional": mention["provisional"],
                "method": mention["method"],
            }
        )

    return sorted(nodes.values(), key=lambda row: row["node_id"]), sorted(mention_links, key=lambda row: row["mention_id"])

