from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import run_benchmark
from .export import export_outputs
from .pipeline import run_pipeline
from .state import PipelineState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdfkb", description="Pipeline OCR local et auditable")
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
    similarity_build = similarity_subparsers.add_parser("build", help="Construire chunks, index FAISS, arêtes et clusters")
    similarity_build.add_argument("--kb", type=Path, required=True, help="Fichier pages JSONL, ex. outputs_v2/kb/pages.jsonl")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        selected = [item.strip() for item in args.documents.split(",") if item.strip()] if args.documents else None
        manifest = run_pipeline(
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
    elif args.command == "audit":
        with PipelineState(args.state) as state:
            manifest = export_outputs(
                state,
                args.output,
                include_detailed_audit=not (args.light or args.no_detailed_audit),
                include_comparison=not (args.light or args.no_comparison),
            )
    elif args.command == "status":
        with PipelineState(args.state) as state:
            manifest = state.progress()
    elif args.command == "similarity":
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
        manifest = build_similarity(args.kb, args.output, cfg)
    else:
        manifest = run_benchmark(args.source, args.cases, dpi=args.dpi)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
