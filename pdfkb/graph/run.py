from __future__ import annotations

import json
from pathlib import Path

from pdfkb.similarity.io import read_jsonl, read_parquet_records, write_parquet_records

from .build import build_edges, serialize_graph
from .config import GraphConfig
from .entities import extract_mentions
from .gazetteers import build_matcher, load_all_gazetteers
from .linking import document_records_from_pages, load_doc_type_mapping, resolve_nodes


def build(kb: Path, similarity: Path | None, output: Path, ontology: Path, cfg: GraphConfig) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    pages = read_jsonl(kb, limit=cfg.limit_pages)
    entries = load_all_gazetteers(cfg.gazetteers)
    matcher = build_matcher(entries)
    mentions = []
    for page in pages:
        mentions.extend(extract_mentions(page, matcher, cfg))

    documents = document_records_from_pages(pages)
    nodes, mention_links = resolve_nodes(mentions, documents, load_doc_type_mapping())

    nodes_pq = write_parquet_records(nodes, output / "nodes.parquet")
    mention_links_pq = write_parquet_records(mention_links, output / "mention_links.parquet")
    edges_pq = build_edges(nodes, documents, mention_links, similarity, output)
    ttl_path, jsonld_path, sigma_path, summary_path = serialize_graph(nodes_pq, edges_pq, output, cfg)

    manifest = {
        "pages": len(pages),
        "documents": len(documents),
        "gazetteer_entries": len(entries),
        "mentions": len(mentions),
        "nodes": len(read_parquet_records(nodes_pq)),
        "edges": len(read_parquet_records(edges_pq)),
        "nodes_path": str(nodes_pq),
        "edges_path": str(edges_pq),
        "mention_links_path": str(mention_links_pq),
        "graph_ttl": str(ttl_path),
        "graph_jsonld": str(jsonld_path),
        "graph_sigma": str(sigma_path),
        "summary_path": str(summary_path),
        "ontology": str(ontology),
        "config": cfg.to_dict(),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest

