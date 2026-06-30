from __future__ import annotations

from dataclasses import dataclass
import re


MONTHS = {
    "janvier": 1,
    "january": 1,
    "février": 2,
    "fevrier": 2,
    "february": 2,
    "mars": 3,
    "march": 3,
    "avril": 4,
    "april": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "june": 6,
    "juillet": 7,
    "july": 7,
    "août": 8,
    "aout": 8,
    "august": 8,
    "septembre": 9,
    "september": 9,
    "octobre": 10,
    "october": 10,
    "novembre": 11,
    "november": 11,
    "décembre": 12,
    "decembre": 12,
    "december": 12,
}

MONTH_PATTERN = "|".join(sorted((re.escape(month) for month in MONTHS), key=len, reverse=True))
TEXTUAL_DATE_RE = re.compile(rf"\b(?:le\s+)?([0-9]{{1,2}})\s+({MONTH_PATTERN})\s+([12][0-9]{{3}})\b", re.IGNORECASE)
NUMERIC_DATE_RE = re.compile(r"\b([0-3]?[0-9])[/-]([01]?[0-9])[/-]([12][0-9]{3})\b")


@dataclass(frozen=True)
class DateMention:
    surface: str
    start: int
    end: int
    iso_date: str
    confidence: float


def extract_dates(text: str) -> list[DateMention]:
    mentions: list[DateMention] = []
    for match in TEXTUAL_DATE_RE.finditer(text):
        day = int(match.group(1))
        month = MONTHS[match.group(2).casefold()]
        year = int(match.group(3))
        if _valid_date(year, month, day):
            mentions.append(DateMention(match.group(0), match.start(), match.end(), f"{year:04d}-{month:02d}-{day:02d}", 0.95))
    for match in NUMERIC_DATE_RE.finditer(text):
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        if _valid_date(year, month, day):
            mentions.append(DateMention(match.group(0), match.start(), match.end(), f"{year:04d}-{month:02d}-{day:02d}", 0.85))
    return mentions


def _valid_date(year: int, month: int, day: int) -> bool:
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return False
    if month in {4, 6, 9, 11} and day > 30:
        return False
    if month == 2 and day > 29:
        return False
    return 1400 <= year <= 2100

