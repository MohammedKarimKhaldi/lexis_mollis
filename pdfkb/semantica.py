from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


def _require_semantica_context_graph():
    try:
        from semantica.context import ContextGraph
    except ImportError as exc:  # pragma: no cover - exercised without the optional extra
        raise RuntimeError(
            "Semantica is required for this command. Install it with: pip install -e '.[semantica]'"
        ) from exc
    return ContextGraph


def _non_empty_text(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _object(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Sigma {field} must be an object")
    return dict(value)


def _convert_node(raw_node: Any, node_ids: set[str]) -> dict[str, Any]:
    if not isinstance(raw_node, dict):
        raise ValueError("Every Sigma node must be an object")
    node_id = _non_empty_text(raw_node.get("id"), "")
    if not node_id:
        raise ValueError("Every Sigma node must have a non-empty id")
    if node_id in node_ids:
        raise ValueError(f"Duplicate Sigma node id: {node_id}")
    node_ids.add(node_id)

    label = _non_empty_text(raw_node.get("label"), node_id)
    node_type = _non_empty_text(raw_node.get("type"), "Entity")
    properties = {
        key: value for key, value in raw_node.items() if key not in {"id", "label", "type", "metadata", "properties"}
    }
    properties.update(_object(raw_node.get("properties"), field="node properties"))
    properties.setdefault("label", label)

    metadata = _object(raw_node.get("metadata"), field="node metadata")
    metadata.setdefault("source_format", "sigma")
    return {
        "id": node_id,
        "type": node_type,
        "content": label,
        "properties": properties,
        "metadata": metadata,
    }


def _convert_edge(raw_edge: Any, node_ids: set[str]) -> dict[str, Any]:
    if not isinstance(raw_edge, dict):
        raise ValueError("Every Sigma edge must be an object")
    source = _non_empty_text(raw_edge.get("source"), "")
    target = _non_empty_text(raw_edge.get("target"), "")
    if not source or not target:
        raise ValueError("Every Sigma edge must have non-empty source and target ids")
    if source not in node_ids or target not in node_ids:
        raise ValueError(f"Sigma edge references an unknown node: {source} -> {target}")

    edge_type = _non_empty_text(raw_edge.get("type"), "related_to")
    metadata = {
        key: value
        for key, value in raw_edge.items()
        if key not in {"id", "familyId", "family_id", "source", "target", "type", "weight", "metadata", "properties"}
    }
    metadata.update(_object(raw_edge.get("properties"), field="edge properties"))
    metadata.update(_object(raw_edge.get("metadata"), field="edge metadata"))
    metadata.setdefault("source_format", "sigma")

    edge: dict[str, Any] = {
        "source": source,
        "target": target,
        "type": edge_type,
        "weight": float(raw_edge.get("weight", 1.0)),
        "metadata": metadata,
    }
    if raw_edge.get("id") is not None:
        edge["id"] = str(raw_edge["id"])
    family_id = raw_edge.get("familyId", raw_edge.get("family_id"))
    if family_id is not None:
        edge["familyId"] = str(family_id)
    return edge


def sigma_to_semantica(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert the published Sigma graph into Semantica ContextGraph data.

    Coordinates and display attributes live at the top level in the Sigma
    export. Semantica stores those values under ``properties``/``metadata``;
    moving them there preserves the existing layout for the Explorer without
    changing the source graph format used by the Astro site.
    """

    raw_nodes = payload.get("nodes", [])
    raw_edges = payload.get("edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("Sigma graph must contain list-valued 'nodes' and 'edges'")

    node_ids: set[str] = set()
    nodes = [_convert_node(raw_node, node_ids) for raw_node in raw_nodes]
    edges = [_convert_edge(raw_edge, node_ids) for raw_edge in raw_edges]
    return {"nodes": nodes, "edges": edges}


def export_semantica_graph(source: Path, output: Path) -> dict[str, Any]:
    """Build and persist a Semantica ContextGraph from a Sigma JSON export."""

    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Sigma graph not found: {source}")

    source_bytes = source.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    sigma_payload = json.loads(source_bytes)
    context_payload = sigma_to_semantica(sigma_payload)

    ContextGraph = _require_semantica_context_graph()  # noqa: N806 - class reference, not a constant
    graph = ContextGraph(
        advanced_analytics=False,
        centrality_analysis=False,
        community_detection=False,
        node_embeddings=False,
        extract_entities=False,
        extract_relationships=False,
    )
    graph.graph_id = f"urn:lexis-mollis:semantica:{source_sha256}"
    graph.from_dict(context_payload)

    expected_nodes = len(context_payload["nodes"])
    expected_edges = len(context_payload["edges"])
    if len(graph.nodes) != expected_nodes or len(graph.edges) != expected_edges:
        raise RuntimeError(
            "Semantica rejected part of the graph: "
            f"expected {expected_nodes} nodes/{expected_edges} edges, "
            f"loaded {len(graph.nodes)} nodes/{len(graph.edges)} edges"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        graph.save_to_file(str(temporary))
        temporary.replace(output)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise

    node_types = Counter(node["type"] for node in context_payload["nodes"])
    edge_types = Counter(edge["type"] for edge in context_payload["edges"])
    return {
        "engine": "semantica",
        "semantica_version": "0.6.0",
        "source": str(source),
        "source_sha256": source_sha256,
        "output": str(output),
        "nodes": expected_nodes,
        "edges": expected_edges,
        "node_types": dict(sorted(node_types.items())),
        "edge_types": dict(sorted(edge_types.items())),
    }


def serve_semantica_explorer(graph: Path, host: str, port: int, *, open_browser: bool) -> int:
    """Launch Semantica Knowledge Explorer for an exported ContextGraph."""

    graph = graph.resolve()
    if not graph.is_file():
        raise FileNotFoundError(f"Semantica graph not found: {graph}. Run 'pdfkb semantica export' first.")

    try:
        from semantica.explorer import main as explorer_main
    except ImportError as exc:  # pragma: no cover - exercised without the optional extra
        raise RuntimeError(
            "Semantica Explorer is required for this command. Install it with: pip install -e '.[semantica]'"
        ) from exc

    # Semantica's packaged Explorer only permits its React development origin
    # by default. Lexis Mollis consumes the same official API from the light
    # Astro/Worker interface during local development, so allow those loopback
    # origins without broadening access to arbitrary websites. An explicit
    # user value still wins.
    os.environ.setdefault(
        "EXPLORER_CORS_ORIGINS",
        ",".join(
            (
                "http://127.0.0.1:4321",
                "http://localhost:4321",
                "http://127.0.0.1:8787",
                "http://localhost:8787",
            )
        ),
    )

    arguments = ["--graph", str(graph), "--host", host, "--port", str(port)]
    if not open_browser:
        arguments.append("--no-browser")
    result = explorer_main(arguments)
    return int(result or 0)
