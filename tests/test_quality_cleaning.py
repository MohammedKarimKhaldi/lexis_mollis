from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pdfkb.cleaning import clean_document
from pdfkb.models import Candidate, PageResult, TextBlock
from pdfkb.quality import agreement, score_candidate, scripts_in_text
from pdfkb.state import PipelineState


def page(number: int, text: str) -> PageResult:
    candidate = Candidate(
        method="test",
        text=text,
        blocks=[TextBlock(line, (0.1, index * 0.05, 0.9, index * 0.05 + 0.03), 0.9) for index, line in enumerate(text.splitlines()) if line],
        confidence=0.9,
    )
    score_candidate(candidate)
    return PageResult(
        source_sha256="a" * 64,
        page_number=number,
        page_count=3,
        width=595,
        height=842,
        rotation=0,
        ink_ratio=0.1,
        selected=candidate,
        candidates=[candidate],
        agreement=None,
        quality_score=candidate.score,
        review_required=False,
        review_priority="none",
        review_reasons=[],
    )


class QualityTests(unittest.TestCase):
    def test_scripts_are_unicode_based(self) -> None:
        self.assertEqual(scripts_in_text("中华人民共和国"), ["Han"])
        self.assertIn("Cyrillic", scripts_in_text("Министерство Иностранных Дел"))

    def test_agreement_ignores_spacing_and_case(self) -> None:
        self.assertGreater(agreement("Bonjour le monde diplomatique", "BONJOUR  le monde diplomatique"), 0.99)

    def test_recurring_headers_removed_only_from_clean_layer(self) -> None:
        pages = [
            page(1, "ARCHIVES DIPLOMATIQUES\nLe présent accord se poursuit\nsur cette ligne.\n1"),
            page(2, "ARCHIVES DIPLOMATIQUES\nUne autre disposition figure\nsur cette page.\n2"),
            page(3, "ARCHIVES DIPLOMATIQUES\nLa dernière disposition figure\nici.\n3"),
        ]
        clean_document(pages)
        self.assertNotIn("ARCHIVES DIPLOMATIQUES", pages[0].cleaned_text)
        self.assertIn("ARCHIVES DIPLOMATIQUES", pages[0].selected.text)

    def test_state_round_trip(self) -> None:
        result = page(1, "Texte fidèle et suffisamment long pour le test.")
        with tempfile.TemporaryDirectory() as directory:
            with PipelineState(Path(directory) / "state.sqlite3") as state:
                state.save_page(result)
                loaded = state.load_page(result.source_sha256, 1)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.selected.text, result.selected.text)
                self.assertTrue(state.page_is_done(result.source_sha256, 1))
                state.save_error(result.source_sha256, 1, "échec de nouvelle tentative")
                preserved = state.load_page(result.source_sha256, 1)
                self.assertIsNotNone(preserved)
                self.assertEqual(preserved.selected.text, result.selected.text)
                self.assertEqual(len(state.errors()), 1)


if __name__ == "__main__":
    unittest.main()
