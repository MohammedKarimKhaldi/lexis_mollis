from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .benchmark import run_benchmark
from .export import export_outputs
from .pipeline import run_pipeline
from .state import PipelineState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdfkb", description="Pipeline OCR local et auditable")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Journaliser les repli internes (OCR, embeddings) sur stderr en plus des erreurs",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Inventorier, extraire, nettoyer et exporter")
    run.add_argument("--source", type=Path, required=True, help="Répertoire contenant les PDF")
    run.add_argument("--metadata", type=Path, required=True, help="Métadonnées JSON")
    run.add_argument("--output", type=Path, required=True, help="Répertoire de sortie v2")
    run.add_argument("--state", type=Path, default=Path("metadata/pipeline.sqlite3"))
    run.add_argument("--workers", type=int, default=2)
    run.add_argument("--dpi", type=int, default=300)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--documents", help="Noms ou stems séparés par des virgules")
    run.add_argument("--limit", type=int)
    run.add_argument("--no-review-images", action="store_true")

    audit = subparsers.add_parser("audit", help="Reconstruire les exports depuis l'état SQLite")
    audit.add_argument("--state", type=Path, default=Path("metadata/pipeline.sqlite3"))
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument(
        "--light",
        action="store_true",
        help="Exporter un snapshot rapide sans audit détaillé ni rapport comparatif",
    )
    audit.add_argument(
        "--no-detailed-audit",
        action="store_true",
        help="Ne pas écrire audit/pages.jsonl avec candidats OCR et coordonnées",
    )
    audit.add_argument(
        "--no-comparison",
        action="store_true",
        help="Ne pas reconstruire les rapports de comparaison avec extracted/",
    )

    status = subparsers.add_parser("status", help="Afficher la progression enregistrée")
    status.add_argument("--state", type=Path, default=Path("metadata/pipeline.sqlite3"))

    benchmark = subparsers.add_parser("benchmark", help="Exécuter le banc de régression OCR")
    benchmark.add_argument("--source", type=Path, required=True)
    benchmark.add_argument("--cases", type=Path, default=Path("benchmarks/cases.json"))
    benchmark.add_argument("--dpi", type=int, default=200)
    benchmark.add_argument("--report", type=Path)

    similarity = subparsers.add_parser("similarity", help="Construire les similarités lexicales/sémantiques")
    similarity_subparsers = similarity.add_subparsers(dest="similarity_command", required=True)
    similarity_build = similarity_subparsers.add_parser(
        "build", help="Construire chunks, index FAISS, arêtes et clusters"
    )
    similarity_build.add_argument(
        "--kb", type=Path, required=True, help="Fichier pages JSONL, ex. outputs_v2/kb/pages.jsonl"
    )
    similarity_build.add_argument("--output", type=Path, required=True, help="Répertoire de sortie similarity/")
    similarity_build.add_argument("--model", default="sentence-transformers/LaBSE")
    similarity_build.add_argument(
        "--fallback-model",
        default="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    )
    similarity_build.add_argument("--target-tokens", type=int, default=384)
    similarity_build.add_argument("--overlap", type=int, default=64)
    similarity_build.add_argument("--minhash-perm", type=int, default=128)
    similarity_build.add_argument("--char-ngram", type=int, default=5)
    similarity_build.add_argument("--lsh-threshold", type=float, default=0.5)
    similarity_build.add_argument("--knn", type=int, default=20)
    similarity_build.add_argument("--w-lexical", type=float, default=0.5)
    similarity_build.add_argument("--w-semantic", type=float, default=0.5)
    similarity_build.add_argument("--t-duplicate", type=float, default=0.90)
    similarity_build.add_argument("--t-clause-reuse", type=float, default=0.60)
    similarity_build.add_argument("--t-translation", type=float, default=0.80)
    similarity_build.add_argument("--t-weak-link", type=float, default=0.70)
    similarity_build.add_argument("--batch-size", type=int, default=64)
    similarity_build.add_argument("--seed", type=int, default=20260701)
    similarity_build.add_argument("--limit-pages", type=int, help="Limiter le nombre de pages pour un pilote")
    similarity_build.add_argument(
        "--lexical-only",
        action="store_true",
        help="Pilote rapide sans embeddings/FAISS, utile pendant que l'OCR tourne",
    )

    graph = subparsers.add_parser("graph", help="Construire le knowledge graph")
    graph_subparsers = graph.add_subparsers(dest="graph_command", required=True)
    graph_build = graph_subparsers.add_parser("build", help="Construire nodes/edges/RDF/Sigma")
    graph_build.add_argument("--kb", type=Path, required=True, help="Fichier pages JSONL")
    graph_build.add_argument("--similarity", type=Path, help="Répertoire outputs_v2/similarity à importer")
    graph_build.add_argument("--output", type=Path, required=True, help="Répertoire de sortie graph/")
    graph_build.add_argument("--ontology", type=Path, default=Path("metadata_design/ontology.ttl"))
    graph_build.add_argument("--gazetteers", type=Path, default=Path("data/gazetteers"))
    graph_build.add_argument("--min-confidence", type=float, default=0.70)
    graph_build.add_argument("--seed", type=int, default=20260701)
    graph_build.add_argument("--limit-pages", type=int, help="Limiter le nombre de pages pour un pilote")

    semantica = subparsers.add_parser("semantica", help="Exporter et explorer le graphe avec Semantica")
    semantica_subparsers = semantica.add_subparsers(dest="semantica_command", required=True)
    semantica_export = semantica_subparsers.add_parser(
        "export", help="Convertir un export Sigma en ContextGraph Semantica"
    )
    semantica_export.add_argument(
        "--input",
        type=Path,
        default=Path("outputs_v2/graph/graph.sigma.json"),
        help="Export Sigma source",
    )
    semantica_export.add_argument(
        "--output",
        type=Path,
        default=Path("outputs_v2/graph/graph.semantica.json"),
        help="ContextGraph JSON destiné à Semantica Explorer",
    )
    semantica_serve = semantica_subparsers.add_parser(
        "serve", help="Lancer Semantica Knowledge Explorer pour le ContextGraph exporté"
    )
    semantica_serve.add_argument(
        "--graph",
        type=Path,
        default=Path("outputs_v2/graph/graph.semantica.json"),
    )
    semantica_serve.add_argument("--host", default="127.0.0.1")
    semantica_serve.add_argument("--port", type=int, default=8000)
    semantica_serve.add_argument("--no-browser", action="store_true")
    return parser


def _run_run(args: argparse.Namespace) -> dict:
    selected = [item.strip() for item in args.documents.split(",") if item.strip()] if args.documents else None
    return run_pipeline(
        source=args.source,
        metadata_path=args.metadata,
        output=args.output,
        state_path=args.state,
        workers=args.workers,
        resume=args.resume,
        selected=selected,
        limit=args.limit,
        dpi=args.dpi,
        save_review_images=not args.no_review_images,
    )


def _run_audit(args: argparse.Namespace) -> dict:
    with PipelineState(args.state) as state:
        return export_outputs(
            state,
            args.output,
            include_detailed_audit=not (args.light or args.no_detailed_audit),
            include_comparison=not (args.light or args.no_comparison),
        )


def _run_status(args: argparse.Namespace) -> dict:
    with PipelineState(args.state) as state:
        return state.progress()


def _run_similarity(args: argparse.Namespace) -> dict:
    from .similarity import SimilarityConfig
    from .similarity.run import build as build_similarity

    if args.similarity_command != "build":
        raise ValueError(f"Unknown similarity command: {args.similarity_command}")
    cfg = SimilarityConfig(
        model=args.model,
        fallback_model=args.fallback_model,
        target_tokens=args.target_tokens,
        overlap_tokens=args.overlap,
        minhash_perm=args.minhash_perm,
        char_ngram=args.char_ngram,
        lsh_threshold=args.lsh_threshold,
        knn=args.knn,
        w_lexical=args.w_lexical,
        w_semantic=args.w_semantic,
        t_duplicate=args.t_duplicate,
        t_clause_reuse=args.t_clause_reuse,
        t_translation=args.t_translation,
        t_weak_link=args.t_weak_link,
        batch_size=args.batch_size,
        seed=args.seed,
        lexical_only=args.lexical_only,
        limit_pages=args.limit_pages,
    )
    return build_similarity(args.kb, args.output, cfg)


def _run_graph(args: argparse.Namespace) -> dict:
    from .graph import GraphConfig
    from .graph.run import build as build_graph

    if args.graph_command != "build":
        raise ValueError(f"Unknown graph command: {args.graph_command}")
    cfg = GraphConfig(
        gazetteers=args.gazetteers,
        min_confidence=args.min_confidence,
        seed=args.seed,
        limit_pages=args.limit_pages,
    )
    return build_graph(args.kb, args.similarity, args.output, args.ontology, cfg)


def _run_semantica(args: argparse.Namespace) -> dict | int:
    from .semantica import export_semantica_graph, serve_semantica_explorer

    if args.semantica_command == "export":
        return export_semantica_graph(args.input, args.output)
    if args.semantica_command == "serve":
        return serve_semantica_explorer(
            args.graph,
            args.host,
            args.port,
            open_browser=not args.no_browser,
        )
    raise ValueError(f"Unknown Semantica command: {args.semantica_command}")


def _run_benchmark(args: argparse.Namespace) -> dict:
    manifest = run_benchmark(args.source, args.cases, dpi=args.dpi)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


_COMMAND_HANDLERS = {
    "run": _run_run,
    "audit": _run_audit,
    "status": _run_status,
    "similarity": _run_similarity,
    "graph": _run_graph,
    "semantica": _run_semantica,
    "benchmark": _run_benchmark,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    result = _COMMAND_HANDLERS[args.command](args)
    if args.command == "semantica" and args.semantica_command == "serve":
        return result
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
