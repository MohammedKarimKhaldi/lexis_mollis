#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from rdflib import Graph


ROOT = Path(__file__).resolve().parents[1]
METADATA_DESIGN = ROOT / "metadata_design"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_json_schemas() -> list[Path]:
    schema_paths = sorted(METADATA_DESIGN.glob("*.schema.json"))
    if not schema_paths:
        fail("no JSON schemas found in metadata_design")
    for path in schema_paths:
        Draft202012Validator.check_schema(load_json(path))
    return schema_paths


def validate_ontology() -> int:
    ttl = METADATA_DESIGN / "ontology.ttl"
    if not ttl.exists():
        fail("metadata_design/ontology.ttl is missing")
    graph = Graph()
    graph.parse(ttl, format="turtle")
    return len(graph)


def validate_taxonomy_and_mapping() -> tuple[int, int]:
    document_schema = load_json(METADATA_DESIGN / "document.schema.json")
    taxonomy = load_json(METADATA_DESIGN / "tag_taxonomy.json")
    mapping = load_json(METADATA_DESIGN / "doc_type_mapping.json")

    doc_types = set(document_schema["properties"]["doc_type"]["enum"])
    mapped = set(mapping.get("mappings", {}))
    missing = sorted(doc_types - mapped)
    extra = sorted(mapped - doc_types)
    if missing:
        fail("doc_type_mapping.json missing doc_type values: " + ", ".join(missing))
    if extra:
        fail("doc_type_mapping.json has unknown doc_type values: " + ", ".join(extra))

    namespaces = taxonomy.get("namespaces", {})
    for namespace in ["instrument_type", "issuing_body", "legal_force", "source_db"]:
        if namespace not in namespaces:
            fail(f"tag_taxonomy.json missing namespace: {namespace}")

    instrument_values = set(namespaces["instrument_type"].get("values", []))
    legal_force_values = set(namespaces["legal_force"].get("values", []))
    for doc_type, record in mapping["mappings"].items():
        if record.get("instrument_type") not in instrument_values:
            fail(f"{doc_type}: invalid instrument_type {record.get('instrument_type')!r}")
        if record.get("legal_force") not in legal_force_values:
            fail(f"{doc_type}: invalid legal_force {record.get('legal_force')!r}")
    return len(namespaces), len(mapped)


def validate_page_samples(limit: int) -> int:
    pages_path = ROOT / "outputs_v2" / "kb" / "pages.jsonl"
    if not pages_path.exists():
        return 0

    page_schema = load_json(METADATA_DESIGN / "page.schema.json")
    validator = Draft202012Validator(page_schema)
    count = 0
    with pages_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
            if errors:
                first = errors[0]
                location = ".".join(str(part) for part in first.path) or "<root>"
                fail(f"outputs_v2/kb/pages.jsonl record {count + 1} invalid at {location}: {first.message}")
            count += 1
            if count >= limit:
                break
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Lexis Mollis metadata schemas and sample exports.")
    parser.add_argument("--sample-pages", type=int, default=250, help="Number of outputs_v2 page records to validate.")
    args = parser.parse_args()

    schema_paths = validate_json_schemas()
    triple_count = validate_ontology()
    namespace_count, mapping_count = validate_taxonomy_and_mapping()
    page_count = validate_page_samples(args.sample_pages)

    print(
        json.dumps(
            {
                "schemas_valid": len(schema_paths),
                "ontology_triples": triple_count,
                "tag_namespaces": namespace_count,
                "doc_type_mappings": mapping_count,
                "page_samples_validated": page_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

