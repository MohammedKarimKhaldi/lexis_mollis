from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from .inventory import sha256_file
from .ocr import process_page


def normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def run_benchmark(source: Path, cases_path: Path, dpi: int = 200) -> dict[str, Any]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    outcomes: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        pdf_path = source / case["filename"]
        result = process_page(
            pdf_path,
            sha256_file(pdf_path),
            int(case["page_number"]) - 1,
            case.get("year"),
            dpi=dpi,
        )
        checks: dict[str, bool] = {}
        text = normalized(result.selected.text)
        if "min_chars" in case:
            checks["min_chars"] = len(result.selected.text) >= int(case["min_chars"])
        if "contains" in case:
            checks["contains"] = all(normalized(fragment) in text for fragment in case["contains"])
        if "script" in case:
            checks["script"] = case["script"] in result.selected.scripts
        if "method_prefix" in case:
            checks["method_prefix"] = result.selected.method.startswith(case["method_prefix"])
        if "review_required" in case:
            checks["review_required"] = result.review_required is bool(case["review_required"])
        success = all(checks.values())
        passed += int(success)
        outcomes.append(
            {
                "name": case["name"],
                "category": case["category"],
                "passed": success,
                "checks": checks,
                "method": result.selected.method,
                "char_count": len(result.selected.text),
                "quality_score": round(result.quality_score, 4),
                "scripts": result.selected.scripts,
                "languages": result.selected.languages,
                "review_reasons": result.review_reasons,
            }
        )
    return {"cases": len(cases), "passed": passed, "failed": len(cases) - passed, "outcomes": outcomes}

