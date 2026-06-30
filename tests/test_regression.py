from __future__ import annotations

import json
import unittest
from pathlib import Path

from pdfkb.benchmark import run_benchmark


class CorpusRegressionTests(unittest.TestCase):
    def test_stratified_benchmark(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = root / "traites"
        cases_path = root / "benchmarks" / "cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        missing = [case["filename"] for case in cases if not (source / case["filename"]).exists()]
        if missing:
            self.skipTest("local PDF benchmark corpus is unavailable: " + ", ".join(missing[:3]))
        report = run_benchmark(source, cases_path, dpi=200)
        failures = [outcome for outcome in report["outcomes"] if not outcome["passed"]]
        self.assertEqual(failures, [], failures)


if __name__ == "__main__":
    unittest.main()
