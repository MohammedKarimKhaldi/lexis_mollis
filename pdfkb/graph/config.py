from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GraphConfig:
    gazetteers: Path = Path("data/gazetteers")
    min_confidence: float = 0.70
    seed: int = 20260701
    limit_pages: int | None = None
    sigma_max_nodes: int = 10_000

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["gazetteers"] = str(self.gazetteers)
        return data

