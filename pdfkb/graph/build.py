from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from urllib.parse import quote

import networkx as nx
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, XSD

from pdfkb import PIPELINE_VERSION
from pdfkb.ids import edge_key, node_id, text_sha256
from pdfkb.similarity.io import read_parquet_records, write_parquet_records

from .config import GraphConfig


SLO = Namespace("https://lexis-mollis.org/ontology#")
SCHEMA = Namespace("https://schema.org/")
BASE_ID = "https://lexis-mollis.org/id/"

EDGE_PREDICATES = {
    "party_to": SLO.partyTo,
    "issued_by": SLO.issuedBy,
    "signed_at": SLO.signedAt,
    "dated": SLO.dated,
    "amends": SLO.amends,
    "supersedes": SLO.supersedes,
    "references": SLO.references,
    "translation_of": SLO.translationOf,
    "same_instrument_as": SLO.sameInstrumentAs,
    "similar_to": SLO.similarTo,
    "about_topic": SLO.aboutTopic,
    "translation": SLO.translation,
}


def build_edges(
    nodes: list[dict],
    documents: list[dict],
    mention_links: list[dict],
    similarity_dir: Path | None,
    out_dir: Path,
) -> Path:
    node_ids = {node["node_id"] for node in nodes}
    docs = {doc["document_id"]: doc for doc in documents}
    records: dict[str, dict] = {}

    for doc in documents:
        if not doc.get("treaty_id"):
            continue
        src = node_id("Document", document_id=doc["document_id"])
        dst = node_id("Instrument", treaty_id=doc["treaty_id"])
        _add_edge(
            records,
            {
                "src": src,
                "dst": dst,
                "level": "document",
                "type": "same_instrument_as",
                "lexical": None,
                "semantic": None,
                "combined": None,
                "quality_weight": doc.get("confidence"),
                "provisional": bool(doc.get("provisional")),
                "method": "metadata:treaty_id",
                "evidence": f"treaty_id={doc['treaty_id']}",
                "pipeline_version": doc.get("pipeline_version") or PIPELINE_VERSION,
            },
        )

    for link in mention_links:
        doc = docs.get(link["document_id"])
        if not doc or not doc.get("treaty_id"):
            continue
        instr = node_id("Instrument", treaty_id=doc["treaty_id"])
        mention_node = link["node_id"]
        edge_type: str | None = None
        src = mention_node
        dst = instr
        if link["type"] == "Party":
            edge_type = "party_to"
        elif link["type"] == "Organization":
            edge_type = "issued_by"
            src, dst = instr, mention_node
        elif link["type"] == "Place":
            edge_type = "signed_at"
            src, dst = instr, mention_node
        elif link["type"] == "TopicConcept" and str(link["node_id"]).startswith("ent:TopicConcept:date_"):
            edge_type = "dated"
            src, dst = instr, mention_node
        if edge_type is None:
            continue
        _add_edge(
            records,
            {
                "src": src,
                "dst": dst,
                "level": "entity",
                "type": edge_type,
                "lexical": None,
                "semantic": None,
                "combined": None,
                "quality_weight": float(link.get("confidence") or 0),
                "provisional": bool(link.get("provisional")),
                "method": link.get("method"),
                "evidence": f"{link['document_id']}:p{int(link['page_number']):04d}:{link['char_start']}-{link['char_end']}",
                "pipeline_version": doc.get("pipeline_version") or PIPELINE_VERSION,
            },
        )

    nodes_by_id = {node["node_id"]: node for node in nodes}
    for doc in documents:
        if not doc.get("treaty_id"):
            continue
        instr = node_id("Instrument", treaty_id=doc["treaty_id"])
        doc_node = nodes_by_id.get(node_id("Document", document_id=doc["document_id"]), {})
        for tag in doc_node.get("tags") or []:
            if not tag.startswith("instrument_type:"):
                continue
            topic_id = f"ent:TopicConcept:instrument_type_{tag.split(':', 1)[1]}"
            if topic_id not in node_ids:
                continue
            _add_edge(
                records,
                {
                    "src": instr,
                    "dst": topic_id,
                    "level": "entity",
                    "type": "about_topic",
                    "lexical": None,
                    "semantic": None,
                    "combined": None,
                    "quality_weight": 1.0,
                    "provisional": False,
                    "method": "doc_type_mapping",
                    "evidence": "metadata_design/doc_type_mapping.json",
                    "pipeline_version": doc.get("pipeline_version") or PIPELINE_VERSION,
                },
            )

    if similarity_dir is not None and (similarity_dir / "doc_edges.parquet").exists():
        for edge in read_parquet_records(similarity_dir / "doc_edges.parquet"):
            if edge["src"] in node_ids and edge["dst"] in node_ids:
                imported = dict(edge)
                imported["type"] = "similar_to" if imported["type"] == "similar_to" else imported["type"]
                imported["pipeline_version"] = imported.get("pipeline_version") or PIPELINE_VERSION
                _add_edge(records, imported)

    valid_records = [edge for edge in records.values() if edge["src"] in node_ids and edge["dst"] in node_ids]
    return write_parquet_records(sorted(valid_records, key=lambda row: (row["type"], row["src"], row["dst"])), out_dir / "edges.parquet")


def _add_edge(records: dict[str, dict], edge: dict) -> None:
    key = edge_key(edge["src"], edge["dst"], edge["type"])
    existing = records.get(key)
    if existing is None or float(edge.get("quality_weight") or 0) > float(existing.get("quality_weight") or 0):
        records[key] = edge


def serialize_graph(nodes_pq: Path, edges_pq: Path, out_dir: Path, cfg: GraphConfig) -> tuple[Path, Path, Path, Path]:
    nodes = read_parquet_records(nodes_pq)
    edges = read_parquet_records(edges_pq)
    ttl_path = out_dir / "graph.ttl"
    jsonld_path = out_dir / "graph.jsonld"
    sigma_path = out_dir / "graph.sigma.json"
    summary_path = out_dir / "summary.json"

    rdf = Graph()
    rdf.bind("slo", SLO)
    rdf.bind("schema", SCHEMA)
    rdf.bind("dcterms", DCTERMS)
    rdf.bind("owl", OWL)
    for node in nodes:
        subject = _uri(node["node_id"])
        rdf.add((subject, RDF.type, SLO[node["type"]]))
        rdf.add((subject, RDFS.label, Literal(node["label"])))
        if node.get("wikidata_qid"):
            rdf.add((subject, OWL.sameAs, URIRef(f"http://www.wikidata.org/entity/{node['wikidata_qid']}")))
        if node.get("year") is not None:
            rdf.add((subject, SCHEMA.datePublished, Literal(int(node["year"]), datatype=XSD.gYear)))
        if node.get("confidence") is not None:
            rdf.add((subject, SLO.qualityScore, Literal(float(node["confidence"]))))
        rdf.add((subject, SLO.provisional, Literal(bool(node.get("provisional")))))

    for edge in edges:
        src = _uri(edge["src"])
        dst = _uri(edge["dst"])
        predicate = EDGE_PREDICATES.get(edge["type"], SLO.references)
        rdf.add((src, predicate, dst))
        if edge.get("combined") is not None or edge["type"] in {"similar_to", "translation", "same_instrument_as"}:
            link = BNode(text_sha256(f"{edge['src']}|{edge['type']}|{edge['dst']}"))
            rdf.add((link, RDF.type, SLO.SimilarityLink))
            rdf.add((link, SLO.src, src))
            rdf.add((link, SLO.dst, dst))
            rdf.add((link, SLO.linkType, Literal(edge["type"])))
            if edge.get("combined") is not None:
                rdf.add((link, SLO.weight, Literal(float(edge["combined"]))))
            rdf.add((link, SLO.provisional, Literal(bool(edge.get("provisional")))))

    rdf.serialize(ttl_path, format="turtle")
    rdf.serialize(jsonld_path, format="json-ld", indent=2)
    _write_sigma(nodes, edges, sigma_path, cfg)
    _write_summary(nodes, edges, summary_path)
    return ttl_path, jsonld_path, sigma_path, summary_path


def _uri(node_identifier: str) -> URIRef:
    return URIRef(BASE_ID + quote(node_identifier, safe=""))


def _write_sigma(nodes: list[dict], edges: list[dict], path: Path, cfg: GraphConfig) -> None:
    graph = nx.Graph()
    for node in nodes[: cfg.sigma_max_nodes]:
        graph.add_node(node["node_id"])
    for edge in edges:
        if edge["src"] in graph and edge["dst"] in graph:
            graph.add_edge(edge["src"], edge["dst"], weight=float(edge.get("combined") or edge.get("quality_weight") or 1.0))
    positions = nx.spring_layout(graph, seed=cfg.seed, weight="weight") if graph.number_of_nodes() else {}
    degrees = dict(graph.degree())
    payload = {
        "nodes": [
            {
                "id": node["node_id"],
                "label": node["label"],
                "type": node["type"],
                "x": float(positions.get(node["node_id"], [0.0, 0.0])[0]),
                "y": float(positions.get(node["node_id"], [0.0, 0.0])[1]),
                "size": 1 + degrees.get(node["node_id"], 0),
            }
            for node in nodes
            if node["node_id"] in graph
        ],
        "edges": [
            {
                "source": edge["src"],
                "target": edge["dst"],
                "type": edge["type"],
                "weight": edge.get("combined") or edge.get("quality_weight") or 1.0,
            }
            for edge in edges
            if edge["src"] in graph and edge["dst"] in graph
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_summary(nodes: list[dict], edges: list[dict], path: Path) -> None:
    summary = {
        "nodes": len(nodes),
        "edges": len(edges),
        "node_types": dict(sorted(Counter(node["type"] for node in nodes).items())),
        "edge_types": dict(sorted(Counter(edge["type"] for edge in edges).items())),
        "provisional_nodes": sum(1 for node in nodes if node.get("provisional")),
        "provisional_edges": sum(1 for edge in edges if edge.get("provisional")),
    }
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
