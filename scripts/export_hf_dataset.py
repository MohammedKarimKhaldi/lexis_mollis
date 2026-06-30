#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


CARD = """---
license: cc-by-4.0
pretty_name: Lexis Mollis — soft-law corpus
language:
  - fr
  - en
  - ar
  - zh
  - ru
tags:
  - soft-law
  - OCR
  - knowledge-graph
  - semantic-search
configs:
  - config_name: documents
    data_files: documents/*.parquet
  - config_name: pages
    data_files: pages/*.parquet
  - config_name: chunks
    data_files: chunks/*.parquet
  - config_name: edges
    data_files: edges/*.parquet
  - config_name: nodes
    data_files: nodes/*.parquet
---

# Lexis Mollis — base ouverte de droit souple

Corpus ouvert de droit souple avec OCR fidèle et auditable, knowledge base,
knowledge graph et similarités documentaires.

Attribution requise : **Mohammed-Karim Khaldi, Reda Rostane — Lexis Mollis**.

## Avertissement qualité/OCR

Les textes proviennent de PDF historiques et multilingues. Les pages faibles sont
conservées avec `quality_score`, `review_required` et `review_priority`. Ne pas
traiter les transcriptions comme vérité absolue sans vérifier les pages signalées.
Aucune correction générative ou reformulation n'est appliquée au texte OCR.

## Licence

Données dérivées sous CC-BY-4.0. Les textes officiels sous-jacents peuvent relever
de conditions propres à leur source ; consulter `rights_status`.

## Tables

- `documents`: métadonnées documentaires.
- `pages`: texte page par page.
- `chunks`: segments KB pour embeddings.
- `edges`: similarités et relations KG.
- `nodes`: nœuds du knowledge graph.
- `graph/`: exports RDF/JSON-LD/Sigma.

Voir `metadata_design/data_dictionary.md` dans le dépôt source pour le dictionnaire
complet.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or upload a Hugging Face dataset folder.")
    parser.add_argument("--release", type=Path, default=Path("outputs_v2/release"))
    parser.add_argument("--repo-id", default="lexis-mollis/soft-law-corpus")
    parser.add_argument("--workdir", type=Path, default=Path("outputs_v2/hf_dataset"))
    parser.add_argument("--upload", action="store_true", help="Upload with HF_TOKEN; default is local dry-run only.")
    args = parser.parse_args()

    if args.workdir.exists():
        shutil.rmtree(args.workdir)
    shutil.copytree(args.release, args.workdir)
    (args.workdir / "README.md").write_text(CARD, encoding="utf-8")

    if args.upload:
        token = os.environ.get("HF_TOKEN")
        if not token:
            raise SystemExit("HF_TOKEN is required for --upload")
        from huggingface_hub import HfApi

        HfApi(token=token).upload_folder(
            repo_id=args.repo_id,
            repo_type="dataset",
            folder_path=str(args.workdir),
        )
        print(f"uploaded {args.workdir} to hf://datasets/{args.repo_id}")
    else:
        print(f"prepared local HF dataset folder: {args.workdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

