from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from rdflib import Graph

from pdfkb.graph.config import GraphConfig
from pdfkb.graph.dates import extract_dates
from pdfkb.graph.gazetteers import build_matcher, load_all_gazetteers
from pdfkb.graph.run import build as build_graph
from pdfkb.similarity.io import read_parquet_records, write_parquet_records


SHA = "c" * 64


def page(document_id: str, page_number: int, text: str, treaty_id: str = "TRA19000001") -> dict:
    return {
        "document_id": document_id,
        "source_filename": f"{document_id}.PDF",
        "canonical_filename": f"{document_id}.PDF",
        "source_sha256": SHA,
        "title": "Convention de test",
        "treaty_id": treaty_id,
        "treaty_number": "001",
        "doc_type": "Convention",
        "year": 1900,
        "pipeline_version": "2.0.1",
        "page_number": page_number,
        "page_count": 1,
        "language": ["fr"],
        "script": ["Latin"],
        "method": "native_pymupdf",
        "quality_score": 0.94,
        "review_required": False,
        "review_priority": "none",
        "review_reasons": [],
        "text": text,
    }


class GraphTests(unittest.TestCase):
    def test_gazetteer_matcher_finds_qid(self) -> None:
        entries = load_all_gazetteers(Path("data/gazetteers"))
        matcher = build_matcher(entries)
        matches = matcher.find("La France signe à Paris.")
        self.assertTrue(any(match.entry.qid == "Q142" for match in matches))
        self.assertTrue(any(match.entry.qid == "Q90" for match in matches))

    def test_dates_fr_en(self) -> None:
        mentions = extract_dates("Signé le 24 octobre 1648 puis confirmed 25 October 1648.")
        self.assertEqual([mention.iso_date for mention in mentions], ["1648-10-24", "1648-10-25"])

    def test_build_graph_outputs_valid_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "pages.jsonl"
            pages = [
                page("doc_a", 1, "La France et la République française signent à Paris le 24 octobre 1900."),
                page("doc_b", 1, "The United Kingdom signs in London on 25 October 1900.", treaty_id="TRA19000002"),
            ]
            kb.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in pages) + "\n", encoding="utf-8")
            similarity = root / "similarity"
            similarity.mkdir()
            write_parquet_records(
                [
                    {
                        "src": "doc:doc_a",
                        "dst": "doc:doc_b",
                        "level": "document",
                        "type": "similar_to",
                        "lexical": 0.1,
                        "semantic": 0.8,
                        "combined": 0.45,
                        "quality_weight": 0.9,
                        "provisional": False,
                        "method": "test",
                        "evidence": "synthetic",
                        "pipeline_version": "2.0.1",
                    }
                ],
                similarity / "doc_edges.parquet",
            )
            out = root / "graph"
            manifest = build_graph(kb, similarity, out, Path("metadata_design/ontology.ttl"), GraphConfig())
            self.assertGreater(manifest["nodes"], 0)
            self.assertGreater(manifest["edges"], 0)

            nodes = read_parquet_records(out / "nodes.parquet")
            edges = read_parquet_records(out / "edges.parquet")
            node_ids = {node["node_id"] for node in nodes}
            self.assertEqual(sum(1 for node in nodes if node["wikidata_qid"] == "Q142"), 1)
            self.assertTrue(all(edge["src"] in node_ids and edge["dst"] in node_ids for edge in edges))

            node_schema = json.loads(Path("metadata_design/node.schema.json").read_text(encoding="utf-8"))
            edge_schema = json.loads(Path("metadata_design/edge.schema.json").read_text(encoding="utf-8"))
            node_validator = Draft202012Validator(node_schema)
            edge_validator = Draft202012Validator(edge_schema)
            for node_record in nodes:
                node_validator.validate(node_record)
            for edge_record in edges:
                edge_validator.validate(edge_record)

            rdf = Graph()
            rdf.parse(out / "graph.ttl", format="turtle")
            self.assertGreater(len(rdf), 0)

            sigma = json.loads((out / "graph.sigma.json").read_text(encoding="utf-8"))
            self.assertIn("nodes", sigma)
            self.assertIn("edges", sigma)
            self.assertTrue(all(isinstance(node["x"], float) and isinstance(node["y"], float) for node in sigma["nodes"]))


if __name__ == "__main__":
    unittest.main()

