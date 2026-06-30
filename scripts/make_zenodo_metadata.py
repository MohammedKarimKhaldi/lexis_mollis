#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or regenerate .zenodo.json from CITATION.cff.")
    parser.add_argument("--citation", type=Path, default=Path("CITATION.cff"))
    parser.add_argument("--zenodo", type=Path, default=Path(".zenodo.json"))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    citation = yaml.safe_load(args.citation.read_text(encoding="utf-8"))
    creators = [
        {"name": f"{author['family-names']}, {author['given-names']}"}
        for author in citation.get("authors", [])
    ]
    generated = {
        "title": citation["title"],
        "description": citation.get("abstract", ""),
        "upload_type": "dataset",
        "access_right": "open",
        "license": citation["license"],
        "creators": creators,
        "keywords": citation.get("keywords", []),
        "communities": [],
    }

    if args.write:
        args.zenodo.write_text(json.dumps(generated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.zenodo}")
        return 0

    current = json.loads(args.zenodo.read_text(encoding="utf-8"))
    mismatches = {
        key: {"current": current.get(key), "expected": value}
        for key, value in generated.items()
        if current.get(key) != value
    }
    if mismatches:
        print(json.dumps({"status": "mismatch", "mismatches": mismatches}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "zenodo_metadata_ok"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

