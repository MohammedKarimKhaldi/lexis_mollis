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
    else:
        manifest = run_benchmark(args.source, args.cases, dpi=args.dpi)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
