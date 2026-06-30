# Cahier d'exécution — Plateforme ouverte de droit souple

> **Pour l'agent qui exécute.** Ce document est un plan d'implémentation complet et
> ordonné. Réalise les *épics* dans l'ordre, tâche par tâche. Chaque tâche indique son
> **objectif**, ses **entrées**, ses **étapes**, ses **livrables** (chemins exacts) et ses
> **critères d'acceptation (CA)**. Ne marque une tâche terminée que si tous ses CA passent.
> Respecte en permanence les **garde-fous** du §0.3. Travaille par petites *pull requests*
> thématiques. Tout doit rester **gratuit et open source**.

> **Specs détaillées par épic** (sous-tâches, squelettes de code, critères d'acceptation,
> Definition of Done) — dossier `epics/` : `EPIC_A_infrastructure_gouvernance.md`,
> `EPIC_B_modele_donnees_standards.md`, `EPIC_C_similarite.md`, `EPIC_D_knowledge_graph.md`,
> `EPIC_E_export_publication.md`, `EPIC_F_plateforme_web.md`, `EPIC_G_cicd.md`,
> `EPIC_H_expansion_corpus.md`, `EPIC_I_revision_communaute.md`. Ce playbook reste l'index ;
> les fichiers `epics/` font foi pour l'exécution détaillée.

---

## 0. Contexte et règles

### 0.1 État actuel du dépôt (déjà en place)
- `pdfkb/` : pipeline OCR Python (v2.0.1), CLI argparse à sous-commandes
  (`run`, `audit`, `status`, `benchmark`) dans `pdfkb/cli.py`.
- `metadata/pipeline.sqlite3` : **source de vérité** (tables `documents`, `pages`,
  `page_errors`, `settings`). ~10 100 pages OCRisées, **1 309 documents complets** sur 3 146.
- `outputs_live/` : snapshot léger courant (`clean/*.md`, `kb/pages.jsonl`,
  `review_queue.csv`, `manifest.json`) pour 1 240 documents.
- `outputs_v2/` : cible des exports complets (à régénérer).
- `metadata_design/` : schémas JSON (`document.schema.json`, `page.schema.json`,
  `chunk.schema.json`, `review_event.schema.json`), `tag_taxonomy.json`,
  `scientific_methods_full.tex` (méthodo + schémas), `SIMILARITY_DESIGN.md`.
- `ROADMAP.md` : vision et stack. Ce cahier en est la déclinaison exécutable.
- L'**OCR tourne encore** : ne bloque rien dessus. Construis et valide sur les 1 309
  documents complets, puis relance les pipelines sur le corpus entier en fin d'OCR.

### 0.2 Objectif final
La plus grande base **ouverte** de droit souple : recherche plein texte + sémantique
(knowledge base), **knowledge graph**, **similarités** entre documents, **en ligne,
accessible, gratuite**, sous licence ouverte, avec attribution **Mohammed-Karim Khaldi,
Reda Rostane**.

### 0.3 Garde-fous (NON négociables)
1. **Fidélité** : aucun LLM ne corrige, reformule ou « complète » le texte OCR. Les couches
   dérivées (chunks, embeddings, entités, arêtes) n'écrivent jamais dans `raw/`.
2. **Auditabilité** : toute donnée dérivée est reproductible depuis `pipeline.sqlite3` +
   code versionné. Journalise modèles et paramètres.
3. **Qualité conservée** : ne jamais supprimer une page faible ; propager `quality_score`,
   `review_required`, `review_priority` jusqu'aux chunks et aux arêtes (champ `provisional`).
4. **Droits** : conserver `rights_status` (défaut `to_review`), l'URL source et la
   provenance. Ne jamais inférer un statut de droits.
5. **Déterminisme** : pipelines réexécutables, idempotents, à seeds fixés.
6. **Gratuité** : aucune dépendance payante ; pour toute offre gérée à palier gratuit,
   prévoir le repli auto-hébergé statique.

### 0.4 Conventions
- **Langue** : code et identifiants en anglais ; documentation utilisateur en français
  (puis i18n).
- **Python** : ≥ 3.11, style existant de `pdfkb` (type hints, `from __future__ import
  annotations`), `ruff` + `black`, tests `unittest` sous `tests/`.
- **Nouvelles sous-commandes CLI** : suivre le motif argparse de `pdfkb/cli.py`
  (un subparser par commande, dispatch dans `main`).
- **Formats de données dérivées** : **Parquet** (tabulaire), **JSONL** (enregistrements),
  **NPY/`.faiss`** (vecteurs/index), **Turtle + JSON-LD** (RDF). Pas de CSV pour les gros
  volumes.
- **Versionnage** : SemVer du pipeline ; tags `vMAJOR.MINOR.PATCH` déclenchent une release.
- **Commits** : Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`…).

### 0.5 Arborescence cible des dépôts (organisation GitHub publique `lexis-mollis`)
```
lexis-mollis/   # organisation GitHub + Hugging Face ; projet public « Lexis Mollis »
├── pipeline/            # ce dépôt (pdfkb + similarity + graph + scripts + CI)
├── platform/            # site web (Quartz/Astro) + Spaces de service
└── corpus-data/         # pointeurs/sous-modules vers données HF (pas les gros binaires)
```
Dans `pipeline/` :
```
pdfkb/
  ...(existant)...
  similarity/   # EPIC C
  graph/        # EPIC D
scripts/        # export HF, release Zenodo, utilitaires
.github/workflows/   # CI (EPIC G)
docs/           # méthodo, schémas, ce cahier
tests/
```

---

## 1. Préparation de l'environnement (faire en premier)

**T0.1 — Snapshot de travail.** Régénérer un export propre depuis l'état :
```bash
.venv/bin/python -m pdfkb audit --state metadata/pipeline.sqlite3 --output outputs_v2 --light
```
- Livrable : `outputs_v2/kb/pages.jsonl`, `outputs_v2/clean/*.md`, `manifest.json`.
- CA : `manifest.json.documents_exported >= 1240` ; `kb/pages.jsonl` non vide et valide JSONL.

**T0.2 — Dépendances dérivées** (nouveau groupe optionnel dans `pyproject.toml`,
`[project.optional-dependencies].derive`) :
`sentence-transformers`, `faiss-cpu`, `datasketch`, `networkx`, `python-louvain`,
`pyarrow`, `rdflib`, `numpy`, `tqdm`, `scikit-learn`, `regex`. Installer dans `.venv`.
- CA : `python -c "import faiss, sentence_transformers, datasketch, networkx, rdflib, pyarrow"` OK.

---

## EPIC A — Infrastructure & gouvernance

**A.1 Organisation et dépôts.** Créer l'organisation GitHub publique et les 3 dépôts
(§0.5). Pousser le code existant dans `pipeline/`.
- CA : dépôts publics, CI vide qui passe, `README` racine décrivant le projet.

**A.2 Licences et gouvernance.** Ajouter à `pipeline/` :
- `LICENSE` (Apache-2.0) pour le code ;
- `LICENSE-DATA` (CC-BY-4.0) pour les données, attribution « Mohammed-Karim Khaldi, Reda
  Rostane » ;
- `CITATION.cff` (auteurs, titre, année, DOI à compléter après Zenodo) ;
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` ;
- `.zenodo.json` (métadonnées de release : titre, créateurs, licence, mots-clés).
- CA : fichiers présents, valides ; `CITATION.cff` validé par le linter `cffconvert`.

**A.3 Comptes de publication.** Créer l'organisation **Hugging Face** (datasets + Spaces) et
lier **Zenodo** au dépôt GitHub (webhook release→DOI). Stocker les jetons en **secrets
GitHub Actions** (`HF_TOKEN`, `ZENODO_TOKEN`), jamais en clair.
- CA : un dataset HF vide privé créé ; secrets configurés ; aucun secret commité.

---

## EPIC B — Modèle de données & standards

**B.1 Étendre les schémas.** Compléter `metadata_design/` :
- `chunk.schema.json` existe déjà (id `^[a-f0-9]{64}:p\d{4}:c\d{3}$`, champs embedding) :
  l'utiliser tel quel comme contrat des chunks.
- Ajouter `edge.schema.json` (similarité + relations KG) et `node.schema.json`.
- Ajouter au `tag_taxonomy.json` les namespaces : `instrument_type`, `issuing_body`,
  `legal_force` (`binding`, `non_binding`, `mixed`, `unknown`), `source_db`.
- CA : tous les schémas valident en draft 2020-12 ; un script `scripts/validate_schemas.py`
  passe.

**B.2 Ontologie du knowledge graph.** Créer `metadata_design/ontology.ttl` :
- Préfixe projet `slo:` (soft-law-open). Classes : `Document`, `Instrument`, `Party`
  (État), `Organization`, `Person`, `Place`, `TopicConcept`, `Clause`.
- Prédicats : `partyTo`, `issuedBy`, `signedAt`, `dated`, `amends`, `supersedes`,
  `references`, `translationOf`, `sameInstrumentAs`, `similarTo` (avec poids), `aboutTopic`.
- Alignements : `owl:sameAs` → Wikidata ; réutiliser `schema:Legislation`, modèle **FRBR**
  (œuvre/expression/manifestation) pour séparer instrument / version linguistique / scan.
- CA : `ontology.ttl` se charge sans erreur via `rdflib.Graph().parse`.

**B.3 Data dictionary.** Mettre à jour `metadata_design/data_dictionary.md` avec tous les
nouveaux champs (chunk, edge, node) et leur provenance.
- CA : chaque champ produit par un pipeline figure au dictionnaire.

---

## EPIC C — Module de similarité (`pdfkb/similarity/`)

Référence conceptuelle : `metadata_design/SIMILARITY_DESIGN.md`. Implémenter une chaîne
**lexicale (MinHash/LSH)** + **sémantique (embeddings/FAISS)**, fusion pondérée qualité.

### Structure
```
pdfkb/similarity/
  __init__.py
  chunking.py     # pages -> chunks
  embeddings.py   # chunks -> vecteurs (cache)
  lexical.py      # MinHash + LSH -> paires candidates
  index.py        # FAISS build/query
  pairs.py        # fusion lexical+sémantique, seuils, pondération qualité
  graph.py        # arêtes de similarité + clusters
  run.py          # orchestration build
```

**C.1 Chunking** (`chunking.py`).
- Fonction : `chunk_pages(pages: Iterable[dict], target_tokens=384, overlap=64) -> Iterator[dict]`.
- Tokeniser avec le tokenizer du modèle d'embedding ; ne pas franchir les frontières de
  page ; conserver `char_start/char_end`.
- `chunk_id = f"{source_sha256}:p{page_number:04d}:c{chunk_index:03d}"` (conforme au schéma).
- Propager `quality_score`, `review_required`, `review_priority`, `language`, `script`,
  `document_id`, `title`, `treaty_id`, `doc_type`, `year`.
- Livrable : `outputs_v2/similarity/chunks.parquet`.
- CA : chaque ligne valide `chunk.schema.json` ; nombre de chunks ≥ nombre de pages
  non vides ; idempotent (mêmes entrées → mêmes `chunk_id`/`text_sha256`).

**C.2 Embeddings** (`embeddings.py`).
- Modèle par défaut : `sentence-transformers/LaBSE` (multilingue, fort pour aligner
  traductions) ; configurable (`--model`), repli `paraphrase-multilingual-mpnet-base-v2`.
- Normalisation L2. Batch, `show_progress`. **Cache** par `text_sha256` →
  ne ré-encoder que les nouveaux chunks.
- Livrables : `outputs_v2/similarity/embeddings.npy` (+ `embeddings_index.parquet` mappant
  ligne→`chunk_id`) ; renseigner `embedding_model`, `embedding_created_at` dans les chunks.
- CA : `len(embeddings) == len(chunks)` ; vecteurs L2-normalisés (‖v‖≈1) ; relance =
  0 ré-encodage si rien n'a changé.

**C.3 Similarité lexicale** (`lexical.py`).
- N-grammes de caractères (n=5) sur texte replié NFKC + casefold + alphanumérique.
- `datasketch` MinHash (num_perm=128) + `MinHashLSH` (seuil Jaccard ~0.5).
- Sortie : paires candidates `(chunk_a, chunk_b, jaccard_est)`.
- Livrable : `outputs_v2/similarity/lexical_pairs.parquet`.
- CA : doublons exacts connus détectés (Jaccard≈1) ; coût sous-quadratique (LSH, pas de
  produit cartésien).

**C.4 Index sémantique** (`index.py`).
- FAISS `IndexFlatIP` (MVP) sur vecteurs normalisés ; option `IndexIVFPQ` si > 500 k
  vecteurs. Persister `outputs_v2/similarity/faiss.index` + `id_map.parquet`.
- Requête kNN : `query(vectors, k=20) -> (ids, scores)`.
- CA : top-1 d'un chunk sur lui-même = lui-même (score≈1) ; sérialisation/relecture OK.

**C.5 Fusion et seuils** (`pairs.py`).
- Pour chaque paire candidate (lexicale ∪ kNN sémantique) :
  `combined = w_l*jaccard + w_s*cosine` (défaut `w_l=0.5, w_s=0.5`, configurables).
- `quality_weight = min(q_a, q_b)` ; `provisional = review_required_a or review_required_b`.
- Typage par seuils (calibrables, valeurs de départ) :
  - `duplicate` : jaccard ≥ 0.90 ;
  - `clause_reuse` : 0.60 ≤ jaccard < 0.90 ;
  - `semantic_kin` / `translation` : cosine ≥ 0.80 ;
  - `weak_link` : 0.70 ≤ cosine < 0.80.
- Livrable : `outputs_v2/similarity/edges.parquet` conforme à `edge.schema.json`
  (`src, dst, level∈{chunk,document}, type, lexical, semantic, combined, quality_weight,
  provisional`).
- CA : aucune arête entre un chunk et lui-même ; symétrie maîtrisée (une seule arête par
  paire non ordonnée) ; champs de qualité présents.

**C.6 Graphe & familles** (`graph.py`).
- Agréger chunk→document (max/moyenne pondérée des meilleures paires) → arêtes document.
- `networkx` + `python-louvain` (ou Leiden) pour les communautés → familles.
- Livrables : `outputs_v2/similarity/doc_edges.parquet`, `clusters.json`
  (`cluster_id`, membres, méthode, params).
- CA : clustering déterministe (seed fixé) ; rapport résumé (nb arêtes par type, nb
  clusters, taille médiane) écrit en `outputs_v2/similarity/summary.json`.

**C.7 CLI.** Ajouter un subparser `similarity` (sous-actions `build`) dans `pdfkb/cli.py`,
même motif que les autres :
```bash
.venv/bin/python -m pdfkb similarity build \
  --kb outputs_v2/kb/pages.jsonl \
  --output outputs_v2/similarity \
  --model sentence-transformers/LaBSE \
  --target-tokens 384 --overlap 64
```
- CA : commande exécutable de bout en bout sur les 1 309 docs ; produit tous les livrables
  C.1–C.6 ; journal JSON final (compteurs).

**C.8 Tests & calibration.**
- `tests/test_similarity.py` : chunking déterministe, normalisation lexicale, FAISS round-trip,
  typage des seuils.
- Construire un mini jeu de validation annoté (`benchmarks/similarity_cases.json`) :
  paires positives connues (versions multilingues d'un même traité, clauses réutilisées) et
  négatives → calculer précision/rappel par type, ajuster les seuils.
- CA : tests verts ; rapport precision/rappel écrit ; seuils documentés dans
  `SIMILARITY_DESIGN.md`.

---

## EPIC D — Knowledge graph (`pdfkb/graph/`)

**D.1 Extraction d'entités** (`entities.py`).
- À partir des `clean/*.md` et métadonnées : repérer **États/parties**, **organisations**,
  **dates**, **lieux**, **personnes (signataires)**, **thèmes**.
- Approche conservatrice : règles + gazetteers (listes d'États, d'organisations
  internationales, alignées Wikidata) ; option `spaCy` multilingue pour NER ; ne jamais
  inventer — marquer la confiance et la source du span.
- Tenir compte du bruit OCR : seuil de confiance, ne pas extraire sur pages `high` sauf
  marqué `provisional`.
- Livrable : `outputs_v2/graph/mentions.parquet` (entité, type, `document_id`,
  `page_number`, span, confiance, `provisional`).
- CA : précision vérifiée sur un échantillon annoté (≥ 50 mentions) ; chaque mention tracée
  à une page.

**D.2 Liage & nœuds** (`linking.py`).
- Résoudre les mentions vers des entités canoniques ; aligner États/orgs/personnes sur
  **Wikidata** (`owl:sameAs`) via un cache local de QIDs (pas d'appel réseau en CI sans
  cache).
- Livrable : `outputs_v2/graph/nodes.parquet` conforme `node.schema.json`
  (`node_id, type, label, wikidata_qid?, aliases[]`).
- CA : pas de doublon d'entité canonique ; QIDs validés au format `^Q\d+$`.

**D.3 Construction du graphe** (`build.py`).
- Arêtes typées (ontologie B.2) à partir des mentions + métadonnées + arêtes `similarTo`
  importées de l'EPIC C.
- Sorties multi-format :
  - `outputs_v2/graph/graph.ttl` et `graph.jsonld` (RDF, pour SPARQL/interop) ;
  - `outputs_v2/graph/nodes.parquet`, `edges.parquet` (property graph) ;
  - `outputs_v2/graph/graph.sigma.json` (format léger pour la viz web : nodes/edges +
    positions précalculées via layout ForceAtlas2/`networkx`).
- CA : RDF rechargeable par `rdflib` ; cohérence id nœuds entre formats ; `graph.sigma.json`
  < 25 Mo (sinon échantillonner/agréger pour la viz, garder le dump complet à part).

**D.4 CLI.** Subparser `graph build` :
```bash
.venv/bin/python -m pdfkb graph build \
  --kb outputs_v2/kb/pages.jsonl \
  --similarity outputs_v2/similarity \
  --output outputs_v2/graph \
  --ontology metadata_design/ontology.ttl
```
- CA : exécution complète sur le sous-corpus ; tous les livrables D.1–D.3 produits.

**D.5 Tests.** `tests/test_graph.py` : extraction déterministe, format RDF valide,
intégrité référentielle nœuds/arêtes.
- CA : tests verts ; `summary.json` (compteurs par type de nœud/arête).

---

## EPIC E — Export & publication des données

**E.1 Dataset Hugging Face** (`scripts/export_hf_dataset.py`).
- Convertir en Parquet shardé (< 50 Go/fichier, < 10 000 fichiers/dossier) :
  `documents`, `pages`, `chunks`, `edges`, `nodes`. Inclure un `README.md` (dataset card)
  avec licence **CC-BY-4.0**, attribution, description des colonnes, et avertissement
  qualité/OCR.
- Pousser via `huggingface_hub` (token en secret). Versionner par tag.
- CA : dataset public visible, *dataset viewer* fonctionnel, colonnes documentées.

**E.2 PDF sources volumineux.** Publier les PDF (selon droits) sur **Internet Archive**
(item dédié) ou en pièce HF distincte ; conserver le lien dans `documents`.
- CA : chaque document a une URL source résolvable ou un statut de droits expliquant
  l'absence.

**E.3 Release Zenodo** (`.zenodo.json` + workflow). Sur tag `v*`, créer une release GitHub
→ archive → **DOI Zenodo**. Reporter le DOI dans `CITATION.cff` et le `README`.
- CA : un DOI obtenu pour une release de test ; citation à jour.

---

## EPIC F — Plateforme web (dépôt `platform/`)

**F.1 Site statique.** **Astro** (décision arrêtée). La vue graphe est construite avec
**Sigma.js** (F.3), la recherche plein texte côté client (MiniSearch) complétée par le
service sémantique (F.2). Générer une **fiche par document** depuis `clean/*.md` +
métadonnées : texte, métadonnées, tags, sources, **documents similaires** (EPIC C),
**voisinage graphe** (EPIC D), lien PDF, statut de révision.
- Hébergement : **Cloudflare Pages** (bande passante illimitée) ou GitHub Pages.
- CA : site déployé à une URL publique ; navigation document↔similaires↔graphe ; build
  reproductible en CI.

**F.2 Service de recherche sémantique** (`platform/spaces/search/`, HF Space).
- FastAPI (ou Gradio) servant **FAISS + BM25 hybride**. Endpoints : `/search?q=&k=&filters=`
  (filtres par `doc_type`, `year`, `language`, `legal_force`), `/similar?chunk_id=`.
- Charger `faiss.index` + métadonnées depuis le dataset HF. Index compact (IVFPQ) pour
  tenir dans le CPU gratuit (2 vCPU/16 Go). Prévoir le réveil (le Space s'endort après
  48 h) via ping CI programmé.
- Repli **sans serveur** : index réduit + recherche client (`transformers.js` ou
  MiniSearch) pour la démo si le Space dort.
- CA : requête FR/EN/multilingue renvoie des résultats pertinents ; filtres fonctionnels ;
  latence raisonnable sur le sous-corpus.

**F.3 Exploration du graphe.** Page Sigma.js/Cytoscape chargeant `graph.sigma.json` :
recherche de nœud, filtres par type d'arête, focus voisinage, panneau détail.
- Option : endpoint **SPARQL Oxigraph** dans un Space pour requêtes avancées + bouton
  « télécharger le RDF ».
- CA : graphe interactif fluide (≥ quelques milliers de nœuds) ; liens vers fiches.

**F.4 Accessibilité & ouverture.** Multilingue (FR/EN d'abord), responsive, page
« Données & licence » avec liens HF/Zenodo/IA, export JSONL/Parquet/RDF, mentions
d'auteurs et `rights_status` visibles.
- CA : audit accessibilité de base (contraste, navigation clavier) ; tous les exports
  téléchargeables.

---

## EPIC G — Automatisation CI/CD (`.github/workflows/`)

**G.1 `ci.yml`** (push/PR) : lint (`ruff`, `black --check`), `python -m unittest discover`,
validation des schémas, validation `CITATION.cff`.
- CA : obligatoire pour merger ; vert sur `main`.

**G.2 `build-derive.yml`** (sur changement des données nettoyées ou manuel) : exécute
`similarity build` puis `graph build` (incrémental via caches d'embeddings), publie les
artefacts.
- CA : artefacts reproductibles ; cache d'embeddings réutilisé entre runs.

**G.3 `deploy-site.yml`** : build du site + déploiement Cloudflare/GitHub Pages.
- CA : déploiement auto sur `main`.

**G.4 `release.yml`** (tags `v*`) : push dataset HF + release GitHub + DOI Zenodo.
- CA : une release de test complète passe.

> Garder **tous les dépôts publics** (Actions gratuit/illimité pour le public). Secrets via
> `Settings → Secrets`. Seeds fixés pour la reproductibilité.

---

## EPIC H — Expansion du corpus (connecteurs de sources)

Objectif « plus grande base au monde » : ingérer progressivement d'autres sources de droit
souple, **mêmes schémas, même pipeline**.

**H.1 Cadre d'ingestion** (`pdfkb/ingest/`). Interface `Source` :
`discover() -> records`, `fetch(record) -> file`, `to_metadata(record) -> document_meta`.
Respect `robots.txt` / conditions ; renseigner `source_db`, `source_url`, `rights_status`,
`instrument_type`, `legal_force`.
- CA : un connecteur de référence implémenté de bout en bout (voir H.2) ; dédup via
  SHA-256 + MinHash ; documents ingérés passent dans `pdfkb run`.

**H.2 Premiers connecteurs** (ordre de priorité arrêté) :
(1) **Soft law UE / EUR-Lex** (API ouverte, métadonnées riches) → (2) **OCDE / OIT / OMS /
OMC** (recommandations, codes, lignes directrices) → (3) **ECOLEX** (environnement) →
(4) **résolutions & déclarations AGNU**. Sources ultérieures : Refworld/HCR, organes de
traités des droits de l'homme.
- CA : pour chaque source activée, métadonnées normalisées + provenance + droits ;
  rapport d'ingestion.

**H.3 Déduplication inter-sources.** Étendre l'inventaire pour fusionner les doublons exacts
(SHA-256) et signaler les quasi-doublons (MinHash) entre sources.
- CA : pas de double comptage ; alias documentaires préservés.

---

## EPIC I — Révision & communauté

**I.1 Outil de révision.** Exploiter `review_queue.csv` : page statique (ou issues GitHub
générées) listant les pages `high` avec image (`audit/review_images/`) et champs à
confirmer/corriger. Les corrections n'altèrent jamais `raw/` ; elles créent des
`review_event` (cf. `review_event.schema.json`) et, si validées, une couche `corrected/`
distincte et tracée.
- CA : un réviseur peut confirmer/corriger une page ; l'événement est enregistré et
  réexportable.

**I.2 Contribution ouverte.** `CONTRIBUTING.md` : ajouter une source (EPIC H), corriger une
transcription (I.1), signaler une relation. Modèles d'issues/PR.
- CA : un contributeur externe peut suivre le guide sans contexte privé.

---

## 2. Séquencement & parallélisation

```
Phase 0 (S1)  : T0.* + EPIC A + EPIC B            [fondations]
Phase 1 (S2-4): EPIC C (sur 1 309 docs) ∥ EPIC F.1/F.2 (données d'exemple)
                + EPIC E.1 + EPIC G.1            [MVP vertical en ligne]
Phase 2 (S4-8): EPIC D ∥ EPIC F.3 ∥ EPIC G.2-4 ∥ EPIC H.1 + calibration C.8
Phase 3 (post-OCR): relance C+D sur corpus complet, EPIC E.3 (DOI), lancement
Phase 4 (continu) : EPIC H.2-3 (expansion) + EPIC I (communauté)
```
Dépendances dures : A→(tout publié) ; B→C,D ; C→D(arêtes similarité)→F.3 ; E→F (charge les
données) ; G dépend de A. Tout le reste est parallélisable.

**Définition du MVP (fin Phase 1) :** dataset HF public des 1 309 docs + recherche
sémantique en ligne (Space) + site statique avec fiches et similarités + CI verte.

---

## 3. Critères d'acceptation globaux
- [ ] Données publiées (HF + DOI Zenodo) sous CC-BY-4.0, attribution Khaldi & Rostane.
- [ ] Site public : recherche plein texte + sémantique, fiches, similarités, graphe interactif.
- [ ] Knowledge graph téléchargeable (RDF) + SPARQL optionnel.
- [ ] Pipelines reproductibles depuis `pipeline.sqlite3` + code, seeds fixés, CI verte.
- [ ] Garde-fous §0.3 respectés partout (fidélité, qualité propagée, droits, provenance).
- [ ] 100 % gratuit ; replis statiques documentés pour chaque palier gratuit.

## 4. Risques & parades
- **Space CPU s'endort / RAM limitée** → index IVFPQ compact + ping CI ; repli recherche client.
- **Paliers vectoriels gérés trop petits** (Qdrant 1 Go, Supabase 500 Mo) → FAISS embarqué
  comme voie principale, géré seulement pour recherche filtrée légère.
- **Bruit OCR → fausses similarités/entités** → pondération qualité + `provisional` + seuils
  calibrés sur jeu annoté.
- **Droits incertains** → `rights_status=to_review` par défaut ; PDF lourds sur IA ; ne rien
  inférer.
- **Volume (objectif “plus grande au monde”)** → tout incrémental, shardé, caché ; ingestion
  par connecteurs standardisés.

## 5. Décisions arrêtées (verrouillées avec les auteurs)
1. **Licence des données : CC-BY-4.0** — attribution obligatoire « Mohammed-Karim Khaldi,
   Reda Rostane ». (Code : Apache-2.0.)
2. **Site public : Astro** — UI sur-mesure ; la vue graphe est à construire avec **Sigma.js**
   (pas de vue graphe « native » à la Quartz).
3. **Modèle d'embeddings par défaut : LaBSE** (`sentence-transformers/LaBSE`) — alignement
   inter-langues. Repli configurable : `paraphrase-multilingual-mpnet-base-v2`.
4. **Expansion du corpus — ordre de priorité des connecteurs (EPIC H) :**
   (1) **Soft law UE / EUR-Lex** → (2) **OCDE / OIT / OMS / OMC** → (3) **ECOLEX** →
   (4) **Résolutions & déclarations AGNU**.
5. **Nom public & handles : « Lexis Mollis » / `lexis-mollis`** — organisation GitHub
   `github.com/lexis-mollis`, organisation Hugging Face `hf.co/lexis-mollis`, nom du site
   « Lexis Mollis ».
```
```
```

### Annexe — squelette CLI à ajouter dans `pdfkb/cli.py`
```python
# dans build_parser(), après le subparser benchmark :
sim = subparsers.add_parser("similarity", help="Construire chunks, embeddings, similarités")
sim_sub = sim.add_subparsers(dest="sim_command", required=True)
simb = sim_sub.add_parser("build")
simb.add_argument("--kb", type=Path, required=True)
simb.add_argument("--output", type=Path, required=True)
simb.add_argument("--model", default="sentence-transformers/LaBSE")
simb.add_argument("--target-tokens", type=int, default=384)
simb.add_argument("--overlap", type=int, default=64)

g = subparsers.add_parser("graph", help="Construire le knowledge graph")
g_sub = g.add_subparsers(dest="graph_command", required=True)
gb = g_sub.add_parser("build")
gb.add_argument("--kb", type=Path, required=True)
gb.add_argument("--similarity", type=Path, required=True)
gb.add_argument("--output", type=Path, required=True)
gb.add_argument("--ontology", type=Path, default=Path("metadata_design/ontology.ttl"))

# dans main(), brancher args.command == "similarity" / "graph" vers les orchestrateurs
# pdfkb.similarity.run.build(...) et pdfkb.graph.build.build(...)
```
