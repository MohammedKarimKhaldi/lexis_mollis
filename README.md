# Lexis Mollis — base ouverte de droit souple

[![Code license: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](LICENSE)
[![Data license: CC-BY-4.0](https://img.shields.io/badge/data-CC--BY--4.0-green.svg)](LICENSE-DATA)
[![CI](https://github.com/MohammedKarimKhaldi/lexis_mollis/actions/workflows/ci.yml/badge.svg)](https://github.com/MohammedKarimKhaldi/lexis_mollis/actions/workflows/ci.yml)
[![DOI](https://img.shields.io/badge/DOI-Zenodo%20à%20venir-lightgrey.svg)](.zenodo.json)

Lexis Mollis vise à construire une base ouverte, auditable et interrogeable de
droit souple : traités, déclarations, résolutions, recommandations, lignes
directrices, codes de conduite et instruments connexes. Ce dépôt contient le
pipeline OCR local `pdfkb`, les contrats de données, puis les modules dérivés de
recherche sémantique, similarité et knowledge graph.

## Avertissement qualité/OCR

Le corpus contient des documents historiques, multilingues, parfois scannés,
dégradés ou manuscrits. Le pipeline conserve toutes les pages, y compris les pages
faibles, avec des champs de qualité (`quality_score`, `review_required`,
`review_priority`). Les transcriptions ne doivent pas être traitées comme une
vérité absolue sans vérification sur les pages signalées.

Aucune correction générative, reformulation ou complétion par LLM n'est autorisée
sur la couche OCR brute. Les couches dérivées (chunks, embeddings, relations,
graphes) doivent rester reproductibles depuis `metadata/pipeline.sqlite3` et le
code versionné.

## Architecture

La feuille de route complète est dans [ROADMAP.md](ROADMAP.md). Le cahier
d'exécution est dans [BUILD_PLAYBOOK.md](BUILD_PLAYBOOK.md), avec les specs
détaillées dans [`epics/`](epics/).

Flux cible :

1. OCR fidèle et auditable avec `pdfkb`.
2. Export page par page en Markdown/JSONL.
3. Chunking, embeddings multilingues et index FAISS.
4. Graphe de similarités et knowledge graph RDF/property graph.
5. Publication ouverte sur Hugging Face Datasets, Zenodo et site public.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[derive]'
```

## Usage CLI

OCR complet :

```bash
python -m pdfkb run --source traites --metadata metadata/parsed_metadata.json --output outputs_v2 --workers 2 --resume
```

État du run :

```bash
python -m pdfkb status --state metadata/pipeline.sqlite3
```

Export léger exploitable pendant l'OCR :

```bash
python -m pdfkb audit --state metadata/pipeline.sqlite3 --output outputs_v2 --light
```

Pilote similarité lexical léger pendant l'OCR :

```bash
python -m pdfkb similarity build \
  --kb outputs_v2/kb/pages.jsonl \
  --output outputs_v2/similarity_pilot \
  --lexical-only \
  --limit-pages 500
```

Build complet similarité lexicale + embeddings + FAISS, à lancer quand la machine
peut encaisser l'encodage local :

```bash
python -m pdfkb similarity build \
  --kb outputs_v2/kb/pages.jsonl \
  --output outputs_v2/similarity
```

Knowledge graph conservateur (gazetteers + règles + import des similarités) :

```bash
python -m pdfkb graph build \
  --kb outputs_v2/kb/pages.jsonl \
  --similarity outputs_v2/similarity \
  --output outputs_v2/graph \
  --ontology metadata_design/ontology.ttl
```

Calibration des seuils, après annotation humaine de paires réelles dans
`benchmarks/similarity_cases.json` :

```bash
python scripts/calibrate_similarity.py \
  --similarity-dir outputs_v2/similarity \
  --output outputs_v2/similarity/calibration_report.json
```

## Données, licence et attribution

Le code est distribué sous licence Apache-2.0. Les données produites par Lexis
Mollis sont distribuées sous CC-BY-4.0 avec attribution :

> Mohammed-Karim Khaldi, Reda Rostane — Lexis Mollis

Les textes officiels sous-jacents peuvent relever de statuts distincts ; le champ
`rights_status` est conservé pour éviter toute inférence abusive.

Les publications publiques prévues sont :

- Hugging Face Datasets : `lexis-mollis/soft-law-corpus`
- Zenodo : DOI à créer lors de la première release
- Internet Archive ou équivalent : conservation des PDF sources lorsque les droits
  le permettent

## Citation

Voir [CITATION.cff](CITATION.cff).

## Contribution

Voir [CONTRIBUTING.md](CONTRIBUTING.md). Les contributions les plus utiles sont :
proposer une source ouverte, signaler une erreur de transcription, ou signaler une
relation/similarité manquante.

## Auteurs

Mohammed-Karim Khaldi, Reda Rostane.
