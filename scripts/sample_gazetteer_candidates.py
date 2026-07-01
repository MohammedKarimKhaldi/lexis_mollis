#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from pdfkb.graph.gazetteers import load_all_gazetteers
from pdfkb.similarity.io import read_jsonl


CAPITALIZED = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ0-9'’.-]+"
CONNECTOR = r"(?:d[’']|de|du|des|del|della|di|da|dos|das|la|le|les|l[’']|of|the|and|et|à|au|aux)"
PHRASE_RE = re.compile(rf"{CAPITALIZED}(?:\s+(?:{CONNECTOR}|{CAPITALIZED}))*")

STOP_CANDIDATES = {
    "article",
    "articles",
    "annexe",
    "annex",
    "appendix",
    "artikel",
    "articulo",
    "articolo",
    "artículo",
    "bureau",
    "chapitre",
    "chapter",
    "chaque",
    "convention",
    "agreement",
    "accord",
    "protocol",
    "protocole",
    "treaty",
    "traite",
    "traité",
    "declaration",
    "déclaration",
    "partie",
    "parties",
    "section",
    "table",
    "page",
    "signé",
    "signed",
    "fait",
    "done",
    "whereas",
    "considering",
    "cette",
    "dans",
    "december",
    "vu",
    "affaires",
    "commission",
    "commissions",
    "comite",
    "comité",
    "conference",
    "conférence",
    "conseil",
    "council",
    "elle",
    "elles",
    "etat",
    "etats",
    "etrangeres",
    "étrangères",
    "gouvernement",
    "gouvernements",
    "government",
    "governments",
    "informations",
    "institut",
    "institute",
    "french",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "decembre",
    "décembre",
    "janvier",
    "fevrier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "ministère",
    "ministere",
    "ministry",
    "minister",
    "ministre",
    "nous",
    "november",
    "organisation",
    "organisations",
    "party",
    "parte",
    "partes",
    "pays",
    "potenze",
    "pour",
    "president",
    "président",
    "puissance",
    "puissances",
    "republique",
    "république",
    "republic",
    "state",
    "states",
    "stato",
    "signe",
    "sont",
    "though",
    "toutefois",
    "union",
}

CONNECTOR_WORDS = {
    "a",
    "and",
    "d",
    "au",
    "aux",
    "da",
    "das",
    "de",
    "del",
    "della",
    "des",
    "di",
    "dos",
    "du",
    "et",
    "l",
    "la",
    "le",
    "les",
    "of",
    "the",
}


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def known_surfaces(gazetteers: Path) -> set[str]:
    surfaces: set[str] = set()
    for entry in load_all_gazetteers(gazetteers):
        for surface in entry.surfaces:
            value = normalise(surface)
            if value:
                surfaces.add(value)
    return surfaces


def candidate_phrases(text: str) -> Iterable[tuple[str, int, int]]:
    for match in PHRASE_RE.finditer(text):
        phrase = compact(match.group(0))
        if len(phrase) < 3:
            continue
        words = phrase.split()
        if len(words) > 7:
            continue
        yield phrase, match.start(), match.end()


def is_candidate(phrase: str, known: set[str]) -> bool:
    value = normalise(phrase)
    if not value or value in known:
        return False
    parts = value.split()
    if parts[-1] in CONNECTOR_WORDS:
        return False
    if len(parts) == 1 and (len(parts[0]) < 4 or parts[0] in STOP_CANDIDATES):
        return False
    content_parts = [part for part in parts if part not in CONNECTOR_WORDS]
    if not content_parts:
        return False
    generic_count = sum(1 for part in content_parts if part in STOP_CANDIDATES)
    if generic_count == len(content_parts):
        return False
    if len(content_parts) <= 4 and generic_count / len(content_parts) >= 0.60:
        return False
    if any(char.isdigit() for char in value) and len(parts) == 1:
        return False
    return True


def context(text: str, start: int, end: int, chars: int) -> str:
    left = max(0, start - chars)
    right = min(len(text), end + chars)
    return compact(text[left:right])


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample frequent uncatalogued gazetteer candidates from KB text.")
    parser.add_argument("--kb", type=Path, default=Path("outputs_v2/kb/pages.jsonl"))
    parser.add_argument("--gazetteers", type=Path, default=Path("data/gazetteers"))
    parser.add_argument("--output", type=Path, default=Path("outputs_v2/graph/gazetteer_candidates.csv"))
    parser.add_argument("--min-count", type=int, default=8)
    parser.add_argument("--top", type=int, default=300)
    parser.add_argument("--context-chars", type=int, default=90)
    args = parser.parse_args()

    known = known_surfaces(args.gazetteers)
    counts: Counter[str] = Counter()
    display: dict[str, Counter[str]] = defaultdict(Counter)
    documents: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, list[str]] = defaultdict(list)

    for page in read_jsonl(args.kb):
        text = page.get("text") or ""
        document_id = str(page.get("document_id") or "")
        for phrase, start, end in candidate_phrases(text):
            key = normalise(phrase)
            if not is_candidate(phrase, known):
                continue
            counts[key] += 1
            display[key][phrase] += 1
            if document_id:
                documents[key].add(document_id)
            if len(examples[key]) < 3:
                examples[key].append(context(text, start, end, args.context_chars))

    rows = []
    for key, count in counts.most_common():
        if count < args.min_count:
            continue
        label = display[key].most_common(1)[0][0]
        rows.append(
            {
                "candidate_label": label,
                "normalized": key,
                "count": count,
                "document_count": len(documents[key]),
                "suggested_type": "",
                "aliases": "",
                "qid": "",
                "iso3": "",
                "lang": "",
                "sample_documents": "|".join(sorted(documents[key])[:8]),
                "examples_json": json.dumps(examples[key], ensure_ascii=False),
                "review_decision": "",
                "notes": "",
            }
        )
        if len(rows) >= args.top:
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "candidate_label",
                "normalized",
                "count",
                "document_count",
                "suggested_type",
                "aliases",
                "qid",
                "iso3",
                "lang",
                "sample_documents",
                "examples_json",
                "review_decision",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(
        json.dumps(
            {
                "rows": len(rows),
                "output": str(args.output),
                "min_count": args.min_count,
                "known_surfaces": len(known),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
