from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def load_site_data_module():
    path = Path("platform/scripts/build_site_data.py")
    spec = importlib.util.spec_from_file_location("lexis_build_site_data", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SiteDataTests(unittest.TestCase):
    def test_graph_communities_are_bounded_and_labelled(self) -> None:
        module = load_site_data_module()
        graph = {
            "nodes": [{"id": "doc:a"}, {"id": "doc:b"}, {"id": "doc:c"}],
            "edges": [],
        }
        clusters = [
            {
                "cluster_id": "cluster_0001",
                "documents": ["a", "b", "outside_projection"],
            }
        ]
        titles = {
            "a": "Instrument de ratification",
            "b": "Dépôt de la ratification",
            "c": "Autre document",
        }

        result = module.build_graph_communities(graph, clusters, titles)

        self.assertEqual(result["method"], "networkx_louvain")
        self.assertEqual(result["membership"]["doc:a"], "cluster_0001")
        self.assertEqual(result["membership"]["doc:c"], "community_other")
        self.assertEqual(result["communities"][0]["count"], 2)
        self.assertIn("Ratifications", result["communities"][0]["label"])


if __name__ == "__main__":
    unittest.main()
