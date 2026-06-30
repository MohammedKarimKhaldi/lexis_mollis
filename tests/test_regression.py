from __future__ import annotations

import unittest
from pathlib import Path

from pdfkb.benchmark import run_benchmark


class CorpusRegressionTests(unittest.TestCase):
    def test_stratified_benchmark(self) -> None:
        root = Path(__file__).resolve().parents[1]
        report = run_benchmark(root / "traites", root / "benchmarks" / "cases.json", dpi=200)
        failures = [outcome for outcome in report["outcomes"] if not outcome["passed"]]
        self.assertEqual(failures, [], failures)


if __name__ == "__main__":
    unittest.main()

