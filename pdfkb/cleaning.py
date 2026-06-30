from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from .models import PageResult, TextBlock

SPACE_RE = re.compile(r"[\t\u00a0\u2000-\u200b\u202f\u205f\u3000]+")
MULTISPACE_RE = re.compile(r" {2,}")
LIST_RE = re.compile(r"^(?:[-–—•*▪◦]|\(?\d+[.)]|[A-Za-z][.)]|[IVXLCDM]+[.)])\s+")
SENTENCE_END_RE = re.compile(r"[.!?…:;»\]\)](?:[\"'’])?$")


def normalize_line(line: str) -> str:
    line = unicodedata.normalize("NFC", line)
    line = SPACE_RE.sub(" ", line)
    line = line.replace("\ufeff", "").replace("\u00ad", "")
    return line.strip()


def recurring_key(line: str) -> str:
    line = normalize_line(line).casefold()
    line = re.sub(r"\d+", "#", line)
    line = re.sub(r"[^\w#]+", " ", line, flags=re.UNICODE)
    return " ".join(line.split())


def find_recurring_marginal_lines(results: list[PageResult]) -> set[str]:
    if len(results) < 3:
        return set()
    occurrences: Counter[str] = Counter()
    for result in results:
        lines = [normalize_line(line) for line in result.selected.text.splitlines() if normalize_line(line)]
        keys = {recurring_key(line) for line in lines[:3] + lines[-3:]}
        occurrences.update(key for key in keys if len(key) >= 2)
    threshold = max(3, math.ceil(len(results) * 0.40))
    return {key for key, count in occurrences.items() if count >= threshold}


def _line_blocks(result: PageResult) -> dict[str, list[TextBlock]]:
    by_text: dict[str, list[TextBlock]] = {}
    for block in result.selected.blocks:
        by_text.setdefault(normalize_line(block.text), []).append(block)
    return by_text


def _may_join(previous: str, current: str, previous_block: TextBlock | None, current_block: TextBlock | None) -> bool:
    if not previous or not current:
        return False
    if SENTENCE_END_RE.search(previous) or LIST_RE.match(current):
        return False
    if previous.isupper() and len(previous) < 120:
        return False
    if current[0].isupper() and not previous.endswith("-"):
        return False
    if previous_block and current_block:
        same_margin = abs(previous_block.bbox[0] - current_block.bbox[0]) <= 0.08
        vertical_gap = current_block.bbox[1] - previous_block.bbox[3]
        if not same_margin or vertical_gap > 0.035:
            return False
    return True


def clean_page(result: PageResult, recurring: set[str]) -> tuple[str, list[str]]:
    lines = result.selected.text.splitlines()
    normalized = [normalize_line(line) for line in lines]
    nonempty_positions = [index for index, line in enumerate(normalized) if line]
    marginal = set(nonempty_positions[:3] + nonempty_positions[-3:])
    removed: list[str] = []
    kept: list[str] = []
    for index, line in enumerate(normalized):
        if line and index in marginal and recurring_key(line) in recurring:
            removed.append(line)
            continue
        kept.append(line)

    block_map = _line_blocks(result)
    paragraphs: list[str] = []
    current = ""
    current_block: TextBlock | None = None
    for line in kept:
        if not line:
            if current:
                paragraphs.append(current)
                current = ""
                current_block = None
            continue
        candidate_block = (block_map.get(line) or [None])[0]
        line = MULTISPACE_RE.sub(" ", line)
        if current and _may_join(current, line, current_block, candidate_block):
            if current.endswith("-") and line[0].islower() and current_block and current_block.bbox[2] >= 0.82:
                current = current[:-1] + line
            else:
                current += " " + line
        else:
            if current:
                paragraphs.append(current)
            current = line
        current_block = candidate_block
    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs).strip(), removed


def clean_document(results: list[PageResult]) -> list[PageResult]:
    recurring = find_recurring_marginal_lines(results)
    for result in results:
        result.cleaned_text, result.removed_lines = clean_page(result, recurring)
    return results

