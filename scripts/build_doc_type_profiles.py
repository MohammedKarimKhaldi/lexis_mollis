#!/usr/bin/env python3
"""Regenerate `doc_type_profiles.json` without re-running the full similarity build.

`pdfkb similarity build` already produces this file as one of its deliverables
(see `pdfkb/similarity/run.py`). This script exists so the marker regexes /
narrative wording can be iterated on and re-run cheaply against an
already-built `chunks.parquet` — no re-embedding, no re-chunking.

Example:
  .venv/bin/python scripts/build_doc_type_profiles.py \
    --chunks outputs_v2/similarity/chunks.parquet \
    --documents outputs_v2/release/documents \
    --output outputs_v2/similarity/doc_type_profiles.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pdfkb.similarity.doc_type_profiles import write_doc_type_profiles  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunks", type=Path, default=Path("outputs_v2/similarity/chunks.parquet"))
    parser.add_argument("--documents", type=Path, default=Path("outputs_v2/release/documents"),
                         help="Optional documents table (for accurate page counts). Skipped if absent.")
    parser.add_argument("--mapping", type=Path, default=Path("metadata_design/doc_type_mapping.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs_v2/similarity/doc_type_profiles.json"))
    parser.add_argument("--min-documents", type=int, default=3,
                         help="Below this many documents, a type's stats are flagged low_sample_warning.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.chunks.exists():
        print(f"Introuvable : {args.chunks} (lancer d'abord `pdfkb similarity build`).", file=sys.stderr)
        return 1
    documents_pq = args.documents if args.documents.exists() else None
    out_path = write_doc_type_profiles(
        args.chunks,
        args.output,
        mapping_path=args.mapping,
        documents_pq=documents_pq,
        min_documents=args.min_documents,
    )
    data = json.loads(out_path.read_text(encoding="utf-8"))
    print(json.dumps(
        {
            "output": str(out_path),
            "n_documents_total": data["n_documents_total"],
            "n_chunks_total": data["n_chunks_total"],
            "types": {label: profile["n_documents"] for label, profile in data["types"].items()},
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
