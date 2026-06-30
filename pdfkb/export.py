from __future__ import annotations

import csv
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from . import PIPELINE_VERSION
from .cleaning import clean_document
from .models import DocumentRecord, PageResult
from .state import PipelineState


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _metadata(document: DocumentRecord) -> dict[str, Any]:
    primary = document.metadata[0] if document.metadata else {}
    return {
        "document_id": Path(document.filename).stem,
        "source_filename": document.filename,
        "canonical_filename": document.canonical_filename,
        "source_sha256": document.sha256,
        "title": primary.get("title", ""),
        "treaty_id": primary.get("treaty_id", ""),
        "treaty_number": primary.get("treaty_number", ""),
        "doc_type": primary.get("doc_type", ""),
        "year": primary.get("year"),
        "metadata_records": document.metadata,
    }


def _yaml_value(value: Any) -> str:
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False)


def document_markdown(document: DocumentRecord, results: list[PageResult], clean: bool) -> str:
    metadata = _metadata(document)
    lines = ["---"]
    for key in ("document_id", "source_filename", "source_sha256", "title", "treaty_id", "doc_type", "year"):
        lines.append(f"{key}: {_yaml_value(metadata[key])}")
    lines.extend([f"pipeline_version: {_yaml_value(PIPELINE_VERSION)}", "---", ""])
    title = metadata["title"] or metadata["document_id"]
    lines.extend([f"# {title}", ""])
    for result in results:
        text = result.cleaned_text if clean else result.selected.text
        lines.extend(
            [
                f"<!-- page: {result.page_number}; method: {result.selected.method}; quality: {result.quality_score:.3f}; review: {str(result.review_required).lower()} -->",
                f"## Page {result.page_number}",
                "",
                text.strip(),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _json_line(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def export_outputs(
    state: PipelineState,
    output: Path,
    *,
    include_detailed_audit: bool = True,
    include_comparison: bool = True,
) -> dict[str, int]:
    raw_dir = output / "raw"
    clean_dir = output / "clean"
    kb_dir = output / "kb"
    audit_dir = output / "audit"
    for directory in (raw_dir, clean_dir, kb_dir, audit_dir):
        directory.mkdir(parents=True, exist_ok=True)

    kb_lines: list[str] = []
    audit_lines: list[str] = []
    review_rows_by_page: dict[tuple[str, int], dict[str, Any]] = {}
    incomplete = 0
    exported_documents = 0
    exported_pages = 0
    comparison_documents: list[dict[str, Any]] = []

    documents = state.documents()
    aliases_by_hash: dict[str, list[str]] = defaultdict(list)
    for document in documents:
        aliases_by_hash[document.sha256].append(document.filename)

    for document in documents:
        results: list[PageResult] = []
        for page_number in range(1, document.page_count + 1):
            result = state.load_page(document.sha256, page_number)
            if result is None:
                results = []
                break
            results.append(result)
        if not results:
            incomplete += 1
            continue
        clean_document(results)
        stem = Path(document.filename).stem
        atomic_write_text(raw_dir / f"{stem}.md", document_markdown(document, results, clean=False))
        atomic_write_text(clean_dir / f"{stem}.md", document_markdown(document, results, clean=True))
        baseline_chars = None
        if include_comparison:
            baseline_path = Path(document.path).parent.parent / "extracted" / f"{stem}.txt"
            baseline_chars = len(baseline_path.read_text(encoding="utf-8", errors="replace")) if baseline_path.exists() else None
        raw_chars = sum(len(result.selected.text) for result in results)
        if include_comparison:
            comparison_documents.append(
                {
                    "source_filename": document.filename,
                    "page_count": document.page_count,
                    "baseline_char_count": baseline_chars,
                    "v2_raw_char_count": raw_chars,
                    "char_delta": None if baseline_chars is None else raw_chars - baseline_chars,
                    "mean_quality": round(sum(result.quality_score for result in results) / len(results), 4),
                    "minimum_quality": round(min(result.quality_score for result in results), 4),
                    "review_pages": sum(result.review_required for result in results),
                    "methods": sorted({result.selected.method for result in results}),
                }
            )
        metadata = _metadata(document)
        for result in results:
            common = {
                **metadata,
                "pipeline_version": PIPELINE_VERSION,
                "page_number": result.page_number,
                "page_count": result.page_count,
                "language": result.selected.languages,
                "script": result.selected.scripts,
                "method": result.selected.method,
                "quality_score": round(result.quality_score, 4),
                "review_required": result.review_required,
                "review_priority": result.review_priority,
                "review_reasons": result.review_reasons,
            }
            kb_lines.append(_json_line({**common, "text": result.cleaned_text}))
            if include_detailed_audit:
                audit_lines.append(
                    _json_line(
                        {
                            **common,
                            "ink_ratio": round(result.ink_ratio, 6),
                            "agreement": result.agreement,
                            "raw_text": result.selected.text,
                            "cleaned_text": result.cleaned_text,
                            "removed_lines": result.removed_lines,
                            "selected_blocks": [block.to_dict() for block in result.selected.blocks],
                            "candidates": [candidate.to_dict() for candidate in result.candidates],
                        }
                    )
                )
            if result.review_required:
                key = (document.sha256, result.page_number)
                row = review_rows_by_page.setdefault(
                    key,
                    {
                        "source_sha256": document.sha256,
                        "source_filenames": " | ".join(sorted(aliases_by_hash[document.sha256])),
                        "page_number": result.page_number,
                        "priority": result.review_priority,
                        "quality_score": f"{result.quality_score:.4f}",
                        "method": result.selected.method,
                        "languages": " | ".join(result.selected.languages),
                        "scripts": " | ".join(result.selected.scripts),
                        "reasons": " | ".join(result.review_reasons),
                        "review_image": str(
                            Path("audit") / "review_images" / f"{document.sha256[:16]}_p{result.page_number:04d}.jpg"
                        ),
                    },
                )
                if result.review_priority == "high":
                    row["priority"] = "high"
            exported_pages += 1
        exported_documents += 1

    atomic_write_text(kb_dir / "pages.jsonl", "\n".join(kb_lines) + ("\n" if kb_lines else ""))
    if include_detailed_audit:
        atomic_write_text(audit_dir / "pages.jsonl", "\n".join(audit_lines) + ("\n" if audit_lines else ""))
        readme_path = audit_dir / "README.md"
        if readme_path.exists():
            readme_path.unlink()
    else:
        audit_path = audit_dir / "pages.jsonl"
        if audit_path.exists():
            audit_path.unlink()
        atomic_write_text(
            audit_dir / "README.md",
            "Detailed audit export was intentionally skipped for this lightweight live snapshot.\n"
            "Run `python -m pdfkb audit` without `--light` for full candidates, coordinates, and provenance.\n",
        )

    review_path = output / "review_queue.csv"
    fieldnames = [
        "source_sha256",
        "source_filenames",
        "page_number",
        "priority",
        "quality_score",
        "method",
        "languages",
        "scripts",
        "reasons",
        "review_image",
    ]
    descriptor, temporary = tempfile.mkstemp(prefix=".review_queue.", dir=output)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(
                sorted(review_rows_by_page.values(), key=lambda row: (row["priority"] != "high", row["source_filenames"], row["page_number"]))
            )
        os.replace(temporary, review_path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise

    manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "documents_in_state": len(documents),
        "documents_exported": exported_documents,
        "documents_incomplete": incomplete,
        "page_records_exported": exported_pages,
        "review_pages": len(review_rows_by_page),
        "errors": len(state.errors()),
        "detailed_audit_exported": include_detailed_audit,
        "comparison_exported": include_comparison,
    }
    atomic_write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if include_comparison:
        comparison = {
            "pipeline_version": PIPELINE_VERSION,
            "documents": comparison_documents,
            "summary": {
                "documents_compared": sum(item["baseline_char_count"] is not None for item in comparison_documents),
                "baseline_char_count": sum(item["baseline_char_count"] or 0 for item in comparison_documents),
                "v2_raw_char_count": sum(item["v2_raw_char_count"] for item in comparison_documents),
                "review_pages": sum(item["review_pages"] for item in comparison_documents),
            },
        }
        atomic_write_text(output / "comparison_report.json", json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
        markdown = [
            "# Rapport comparatif OCR v2",
            "",
            f"- Documents exportés : {exported_documents}",
            f"- Pages exportées : {exported_pages}",
            f"- Pages à réviser : {len(review_rows_by_page)}",
            f"- Caractères de référence existants : {comparison['summary']['baseline_char_count']:,}",
            f"- Caractères bruts OCR v2 : {comparison['summary']['v2_raw_char_count']:,}",
            "",
            "| Document | Pages | Ancien | OCR v2 | Écart | Qualité moyenne | Révision |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for item in sorted(comparison_documents, key=lambda value: value["source_filename"].casefold()):
            old = "—" if item["baseline_char_count"] is None else f"{item['baseline_char_count']:,}"
            delta = "—" if item["char_delta"] is None else f"{item['char_delta']:+,}"
            markdown.append(
                f"| {item['source_filename']} | {item['page_count']} | {old} | {item['v2_raw_char_count']:,} | {delta} | {item['mean_quality']:.3f} | {item['review_pages']} |"
            )
        atomic_write_text(output / "comparison_report.md", "\n".join(markdown) + "\n")
    else:
        for path in (output / "comparison_report.json", output / "comparison_report.md"):
            if path.exists():
                path.unlink()
    return {key: int(value) for key, value in manifest.items() if isinstance(value, int) and not isinstance(value, bool)}
