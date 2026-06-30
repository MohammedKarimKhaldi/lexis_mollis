# Scientific Methods Schema for the OCR Corpus

This is a draft structure for describing the corpus and pipeline in a future
scientific paper, data paper, or reproducibility appendix.

## Corpus description

Report:

- corpus title;
- source institution or repository;
- acquisition method and source URLs;
- number of PDF aliases;
- number of unique physical PDFs by SHA-256;
- number of pages;
- chronological coverage from minimum to maximum year;
- document type distribution;
- known duplicate policy.

Recommended table columns:

| Variable | Definition | Source |
|---|---|---|
| `document_id` | Filename stem / documentary alias | inventory |
| `source_sha256` | SHA-256 of the PDF bytes | inventory |
| `treaty_id` | Treaty identifier from source metadata | parsed metadata |
| `doc_type` | Normalized document type | parsed metadata |
| `year` | Year parsed from treaty identifier | parsed metadata |
| `page_count` | PDF page count | PyMuPDF inventory |

## OCR and text-production method

Report:

- native text extraction criteria;
- OCR engines used;
- language/script detection strategy;
- image preprocessing policy;
- candidate selection criteria;
- page-level quality score thresholds;
- review queue policy;
- exact pipeline version and command.

Recommended thresholds:

| Band | Rule | Interpretation |
|---|---|---|
| accepted | `quality_score >= 0.85` | usable without priority review |
| review | `0.65 <= quality_score < 0.85` | included, review recommended |
| priority review | `quality_score < 0.65` | included, high-priority review |

## Provenance and auditability

Report each page as a derived data object:

- input PDF SHA-256;
- page number;
- selected OCR method;
- language/script labels;
- quality score;
- review flags;
- raw text;
- clean text;
- pipeline version.

Use the full `outputs_v2/audit/pages.jsonl` after final export for candidate-level
evidence, blocks, transformations, and coordinates.

## Reproducibility statement

Minimum reproducibility bundle:

- original PDFs or documented source URLs;
- `metadata/parsed_metadata.json`;
- `metadata/pipeline.sqlite3` or exported JSONL;
- `pdfkb` source code and version;
- command-line invocation;
- benchmark cases;
- final manifest and review queue.

## Limitations to state explicitly

- OCR confidence is not equivalent to documentary truth.
- Handwriting and degraded historical print remain uncertain.
- Low-confidence pages are retained rather than silently excluded.
- Language detection can be unstable for short or multilingual pages.
- Rights status must be reviewed separately from OCR quality.

