# Lexis Mollis — base ouverte de droit souple

[![Code license: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](LICENSE)
[![Data license: CC-BY-4.0](https://img.shields.io/badge/data-CC--BY--4.0-green.svg)](LICENSE-DATA)
[![CI](https://github.com/MohammedKarimKhaldi/lexis_mollis/actions/workflows/ci.yml/badge.svg)](https://github.com/MohammedKarimKhaldi/lexis_mollis/actions/workflows/ci.yml)

Lexis Mollis transforme des PDF juridiques historiques et multilingues en un corpus ouvert,
auditable et interrogeable. La release actuelle contient 3 146 documents et 26 566 pages,
avec provenance OCR page par page, indicateurs de qualité, chunks de recherche, similarités
et graphe de connaissances.

Le dépôt regroupe :

- le pipeline OCR local `pdfkb` ;
- les contrats de données et l'ontologie RDF dans `metadata_design/` ;
- les pipelines de similarité et de knowledge graph ;
- les scripts de publication Hugging Face/Zenodo ;
- le site Astro/Cloudflare et ses services de recherche/SPARQL.

Voir [ARCHITECTURE.md](ARCHITECTURE.md) pour le flux technique, [PROJECT_STATUS.md](PROJECT_STATUS.md)
pour l'état vérifié et [ROADMAP.md](ROADMAP.md) pour les travaux restants. Les anciennes
spécifications détaillées sont conservées dans [`epics/`](epics/) comme références historiques.

## Qualité et fidélité

Les documents peuvent être scannés, dégradés, manuscrits ou multilingues. Le pipeline conserve
toutes les pages, y compris les pages faibles, avec `quality_score`, `review_required` et
`review_priority`.

Aucune correction générative, reformulation ou complétion par LLM n'est autorisée dans la couche
OCR brute. Les chunks, embeddings, relations et graphes restent reproductibles depuis
`metadata/pipeline.sqlite3`, les sources locales et le code versionné.

## Installation

Python 3.11 ou supérieur est requis.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[derive,semantica]'
```

Pour contribuer au code :

```bash
python -m pip install -e '.[derive,dev,semantica]'
```

## Commandes principales

OCR complet ou reprise d'un run :

```bash
python -m pdfkb run \
  --source traites \
  --metadata metadata/parsed_metadata.json \
  --output outputs_v2 \
  --state metadata/pipeline.sqlite3 \
  --workers 2 \
  --resume
```

Reconstruire les exports sans refaire l'OCR :

```bash
python -m pdfkb audit --state metadata/pipeline.sqlite3 --output outputs_v2
```

Construire la similarité et le graphe :

```bash
python -m pdfkb similarity build \
  --kb outputs_v2/kb/pages.jsonl \
  --output outputs_v2/similarity

python -m pdfkb graph build \
  --kb outputs_v2/kb/pages.jsonl \
  --similarity outputs_v2/similarity \
  --output outputs_v2/graph \
  --ontology metadata_design/ontology.ttl
```

Exporter le graphe complet vers le `ContextGraph` officiel de Semantica :

```bash
python -m pdfkb semantica export
```

Pour alimenter l'interface locale légère, convertir la projection web et lancer l'API
Semantica :

```bash
python -m pdfkb semantica export \
  --input platform/site/public/data/graph.sigma.json \
  --output outputs_v2/graph/graph.semantica.web.json

python -m pdfkb semantica serve \
  --graph outputs_v2/graph/graph.semantica.web.json \
  --no-browser
```

Construire puis lancer le site complet dans un second terminal :

```bash
npm run build
cd platform/site && npx wrangler dev --port 8787
```

Ouvrir <http://127.0.0.1:8787/graphe/>. L'interface Astro reste claire et compacte ; elle
interroge l'API Semantica locale sur le port 8000 pour la recherche, les voisinages et la
provenance. L'Explorer officiel sur le port 8000 reste un outil de diagnostic, pas une seconde
interface utilisateur. L'assistant accepte les questions naturelles en français et répond en
français par défaut.

## Validation

```bash
ruff check .
ruff format --check .
python -m unittest discover -v
python scripts/validate_schemas.py
python scripts/check_governance.py
npm run build
```

## Publications

- Dataset : <https://huggingface.co/datasets/lexis-mollis/soft-law-corpus>
- Site public : <https://lexis-mollis.karim-m-khaldi.workers.dev>
- Release GitHub : <https://github.com/MohammedKarimKhaldi/lexis_mollis/releases/tag/v0.1.0>
- Zenodo : DOI à reporter après validation du dépôt associé à la release

## Licences et citation

Le code est distribué sous Apache-2.0. Les données dérivées sont distribuées sous CC-BY-4.0,
avec attribution à Mohammed-Karim Khaldi et Reda Rostane. Voir [CITATION.cff](CITATION.cff).
