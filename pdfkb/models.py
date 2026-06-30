from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class TextBlock:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None = None
    block_type: str = "line"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bbox"] = [round(v, 6) for v in self.bbox]
        if self.confidence is not None:
            data["confidence"] = round(self.confidence, 4)
        return data


@dataclass(slots=True)
class Candidate:
    method: str
    text: str
    blocks: list[TextBlock] = field(default_factory=list)
    confidence: float = 0.0
    score: float = 0.0
    languages: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    variant: str = "original"
    metrics: dict[str, float | int | str | bool] = field(default_factory=dict)

    def to_dict(self, include_blocks: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "method": self.method,
            "variant": self.variant,
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "score": round(self.score, 4),
            "languages": self.languages,
            "scripts": self.scripts,
            "metrics": self.metrics,
        }
        if include_blocks:
            data["blocks"] = [block.to_dict() for block in self.blocks]
        return data


@dataclass(slots=True)
class PageResult:
    source_sha256: str
    page_number: int
    page_count: int
    width: float
    height: float
    rotation: int
    ink_ratio: float
    selected: Candidate
    candidates: list[Candidate]
    agreement: float | None
    quality_score: float
    review_required: bool
    review_priority: str
    review_reasons: list[str]
    cleaned_text: str = ""
    removed_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "page_number": self.page_number,
            "page_count": self.page_count,
            "width": round(self.width, 3),
            "height": round(self.height, 3),
            "rotation": self.rotation,
            "ink_ratio": round(self.ink_ratio, 6),
            "selected_method": self.selected.method,
            "selected_variant": self.selected.variant,
            "raw_text": self.selected.text,
            "cleaned_text": self.cleaned_text,
            "selected_blocks": [b.to_dict() for b in self.selected.blocks],
            "candidates": [c.to_dict() for c in self.candidates],
            "agreement": None if self.agreement is None else round(self.agreement, 4),
            "quality_score": round(self.quality_score, 4),
            "review_required": self.review_required,
            "review_priority": self.review_priority,
            "review_reasons": self.review_reasons,
            "removed_lines": self.removed_lines,
            "languages": self.selected.languages,
            "scripts": self.selected.scripts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PageResult":
        def block_from_dict(block: dict[str, Any]) -> TextBlock:
            return TextBlock(
                text=block["text"],
                bbox=tuple(block["bbox"]),
                confidence=block.get("confidence"),
                block_type=block.get("block_type", "line"),
            )

        def candidate_from_dict(candidate: dict[str, Any]) -> Candidate:
            return Candidate(
                method=candidate["method"],
                text=candidate.get("text", ""),
                blocks=[block_from_dict(b) for b in candidate.get("blocks", [])],
                confidence=float(candidate.get("confidence", 0.0)),
                score=float(candidate.get("score", 0.0)),
                languages=list(candidate.get("languages", [])),
                scripts=list(candidate.get("scripts", [])),
                variant=candidate.get("variant", "original"),
                metrics=dict(candidate.get("metrics", {})),
            )

        candidates = [candidate_from_dict(c) for c in data.get("candidates", [])]
        selected_method = data.get("selected_method")
        selected_variant = data.get("selected_variant", "original")
        selected = next(
            (c for c in candidates if c.method == selected_method and c.variant == selected_variant),
            None,
        )
        if selected is None:
            selected = Candidate(
                method=selected_method or "unknown",
                text=data.get("raw_text", ""),
                blocks=[block_from_dict(b) for b in data.get("selected_blocks", [])],
                languages=list(data.get("languages", [])),
                scripts=list(data.get("scripts", [])),
                score=float(data.get("quality_score", 0.0)),
                variant=selected_variant,
            )
            candidates.insert(0, selected)
        return cls(
            source_sha256=data["source_sha256"],
            page_number=int(data["page_number"]),
            page_count=int(data["page_count"]),
            width=float(data["width"]),
            height=float(data["height"]),
            rotation=int(data.get("rotation", 0)),
            ink_ratio=float(data.get("ink_ratio", 0.0)),
            selected=selected,
            candidates=candidates,
            agreement=data.get("agreement"),
            quality_score=float(data.get("quality_score", 0.0)),
            review_required=bool(data.get("review_required", False)),
            review_priority=data.get("review_priority", "none"),
            review_reasons=list(data.get("review_reasons", [])),
            cleaned_text=data.get("cleaned_text", ""),
            removed_lines=list(data.get("removed_lines", [])),
        )


@dataclass(slots=True)
class DocumentRecord:
    filename: str
    path: str
    sha256: str
    canonical_filename: str
    page_count: int
    metadata: list[dict[str, Any]] = field(default_factory=list)
