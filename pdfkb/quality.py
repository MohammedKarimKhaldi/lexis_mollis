from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from langdetect import DetectorFactory, LangDetectException, detect_langs

from .models import Candidate

DetectorFactory.seed = 0

WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)
NOISE_CHARS = set("�|¦¬~`^¤■□◆◇◊※")

SCRIPT_RANGES: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("Arabic", ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF))),
    ("Cyrillic", ((0x0400, 0x052F),)),
    ("Greek", ((0x0370, 0x03FF),)),
    ("Hebrew", ((0x0590, 0x05FF),)),
    ("Han", ((0x3400, 0x4DBF), (0x4E00, 0x9FFF))),
    ("Japanese", ((0x3040, 0x30FF),)),
    ("Hangul", ((0xAC00, 0xD7AF), (0x1100, 0x11FF))),
    ("Devanagari", ((0x0900, 0x097F),)),
    ("Thai", ((0x0E00, 0x0E7F),)),
    ("Lao", ((0x0E80, 0x0EFF),)),
    ("Latin", ((0x0041, 0x024F), (0x1E00, 0x1EFF))),
)


def scripts_in_text(text: str, minimum_ratio: float = 0.02) -> list[str]:
    counts: Counter[str] = Counter()
    total = 0
    for char in text:
        if not char.isalpha():
            continue
        total += 1
        code = ord(char)
        for script, ranges in SCRIPT_RANGES:
            if any(start <= code <= end for start, end in ranges):
                counts[script] += 1
                break
        else:
            counts["Other"] += 1
    if not total:
        return []
    return [name for name, count in counts.most_common() if count / total >= minimum_ratio]


def languages_in_text(text: str, maximum: int = 3) -> list[str]:
    sample = " ".join(text.split())[:12000]
    if len(sample) < 40:
        return []
    try:
        detected = detect_langs(sample)
    except LangDetectException:
        return []
    return [str(item.lang) for item in detected[:maximum] if item.prob >= 0.10]


def text_metrics(text: str) -> dict[str, float | int | bool]:
    stripped = text.strip()
    length = len(stripped)
    if not stripped:
        return {
            "char_count": 0,
            "word_count": 0,
            "printable_ratio": 0.0,
            "alnum_ratio": 0.0,
            "isolated_word_ratio": 1.0,
            "noise_ratio": 1.0,
            "replacement_count": 0,
            "private_use_count": 0,
        }
    printable = sum(char.isprintable() or char in "\n\t" for char in stripped)
    alnum = sum(char.isalnum() for char in stripped)
    words = WORD_RE.findall(stripped)
    isolated = sum(len(re.sub(r"\W", "", word, flags=re.UNICODE)) <= 1 for word in words)
    noise = sum(char in NOISE_CHARS for char in stripped)
    private = sum(unicodedata.category(char) == "Co" for char in stripped)
    return {
        "char_count": length,
        "word_count": len(words),
        "printable_ratio": printable / length,
        "alnum_ratio": alnum / length,
        "isolated_word_ratio": isolated / max(len(words), 1),
        "noise_ratio": noise / length,
        "replacement_count": stripped.count("�"),
        "private_use_count": private,
    }


def score_candidate(candidate: Candidate) -> float:
    metrics = text_metrics(candidate.text)
    candidate.metrics.update(metrics)
    length = int(metrics["char_count"])
    if length == 0:
        candidate.score = 0.0
        return 0.0
    printable = float(metrics["printable_ratio"])
    alnum = float(metrics["alnum_ratio"])
    isolated = float(metrics["isolated_word_ratio"])
    noise = float(metrics["noise_ratio"])
    replacements = int(metrics["replacement_count"])
    private = int(metrics["private_use_count"])

    # A healthy transcription can contain many punctuation marks, numbers or non-Latin text.
    alnum_score = max(0.0, 1.0 - abs(alnum - 0.72) / 0.72)
    token_score = max(0.0, 1.0 - isolated * 2.5)
    noise_score = max(0.0, 1.0 - noise * 20.0)
    evidence = min(1.0, math.log1p(length) / math.log(41))
    score = (
        0.36 * max(0.0, min(1.0, candidate.confidence))
        + 0.20 * printable
        + 0.14 * alnum_score
        + 0.14 * token_score
        + 0.10 * noise_score
        + 0.06 * evidence
    )
    score -= min(0.35, replacements * 0.04 + private * 0.01)
    candidate.score = max(0.0, min(1.0, score))
    if not candidate.scripts:
        candidate.scripts = scripts_in_text(candidate.text)
    if not candidate.languages:
        candidate.languages = languages_in_text(candidate.text)
    return candidate.score


def normalize_for_comparison(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in normalized if char.isalnum())


def agreement(left: str, right: str) -> float | None:
    a = normalize_for_comparison(left)
    b = normalize_for_comparison(right)
    if len(a) < 20 or len(b) < 20:
        return None
    # Bound the comparison cost on very long pages while sampling the full extent.
    if len(a) > 20000:
        a = a[:10000] + a[-10000:]
    if len(b) > 20000:
        b = b[:10000] + b[-10000:]
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def native_is_credible(candidate: Candidate) -> bool:
    metrics = candidate.metrics or text_metrics(candidate.text)
    return bool(
        int(metrics["char_count"]) >= 3
        and int(metrics["replacement_count"]) == 0
        and int(metrics["private_use_count"]) == 0
        and float(metrics["printable_ratio"]) >= 0.98
        and float(metrics["noise_ratio"]) <= 0.01
        and candidate.score >= 0.82
    )

