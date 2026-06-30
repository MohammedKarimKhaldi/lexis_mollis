#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq


ELIGIBLE_RIGHTS = {"public_domain_claimed", "open_data_source"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Internet Archive eligibility report for source PDFs.")
    parser.add_argument("--documents", type=Path, default=Path("outputs_v2/release/documents/part-000.parquet"))
    parser.add_argument("--output", type=Path, default=Path("outputs_v2/release/internet_archive_report.json"))
    args = parser.parse_args()

    rows = pq.read_table(args.documents).to_pylist()
    eligible = []
    excluded = []
    for row in rows:
        rights = row.get("rights_status") or "to_review"
        record = {
            "document_id": row.get("document_id"),
            "source_filename": row.get("source_filename"),
            "source_sha256": row.get("source_sha256"),
            "title": row.get("title"),
            "rights_status": rights,
        }
        if rights in ELIGIBLE_RIGHTS:
            eligible.append(record)
        else:
            record["reason"] = "rights_status_not_publishable"
            excluded.append(record)

    report = {
        "eligible_count": len(eligible),
        "excluded_count": len(excluded),
        "eligible_rights": sorted(ELIGIBLE_RIGHTS),
        "eligible": eligible,
        "excluded": excluded,
        "status": "dry_run_report_only",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["eligible_count", "excluded_count", "status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

