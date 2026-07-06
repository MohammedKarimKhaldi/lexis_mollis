from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .io import read_parquet_records
from .lexical import normalise_lexical

# Every pattern below is matched against `normalise_lexical(text)` output: lowercase,
# accent-stripped, non-alphanumeric characters collapsed to single spaces. So
# "Considérant que" / "CONSIDÉRANT QUE" / "Considerant, que" all normalise to
# "considerant que" and match the same pattern. Patterns are deliberately simple
# (no lookaheads on OCR-mangled punctuation) because the underlying text is
# historical OCR output, sometimes noisy — see `method` in the output for the
# resulting caveat.
MARKER_DEFINITIONS: list[tuple[str, str, str]] = [
    ("pleins_pouvoirs", "Préambule de « pleins pouvoirs » des plénipotentiaires", r"pleins pouvoirs"),
    ("hautes_parties_contractantes", "Mention des « Hautes Parties contractantes »", r"hautes parties contractantes"),
    ("considerant_que", "Clause introductive « Considérant que »", r"considerant que"),
    ("soussigne_declare", "Formule « Le/Les soussigné(s) … déclare(nt) »", r"soussigne\w*(?: \w+){0,15} declar\w*"),
    ("sont_convenus", "Formule d'accord « sont convenus … »", r"sont convenus"),
    ("gouvernement_de", "Parties désignées par « le Gouvernement de … »", r"gouvernement de"),
    ("article_numbered", "Structure en articles numérotés", r"article (?:premier|1er|\d{1,3})\b"),
    ("en_foi_de_quoi", "Clause de signature « En foi de quoi »", r"en foi de quoi"),
    ("fait_a_le", "Clause de lieu et date « Fait à … le … »", r"fait a(?: \w+){1,4} le \d{1,2}"),
    ("ratification", "Mention de ratification", r"ratifi\w*"),
    ("entree_en_vigueur", "Clause d'entrée en vigueur", r"entr\w{1,3} en vigueur"),
    ("denonciation", "Clause de dénonciation / durée", r"denonc\w*"),
]

# Markers where the *number* of occurrences is at least as informative as their
# mere presence (article count is the clearest proxy for "how article-structured"
# a document is; repeated "gouvernement de" is a proxy for the number of parties
# named that way rather than by title/rank).
COUNT_MARKERS = {"gouvernement_de", "article_numbered"}

DEFAULT_MIN_DOCUMENTS = 3
DEFAULT_MAX_SAMPLES = 3
DEFAULT_SAMPLE_CHARS = 320

METHOD_NOTE = (
    "Statistiques calculées automatiquement par détection d'expressions régulières sur le texte "
    "OCR normalisé (minuscules, accents supprimés) de chaque document, regroupé par doc_type. "
    "Approche heuristique : le bruit OCR peut faire sous-compter certains marqueurs (texte mal "
    "reconnu) ; les fractions et moyennes n'en restent pas moins de vraies mesures sur le corpus "
    "tel qu'océrisé, pas des estimations qualitatives. À ne pas confondre avec une annotation "
    "juridique validée humainement — voir PROJECT_STATUS.md pour l'état de calibration du corpus."
)


def _compiled_markers() -> list[tuple[str, str, re.Pattern]]:
    return [(key, label, re.compile(pattern)) for key, label, pattern in MARKER_DEFINITIONS]


def _group_chunks_by_document(chunks: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        groups[chunk["document_id"]].append(chunk)
    for doc_chunks in groups.values():
        doc_chunks.sort(key=lambda c: (c.get("page_number") or 0, c.get("chunk_index") or 0))
    return groups


def _document_full_text(doc_chunks: list[dict]) -> str:
    return "\n".join(str(chunk.get("text") or "") for chunk in doc_chunks)


def _excerpt(text: str, limit: int) -> str:
    normalised = " ".join((text or "").split())
    if len(normalised) <= limit:
        return normalised
    return normalised[: limit - 1].rstrip() + "…"


def _pct(fraction: float) -> float:
    return round(fraction * 100, 1)


def _narrative(profile: dict) -> str:
    markers = profile["markers"]

    def pct(key: str) -> float:
        return _pct(markers[key]["document_fraction"])

    quality = profile["avg_quality_score"]
    quality_part = f", score qualité OCR moyen {quality:.2f}" if quality is not None else ""
    sentences = [
        f"{profile['n_documents']} document(s) classé(s) « {profile['label']} » "
        f"({profile['n_chunks']} extraits{quality_part}).",
        (
            "Formes de rédaction observées (fraction des documents où le marqueur est détecté dans "
            f"le texte OCR) : pleins pouvoirs des plénipotentiaires {pct('pleins_pouvoirs')}% ; "
            f"« Hautes Parties contractantes » {pct('hautes_parties_contractantes')}% ; "
            f"clause « Considérant que » {pct('considerant_que')}% ; "
            f"formule « Le/Les soussigné(s) … déclare(nt) » {pct('soussigne_declare')}% ; "
            f"formule d'accord « sont convenus … » {pct('sont_convenus')}% ; "
            f"parties désignées par « le Gouvernement de … » {pct('gouvernement_de')}% "
            f"(en moyenne {markers['gouvernement_de']['avg_occurrences_per_document']:.1f} "
            "occurrence(s)/document) ; "
            f"structure en articles numérotés {pct('article_numbered')}% "
            f"(en moyenne {markers['article_numbered']['avg_occurrences_per_document']:.1f} "
            "article(s)/document) ; "
            f"clause de signature « En foi de quoi » {pct('en_foi_de_quoi')}% ; "
            f"clause de lieu et date « Fait à … le … » {pct('fait_a_le')}% ; "
            f"mention de ratification {pct('ratification')}% ; "
            f"clause d'entrée en vigueur {pct('entree_en_vigueur')}% ; "
            f"clause de dénonciation/durée {pct('denonciation')}%."
        ),
    ]
    if profile["low_sample_warning"]:
        sentences.append(
            f"Attention : échantillon réduit ({profile['n_documents']} document(s)), ces proportions "
            "sont peu fiables statistiquement."
        )
    return " ".join(sentences)


def build_doc_type_profiles(
    chunks: list[dict],
    mapping: dict[str, dict] | None = None,
    documents: list[dict] | None = None,
    min_documents: int = DEFAULT_MIN_DOCUMENTS,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    sample_chars: int = DEFAULT_SAMPLE_CHARS,
) -> dict:
    """Compute per-`doc_type` structural/rhetorical profiles from chunk text.

    Purpose: give a downstream LLM (or a human) *grounded, corpus-measured* facts
    about how each document type is typically drafted (preamble style, article
    structure, signature/ratification clauses, ...), so that comparison questions
    like "compare les types de documents (traité, accord, déclaration)" can be
    answered from real statistics + real excerpts instead of a handful of
    semantically-retrieved chunks that may not be representative of the type.
    """
    mapping = mapping or {}
    compiled = _compiled_markers()
    by_doc = _group_chunks_by_document(chunks)

    page_counts: dict[str, int] = {}
    if documents:
        for doc in documents:
            doc_id = doc.get("document_id")
            if doc_id and doc.get("page_count"):
                page_counts[doc_id] = int(doc["page_count"])

    per_type_docs: dict[str, list[str]] = defaultdict(list)
    for doc_id, doc_chunks in by_doc.items():
        doc_type = doc_chunks[0].get("doc_type") or "Inconnu"
        per_type_docs[doc_type].append(doc_id)

    types_profile: dict[str, dict] = {}
    for doc_type, doc_ids in sorted(per_type_docs.items()):
        doc_ids = sorted(doc_ids)
        n_docs = len(doc_ids)
        marker_hits: dict[str, int] = defaultdict(int)
        marker_counts: dict[str, int] = defaultdict(int)
        quality_scores: list[float] = []
        char_lengths: list[int] = []
        pages: list[int] = []
        languages: Counter = Counter()
        openings: list[dict] = []
        closings: list[dict] = []

        for doc_id in doc_ids:
            doc_chunks = by_doc[doc_id]
            full_text = _document_full_text(doc_chunks)
            normalised = normalise_lexical(full_text)
            char_lengths.append(len(full_text))

            doc_quality = [
                chunk.get("quality_score")
                for chunk in doc_chunks
                if isinstance(chunk.get("quality_score"), (int, float))
            ]
            if doc_quality:
                quality_scores.append(sum(doc_quality) / len(doc_quality))

            for chunk in doc_chunks:
                for lang in chunk.get("language") or []:
                    languages[lang] += 1

            pages.append(
                page_counts.get(doc_id)
                or max((chunk.get("page_number") or 0) for chunk in doc_chunks)
                or 1
            )

            for key, _label, pattern in compiled:
                matches = pattern.findall(normalised)
                if matches:
                    marker_hits[key] += 1
                    marker_counts[key] += len(matches)

            first_chunk, last_chunk = doc_chunks[0], doc_chunks[-1]
            openings.append(
                {
                    "document_id": doc_id,
                    "year": first_chunk.get("year"),
                    "quality_score": first_chunk.get("quality_score"),
                    "excerpt": _excerpt(first_chunk.get("text") or "", sample_chars),
                }
            )
            if last_chunk is not first_chunk:
                closings.append(
                    {
                        "document_id": doc_id,
                        "year": last_chunk.get("year"),
                        "quality_score": last_chunk.get("quality_score"),
                        "excerpt": _excerpt(last_chunk.get("text") or "", sample_chars),
                    }
                )

        openings.sort(key=lambda row: row.get("quality_score") or 0, reverse=True)
        closings.sort(key=lambda row: row.get("quality_score") or 0, reverse=True)

        markers_out: dict[str, dict] = {}
        for key, label, _pattern in compiled:
            hits = marker_hits.get(key, 0)
            entry = {
                "label_fr": label,
                "document_fraction": round(hits / n_docs, 4) if n_docs else 0.0,
                "documents_with_marker": hits,
            }
            if key in COUNT_MARKERS:
                entry["avg_occurrences_per_document"] = (
                    round(marker_counts.get(key, 0) / n_docs, 2) if n_docs else 0.0
                )
            markers_out[key] = entry

        mapped = mapping.get(doc_type, {"instrument_type": "unknown", "legal_force": "unknown"})
        n_chunks = sum(len(by_doc[doc_id]) for doc_id in doc_ids)

        profile = {
            "label": doc_type,
            "instrument_type": mapped.get("instrument_type", "unknown"),
            "legal_force": mapped.get("legal_force", "unknown"),
            "n_documents": n_docs,
            "n_chunks": n_chunks,
            "low_sample_warning": n_docs < min_documents,
            "avg_quality_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else None,
            "avg_chars_per_document": round(sum(char_lengths) / len(char_lengths)) if char_lengths else 0,
            "avg_pages_per_document": round(sum(pages) / len(pages), 1) if pages else None,
            "language_distribution": (
                {lang: round(count / n_docs, 4) for lang, count in languages.most_common(8)} if n_docs else {}
            ),
            "markers": markers_out,
            "sample_openings": openings[:max_samples],
            "sample_closings": closings[:max_samples],
        }
        profile["narrative_fr"] = _narrative(profile)
        types_profile[doc_type] = profile

    return {
        "schema_version": "0.1-draft",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "method": METHOD_NOTE,
        "marker_definitions": {key: label for key, label, _pattern in compiled},
        "min_documents_for_reliable_stats": min_documents,
        "n_documents_total": len(by_doc),
        "n_chunks_total": len(chunks),
        "types": types_profile,
    }


def load_doc_type_mapping(path: Path = Path("metadata_design/doc_type_mapping.json")) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("mappings", {})


def write_doc_type_profiles(
    chunks_pq: Path,
    out_path: Path,
    mapping_path: Path = Path("metadata_design/doc_type_mapping.json"),
    documents_pq: Path | None = None,
    **kwargs,
) -> Path:
    chunks = read_parquet_records(chunks_pq)
    mapping = load_doc_type_mapping(mapping_path)
    documents = read_parquet_records(documents_pq) if documents_pq and documents_pq.exists() else None
    profile = build_doc_type_profiles(chunks, mapping, documents, **kwargs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path
