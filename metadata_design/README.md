# Metadata and Tagging Design for the OCR Treaty Corpus

Version: `0.1-draft`

This folder defines a publication-grade metadata model for the OCR corpus while
the OCR run is still in progress. It is intentionally independent from the final
page count: records can be filled incrementally from `outputs_live/kb/pages.jsonl`
and finalized later from `outputs_v2/`.

## Design principles

1. Keep immutable identifiers separate from labels.
   - `source_sha256` identifies the physical PDF bytes.
   - `document_id` identifies the documentary alias/stem.
   - `treaty_id` and `treaty_number` identify diplomatic metadata when present.
2. Separate descriptive, technical, provenance, quality, and review metadata.
3. Treat OCR text as documentary evidence, not corrected prose.
4. Make all transformations auditable and reproducible.
5. Use controlled vocabularies for tags so the KB remains searchable and publishable.

## Standards alignment

The model is designed to map cleanly to established metadata vocabularies:

- Dublin Core / DCMI Terms for descriptive fields such as title, identifier,
  source, language, type, date, and rights.
- DataCite-style citation metadata for corpus-level publication and dataset
  deposit.
- W3C PROV-O concepts for provenance: entities, activities, agents, and
  derivations.
- PREMIS concepts for preservation: objects, events, agents, and rights.

The local field names remain practical Python/JSON names, but each schema file
includes enough structure to map outward later.

## Record levels

| Level | Purpose | Primary file |
|---|---|---|
| Document | One documentary alias such as `tra16630006_001_s1.pdf` | `document.schema.json` |
| Page | One OCR-selected page record | `page.schema.json` |
| Chunk | One future semantic-search chunk derived from a page | `chunk.schema.json` |
| Review event | Human review notes and decisions | `review_event.schema.json` |
| Tags | Controlled vocabularies for browsing/filtering | `tag_taxonomy.json` |

## Paper-oriented documentation

- `scientific_methods_full.md`: full French methods draft for a future paper or
  data paper.
- `ocr_protocol.md`: detailed OCR protocol, candidate generation, scoring, and
  review rules.
- `data_dictionary.md`: field-level data dictionary for document, page, chunk,
  and review records.
- `paper_methods_schema.md`: compact outline/checklist for the methods section.

## Immediate use while OCR runs

1. Continue exporting live snapshots:

   ```bash
   nice -n 10 .venv/bin/python -m pdfkb audit \
     --state metadata/pipeline.sqlite3 \
     --output outputs_live \
     --light
   ```

2. Publish snapshots to `kb_repository/`.
3. Use `paperless_fields.csv` to configure Paperless custom fields later.
4. Use `tag_taxonomy.json` as the source of truth for tags in Paperless,
   Forgejo descriptions, and the vector KB.

## Finalization after OCR completion

After the full OCR run, regenerate `outputs_v2/` without `--light`, validate page
counts, then freeze this metadata design as `1.0` alongside the final corpus.

