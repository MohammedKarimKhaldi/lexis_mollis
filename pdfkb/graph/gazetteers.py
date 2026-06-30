from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
import re
from typing import Iterable

from pdfkb.ids import WIKIDATA_QID_RE


@dataclass(frozen=True)
class GazEntry:
    label: str
    aliases: tuple[str, ...]
    qid: str | None
    iso3: str | None
    lang: str | None
    type: str

    @property
    def surfaces(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([self.label, *self.aliases]))


@dataclass(frozen=True)
class GazMatch:
    entry: GazEntry
    surface: str
    start: int
    end: int


def load_gazetteer(path: Path) -> list[GazEntry]:
    entries: list[GazEntry] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            qid = (row.get("qid") or "").strip() or None
            if qid and not WIKIDATA_QID_RE.fullmatch(qid):
                raise ValueError(f"{path}: invalid QID {qid!r}")
            aliases = tuple(alias.strip() for alias in (row.get("aliases") or "").split("|") if alias.strip())
            entries.append(
                GazEntry(
                    label=(row.get("label") or "").strip(),
                    aliases=aliases,
                    qid=qid,
                    iso3=(row.get("iso3") or "").strip() or None,
                    lang=(row.get("lang") or "").strip() or None,
                    type=(row.get("type") or "").strip(),
                )
            )
    return entries


def load_all_gazetteers(root: Path) -> list[GazEntry]:
    entries: list[GazEntry] = []
    for name in ["states.csv", "organizations.csv", "places.csv"]:
        path = root / name
        if path.exists():
            entries.extend(load_gazetteer(path))
    return entries


class Matcher:
    def __init__(self, entries: Iterable[GazEntry]) -> None:
        patterns: list[tuple[re.Pattern[str], GazEntry, str]] = []
        for entry in entries:
            for surface in sorted(entry.surfaces, key=len, reverse=True):
                if surface:
                    pattern = re.compile(rf"(?<!\w){re.escape(surface)}(?!\w)", re.IGNORECASE)
                    patterns.append((pattern, entry, surface))
        self.patterns = patterns

    def find(self, text: str) -> list[GazMatch]:
        matches: list[GazMatch] = []
        for pattern, entry, surface in self.patterns:
            for match in pattern.finditer(text):
                matches.append(GazMatch(entry=entry, surface=match.group(0) or surface, start=match.start(), end=match.end()))
        return _drop_overlaps(matches)


def _drop_overlaps(matches: list[GazMatch]) -> list[GazMatch]:
    ordered = sorted(matches, key=lambda item: (-(item.end - item.start), item.start, item.entry.label))
    accepted: list[GazMatch] = []
    occupied: set[int] = set()
    for match in ordered:
        span = set(range(match.start, match.end))
        if occupied.isdisjoint(span):
            accepted.append(match)
            occupied.update(span)
    return sorted(accepted, key=lambda item: (item.start, item.end, item.entry.label))


def build_matcher(entries: Iterable[GazEntry]) -> Matcher:
    return Matcher(entries)

