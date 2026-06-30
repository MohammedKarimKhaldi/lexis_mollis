from __future__ import annotations

import unittest

from pdfkb.ids import chunk_id, edge_key, node_id, slug, text_sha256


SHA = "a" * 64


class IdTests(unittest.TestCase):
    def test_slug_is_stable_ascii(self) -> None:
        self.assertEqual(slug("État fédéral — République 2026"), "etat_federal_republique_2026")
        self.assertEqual(slug("!!!"), "unknown")

    def test_text_sha256(self) -> None:
        self.assertEqual(
            text_sha256("Lexis Mollis"),
            "87930bd98e357cc7ce3547d085ae95d7094dc880eb332b7daa2e79df3f623965",
        )

    def test_chunk_id_format(self) -> None:
        self.assertEqual(chunk_id(SHA, 12, 3), f"{SHA}:p0012:c003")

    def test_chunk_id_rejects_bad_sha(self) -> None:
        with self.assertRaises(ValueError):
            chunk_id("BAD", 1, 0)

    def test_node_ids(self) -> None:
        self.assertEqual(node_id("Document", document_id="TRA001_s1"), "doc:TRA001_s1")
        self.assertEqual(node_id("Instrument", treaty_id="TRA001"), "instr:TRA001")
        self.assertEqual(node_id("Party", wikidata_qid="Q142"), "ent:wd:Q142")
        self.assertEqual(node_id("Organization", label="Organisation mondiale de la Santé"), "ent:Organization:organisation_mondiale_de_la_sante")
        self.assertEqual(node_id("Clause", source_sha256=SHA, page=1, idx=0), f"clause:{SHA}:p0001:c000")

    def test_symmetric_edge_key_orders_endpoints(self) -> None:
        self.assertEqual(
            edge_key("z", "a", "duplicate"),
            edge_key("a", "z", "duplicate"),
        )
        self.assertEqual(edge_key("z", "a", "issued_by"), "issued_by:z->a")


if __name__ == "__main__":
    unittest.main()
