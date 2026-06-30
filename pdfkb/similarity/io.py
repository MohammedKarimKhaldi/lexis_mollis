from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pyarrow as pa
import pyarrow.parquet as pq


def read_jsonl(path: Path, limit: int | None = None) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            records.append(json.loads(line))
            if limit is not None and len(records) >= limit:
                break
    return records


def read_parquet_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()


def write_parquet_records(records: Iterable[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(records)
    table = pa.Table.from_pylist(rows) if rows else pa.table({})
    pq.write_table(table, path)
    return path

