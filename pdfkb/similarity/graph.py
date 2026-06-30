from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median

from pdfkb import PIPELINE_VERSION

from .config import SimilarityConfig
from .io import read_parquet_records, write_parquet_records


def _document_edge_type(chunk_type: str) -> str:
    if chunk_type == "duplicate":
        return "same_instrument_as"
    if chunk_type == "translation":
        return "translation"
    return "similar_to"


def document_edges(chunk_edges_pq: Path, chunks_pq: Path, cfg: SimilarityConfig, out_dir: Path) -> Path:
    chunks = {chunk["chunk_id"]: chunk for chunk in read_parquet_records(chunks_pq)}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for edge in read_parquet_records(chunk_edges_pq):
        left = chunks.get(edge["src"])
        right = chunks.get(edge["dst"])
        if not left or not right:
            continue
        doc_a = left["document_id"]
        doc_b = right["document_id"]
        if doc_a == doc_b:
            continue
        a, b = sorted((doc_a, doc_b))
        groups[(a, b)].append(edge)

    records: list[dict] = []
    for (src, dst), edges in sorted(groups.items()):
        best = max(edges, key=lambda e: float(e.get("combined") or 0))
        qualities = [float(edge.get("quality_weight") or 0) for edge in edges]
        type_counts = Counter(_document_edge_type(edge["type"]) for edge in edges)
        doc_type = type_counts.most_common(1)[0][0]
        records.append(
            {
                "src": f"doc:{src}",
                "dst": f"doc:{dst}",
                "level": "document",
                "type": doc_type,
                "lexical": best.get("lexical"),
                "semantic": best.get("semantic"),
                "combined": best.get("combined"),
                "quality_weight": round(sum(qualities) / len(qualities), 6) if qualities else None,
                "provisional": all(bool(edge.get("provisional")) for edge in edges),
                "method": "chunk_edge_aggregation:max_combined",
                "evidence": f"chunk_pairs={len(edges)}",
                "pipeline_version": best.get("pipeline_version") or PIPELINE_VERSION,
            }
        )

    return write_parquet_records(records, out_dir / "doc_edges.parquet")


def cluster_documents(doc_edges_pq: Path, cfg: SimilarityConfig, out_dir: Path, chunks_pq: Path | None = None) -> tuple[Path, Path]:
    import networkx as nx
    from networkx.algorithms.community import louvain_communities

    graph = nx.Graph()
    if chunks_pq is not None and chunks_pq.exists():
        for chunk in read_parquet_records(chunks_pq):
            graph.add_node(f"doc:{chunk['document_id']}")

    edges = read_parquet_records(doc_edges_pq)
    for edge in edges:
        graph.add_edge(edge["src"], edge["dst"], weight=float(edge.get("combined") or 0))

    if graph.number_of_nodes() == 0:
        communities: list[set[str]] = []
    elif graph.number_of_edges() == 0:
        communities = [{node} for node in sorted(graph.nodes)]
    else:
        communities = [set(group) for group in louvain_communities(graph, weight="weight", seed=cfg.seed)]

    clusters = [
        {
            "cluster_id": f"cluster_{idx:04d}",
            "documents": sorted(node.replace("doc:", "", 1) for node in members),
            "method": "networkx_louvain",
            "params": {"seed": cfg.seed},
        }
        for idx, members in enumerate(sorted(communities, key=lambda group: (min(group), len(group))))
    ]

    type_counts = Counter(edge["type"] for edge in edges)
    cluster_sizes = [len(cluster["documents"]) for cluster in clusters]
    provisional_count = sum(1 for edge in edges if edge.get("provisional"))
    summary = {
        "document_edges": len(edges),
        "edge_types": dict(sorted(type_counts.items())),
        "clusters": len(clusters),
        "cluster_size_median": median(cluster_sizes) if cluster_sizes else 0,
        "provisional_edge_ratio": round(provisional_count / len(edges), 6) if edges else 0,
    }

    clusters_path = out_dir / "clusters.json"
    summary_path = out_dir / "summary.json"
    clusters_path.write_text(json.dumps(clusters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return clusters_path, summary_path

