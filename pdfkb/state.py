from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from . import PIPELINE_VERSION
from .models import DocumentRecord, PageResult


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    filename TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    canonical_filename TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    pipeline_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);
CREATE TABLE IF NOT EXISTS pages (
    sha256 TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    pipeline_version TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sha256, page_number)
);
CREATE TABLE IF NOT EXISTS page_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    error TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class PipelineState:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, timeout=60)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES('pipeline_version', ?)",
            (PIPELINE_VERSION,),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PipelineState":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def replace_documents(self, documents: Iterable[DocumentRecord]) -> None:
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO documents(filename, path, sha256, canonical_filename, page_count,
                                      metadata_json, pipeline_version)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    path=excluded.path,
                    sha256=excluded.sha256,
                    canonical_filename=excluded.canonical_filename,
                    page_count=excluded.page_count,
                    metadata_json=excluded.metadata_json,
                    pipeline_version=excluded.pipeline_version
                """,
                [
                    (
                        d.filename,
                        d.path,
                        d.sha256,
                        d.canonical_filename,
                        d.page_count,
                        json.dumps(d.metadata, ensure_ascii=False),
                        PIPELINE_VERSION,
                    )
                    for d in documents
                ],
            )

    def page_is_done(self, sha256: str, page_number: int) -> bool:
        row = self.connection.execute(
            "SELECT status, pipeline_version FROM pages WHERE sha256=? AND page_number=?",
            (sha256, page_number),
        ).fetchone()
        return bool(row and row["status"] == "done" and row["pipeline_version"] == PIPELINE_VERSION)

    def save_page(self, result: PageResult) -> None:
        payload = json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO pages(sha256, page_number, status, result_json, error, pipeline_version)
                VALUES(?, ?, 'done', ?, NULL, ?)
                ON CONFLICT(sha256, page_number) DO UPDATE SET
                    status='done', result_json=excluded.result_json, error=NULL,
                    pipeline_version=excluded.pipeline_version, updated_at=CURRENT_TIMESTAMP
                """,
                (result.source_sha256, result.page_number, payload, PIPELINE_VERSION),
            )
            connection.execute(
                "DELETE FROM page_errors WHERE sha256=? AND page_number=? AND pipeline_version=?",
                (result.source_sha256, result.page_number, PIPELINE_VERSION),
            )

    def save_error(self, sha256: str, page_number: int, error: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO page_errors(sha256, page_number, error, pipeline_version) VALUES(?, ?, ?, ?)",
                (sha256, page_number, error[:2000], PIPELINE_VERSION),
            )
            # A failed retry must never replace a previously successful transcription.
            connection.execute(
                """
                INSERT INTO pages(sha256, page_number, status, result_json, error, pipeline_version)
                VALUES(?, ?, 'error', NULL, ?, ?)
                ON CONFLICT(sha256, page_number) DO NOTHING
                """,
                (sha256, page_number, error[:2000], PIPELINE_VERSION),
            )

    def load_page(self, sha256: str, page_number: int) -> PageResult | None:
        row = self.connection.execute(
            "SELECT result_json FROM pages WHERE sha256=? AND page_number=? AND status='done'",
            (sha256, page_number),
        ).fetchone()
        if not row or not row["result_json"]:
            return None
        return PageResult.from_dict(json.loads(row["result_json"]))

    def documents(self) -> list[DocumentRecord]:
        rows = self.connection.execute(
            "SELECT filename, path, sha256, canonical_filename, page_count, metadata_json "
            "FROM documents ORDER BY filename COLLATE NOCASE"
        ).fetchall()
        return [
            DocumentRecord(
                filename=row["filename"],
                path=row["path"],
                sha256=row["sha256"],
                canonical_filename=row["canonical_filename"],
                page_count=row["page_count"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def errors(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT sha256, page_number, error FROM page_errors
            WHERE pipeline_version=?
            UNION ALL
            SELECT sha256, page_number, error FROM pages
            WHERE status='error' AND pipeline_version=?
              AND NOT EXISTS (
                  SELECT 1 FROM page_errors e
                  WHERE e.sha256=pages.sha256 AND e.page_number=pages.page_number
                    AND e.pipeline_version=pages.pipeline_version
              )
            ORDER BY sha256, page_number
            """,
            (PIPELINE_VERSION, PIPELINE_VERSION),
        ).fetchall()

    def progress(self) -> dict[str, int | float | str]:
        total_row = self.connection.execute(
            """
            SELECT COALESCE(SUM(page_count), 0) AS total_pages
            FROM (
                SELECT sha256, MAX(page_count) AS page_count
                FROM documents
                GROUP BY sha256
            )
            """
        ).fetchone()
        done_row = self.connection.execute(
            "SELECT COUNT(*) AS done_pages FROM pages WHERE status='done' AND pipeline_version=?",
            (PIPELINE_VERSION,),
        ).fetchone()
        total = int(total_row["total_pages"])
        done = int(done_row["done_pages"])
        return {
            "pipeline_version": PIPELINE_VERSION,
            "physical_pages_total": total,
            "physical_pages_done": done,
            "physical_pages_remaining": max(0, total - done),
            "progress_percent": round(done / total * 100, 3) if total else 0.0,
            "errors": len(self.errors()),
        }
