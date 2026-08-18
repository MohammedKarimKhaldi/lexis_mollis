from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from pdfkb.semantica import export_semantica_graph, sigma_to_semantica

SAMPLE_SIGMA_GRAPH = {
    "nodes": [
        {
            "id": "doc:a",
            "label": "Document A",
            "type": "Document",
            "x": 0.25,
            "y": -0.5,
            "size": 8,
            "document_id": "a",
        },
        {
            "id": "topic:b",
            "label": "Topic B",
            "type": "TopicConcept",
            "x": 0.75,
            "y": 0.5,
            "size": 3,
        },
    ],
    "edges": [
        {
            "source": "doc:a",
            "target": "topic:b",
            "type": "about_topic",
            "weight": 0.9,
            "provisional": True,
        }
    ],
}


class SemanticaAdapterTests(unittest.TestCase):
    def test_sigma_to_semantica_preserves_graph_and_display_properties(self) -> None:
        converted = sigma_to_semantica(SAMPLE_SIGMA_GRAPH)

        self.assertEqual(len(converted["nodes"]), 2)
        self.assertEqual(len(converted["edges"]), 1)
        self.assertEqual(converted["nodes"][0]["content"], "Document A")
        self.assertEqual(converted["nodes"][0]["properties"]["x"], 0.25)
        self.assertEqual(converted["nodes"][0]["properties"]["document_id"], "a")
        self.assertTrue(converted["edges"][0]["metadata"]["provisional"])

    def test_sigma_to_semantica_rejects_dangling_edges(self) -> None:
        payload = {
            "nodes": [{"id": "doc:a"}],
            "edges": [{"source": "doc:a", "target": "doc:missing"}],
        }
        with self.assertRaisesRegex(ValueError, "unknown node"):
            sigma_to_semantica(payload)

    @unittest.skipUnless(importlib.util.find_spec("semantica"), "Semantica optional extra is not installed")
    def test_export_round_trips_through_semantica_explorer(self) -> None:
        from semantica.explorer.session import GraphSession

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "graph.sigma.json"
            output = temporary / "graph.semantica.json"
            source.write_text(json.dumps(SAMPLE_SIGMA_GRAPH), encoding="utf-8")

            manifest = export_semantica_graph(source, output)
            session = GraphSession.from_file(str(output))

            self.assertEqual(manifest["engine"], "semantica")
            self.assertEqual(manifest["nodes"], 2)
            self.assertEqual(manifest["edges"], 1)
            self.assertEqual(session.get_stats()["node_count"], 2)
            self.assertEqual(session.get_stats()["edge_count"], 1)
            self.assertEqual(session.get_node("doc:a")["properties"]["x"], 0.25)


if __name__ == "__main__":
    unittest.main()
