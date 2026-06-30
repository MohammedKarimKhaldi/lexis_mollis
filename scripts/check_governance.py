#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "LICENSE",
    "LICENSE-DATA",
    "CITATION.cff",
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    ".zenodo.json",
    ".github/ISSUE_TEMPLATE/source_request.yml",
    ".github/ISSUE_TEMPLATE/transcription_fix.yml",
    ".github/ISSUE_TEMPLATE/relation_report.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
]

FORBIDDEN_TRACKED = re.compile(
    r"(^|/)(token|.*\.env($|\.)|.*\.sqlite3($|-)|.*\.parquet$|.*\.npy$|.*\.faiss$|.*\.index$)",
    re.IGNORECASE,
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_yaml(path: Path) -> dict:
    try:
        import yaml
    except Exception as exc:  # pragma: no cover - dependency guard
        fail(f"PyYAML is required to validate {path.name}: {exc}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"{path} must contain a YAML mapping")
    return data


def tracked_files() -> Iterable[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if not path.exists():
            fail(f"missing required governance file: {rel}")

    citation = load_yaml(ROOT / "CITATION.cff")
    for key in ["cff-version", "message", "title", "authors", "license", "version"]:
        if key not in citation:
            fail(f"CITATION.cff missing required key: {key}")
    if citation["license"] != "CC-BY-4.0":
        fail("CITATION.cff license must be CC-BY-4.0")
    if len(citation.get("authors") or []) < 2:
        fail("CITATION.cff must list at least two authors")

    zenodo = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    if zenodo.get("license") != "CC-BY-4.0":
        fail(".zenodo.json license must be CC-BY-4.0")
    if len(zenodo.get("creators") or []) != 2:
        fail(".zenodo.json must list exactly two creators")

    readme = (ROOT / "README.md").read_text(encoding="utf-8").casefold()
    for needle in ["apache-2.0", "cc-by-4.0", "ocr", "mohammed-karim khaldi", "reda rostane"]:
        if needle not in readme:
            fail(f"README.md must mention {needle!r}")

    forbidden = [path for path in tracked_files() if FORBIDDEN_TRACKED.search(path)]
    if forbidden:
        fail("forbidden tracked files: " + ", ".join(forbidden))

    print("governance_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

