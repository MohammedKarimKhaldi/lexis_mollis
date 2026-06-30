# Legacy scripts

This folder contains archived code from the first OCR and ingestion attempts.
It is kept for provenance and comparison only.

## Current production path

The canonical pipeline is the `pdfkb` package:

```bash
python -m pdfkb run --source traites --metadata metadata/parsed_metadata.json --output outputs_v2 --state metadata/pipeline.sqlite3 --workers 4 --dpi 300 --resume
```

The active long-running launcher is:

```bash
./run_pdfkb_full.sh
```

## Archived folders

- `ocr_v1/`: replaced OCR scripts based on successive PyMuPDF, Tesseract, and Apple Vision experiments.
- `ingestion_v1/`: older acquisition and metadata parsing helpers.

These scripts are not part of the production path and should not be used for new OCR runs unless intentionally doing historical comparison.

## Historical outputs

The root `extracted/` directory is intentionally kept outside this folder. It is baseline material for before/after comparison against `outputs_v2/`, not the current knowledge-base source of truth.

The current authoritative state is `metadata/pipeline.sqlite3`; do not replace it with the older `metadata/extraction_log.json`.
