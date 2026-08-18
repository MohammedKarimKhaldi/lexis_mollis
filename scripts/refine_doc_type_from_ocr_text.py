#!/usr/bin/env python3
"""Reclassify a small number of "Autre" documents using their actual OCR'd text,
for the cases where the title alone gives no hint of the type but the document's
own content does (e.g. a document titled "Courrier d'information..." whose first
page literally reads "PROCES-VERBAL de DEPOT des RATIFICATIONS...").

Run AFTER `pdfkb run` (needs OCR'd page text in metadata/pipeline.sqlite3) but
BEFORE `pdfkb run --resume` is re-run to push the correction back into the
pipeline state, and before `pdfkb audit` / `similarity build` / etc. See
README.md and ARCHITECTURE.md for the current command order.

Deliberately conservative: only two text markers are used, both validated by
checking their hit-rate across ALL already title-classified doc_types before
being trusted here (not just the target type) -- candidates with meaningful
false-positive rates elsewhere were rejected:
  - "pleins pouvoirs" was tested for detecting "Pouvoirs" documents, but also
    fires on ~17% of "Déclaration" preambles (nearly as often as in Pouvoirs
    itself) -- too ambiguous, not used.
  - "accusé de réception" alone was tested for "Accusé de réception", but also
    fires on ~30% of "Notification" documents -- too ambiguous alone, so it is
    only trusted here in combination with the diplomatic-note opening formula
    "présente ses compliments" (both together: ~20% hit rate in Accusé de
    réception, ~2% elsewhere).
  - "procès-verbal" appearing anywhere in the first two pages is highly
    specific on its own: ~60% hit rate within already-classified Procès-verbal
    documents, ~0-3% in every other type.

Expect a small yield (order of a few percent of the "Autre" bucket) -- most of
what's left genuinely has no recoverable signal in the title OR the opening
text, and forcing a classification for those would be fabrication, not
inference. This script only touches documents where BOTH the title-based
classifier already available and the text markers below agree the label was
otherwise unknown; it never overrides a title-derived classification.

Adds a `doc_type_source` field to every record ("title" for the vast
majority, "text_marker:<key>" for anything changed here) so the provenance of
each doc_type stays auditable -- this field is metadata-only and does not
flow into outputs_v2/release (pdfkb/export.py only forwards a fixed set of
fields), so it never conflicts with document.schema.json's doc_type enum.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path

DEFAULT_METADATA = Path("metadata/parsed_metadata.json")
DEFAULT_STATE = Path("metadata/pipeline.sqlite3")

# (key, primary pattern, secondary pattern or None, resulting label).
# A record is reclassified only if primary matches (and secondary too, when
# given) in the first --max-pages of its OCR'd text.
TEXT_MARKERS: list[tuple[str, re.Pattern, re.Pattern | None, str]] = [
    ("proces_verbal", re.compile(r"proc[èe]s[\s-]verbal"), None, "Procès-verbal"),
    (
        "accuse_reception",
        re.compile(r"accus\w* r[ée]cept"),
        re.compile(r"pr[ée]sente ses compliments"),
        "Accusé de réception",
    ),
]


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text.lower())


def load_page_text(cur: sqlite3.Cursor, sha256: str, max_pages: int, max_chars: int) -> str:
    cur.execute(
        "SELECT page_number, result_json FROM pages WHERE sha256=? ORDER BY page_number LIMIT ?",
        (sha256, max_pages),
    )
    parts: list[str] = []
    for _page_number, result_json in cur.fetchall():
        try:
            result = json.loads(result_json)
        except (TypeError, json.JSONDecodeError):
            continue
        parts.append(result.get("cleaned_text") or result.get("raw_text") or "")
    return " ".join(parts)[:max_chars]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--max-pages", type=int, default=2, help="OCR pages to read per document.")
    parser.add_argument("--max-chars", type=int, default=1200, help="Text budget per document.")
    args = parser.parse_args()

    records = json.loads(args.metadata.read_text(encoding="utf-8"))

    con = sqlite3.connect(str(args.state))
    cur = con.cursor()
    cur.execute("SELECT filename, sha256 FROM documents")
    sha_by_filename = {filename.casefold(): sha256 for filename, sha256 in cur.fetchall()}

    changes: Counter[str] = Counter()
    considered = 0
    for record in records:
        record.setdefault("doc_type_source", "title")
        if record.get("doc_type") != "Autre":
            continue
        sha256 = sha_by_filename.get(record["filename"].casefold())
        if not sha256:
            continue
        considered += 1
        text = normalise(load_page_text(cur, sha256, args.max_pages, args.max_chars))
        if not text:
            continue
        for key, primary, secondary, label in TEXT_MARKERS:
            if primary.search(text) and (secondary is None or secondary.search(text)):
                record["doc_type"] = label
                record["doc_type_source"] = f"text_marker:{key}"
                changes[label] += 1
                break

    con.close()

    args.metadata.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    csv_path = args.metadata.with_suffix(".csv")
    if records:
        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)

    print(f"Autre documents with OCR text available: {considered}")
    print(f"Reclassified via validated OCR text markers: {sum(changes.values())}")
    for label, n in changes.most_common():
        print(f"  -> {label}: {n}")
    print(f"Wrote {args.metadata} and {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
