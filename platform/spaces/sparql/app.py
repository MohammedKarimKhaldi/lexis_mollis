from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from rdflib import Graph, Literal, Namespace, URIRef


DEFAULT_RDF = Path(__file__).resolve().parents[3] / "outputs_v2" / "release_pilot" / "graph" / "graph.ttl"
RDF_PATH = Path(os.getenv("RDF_PATH", DEFAULT_RDF))
SLO = Namespace("https://lexis-mollis.org/ontology/")


def load_graph() -> Graph:
  graph = Graph()
  if RDF_PATH.exists():
    graph.parse(RDF_PATH)
    return graph
  sample = URIRef("https://lexis-mollis.org/document/sample-declaration-001")
  graph.add((sample, SLO.title, Literal("Déclaration pilote sur la coopération internationale")))
  graph.add((sample, SLO.documentId, Literal("sample-declaration-001")))
  return graph


GRAPH = load_graph()

app = FastAPI(
  title="Lexis Mollis SPARQL",
  description="Read-only SPARQL endpoint scaffold for the Lexis Mollis RDF graph.",
  version="0.1.0",
)

origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]
app.add_middleware(
  CORSMiddleware,
  allow_origins=origins,
  allow_credentials=False,
  allow_methods=["GET", "POST"],
  allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
  return {"ok": True, "triple_count": len(GRAPH), "rdf_path": str(RDF_PATH)}


def serialize_results(results: Any) -> dict[str, Any]:
  bindings: list[dict[str, str]] = []
  for row in results:
    item: dict[str, str] = {}
    for key, value in row.asdict().items():
      item[str(key)] = str(value)
    bindings.append(item)
  return {"head": {"vars": [str(var) for var in results.vars]}, "results": {"bindings": bindings}}


@app.get("/sparql")
def sparql_get(query: Annotated[str, Query(description="SPARQL SELECT query")]) -> dict[str, Any]:
  lowered = query.lower()
  if any(keyword in lowered for keyword in ("insert", "delete", "load", "clear", "create", "drop")):
    return {"error": "This endpoint is read-only."}
  return serialize_results(GRAPH.query(query))


@app.post("/sparql")
async def sparql_post(request: Request) -> dict[str, Any]:
  body = await request.body()
  query = body.decode("utf-8")
  return sparql_get(query=query)
