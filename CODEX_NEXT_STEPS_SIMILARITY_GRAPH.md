# Plan d'exécution — similarité, graphe, nœuds (à partir du corpus complet)

> Document de passation pour Codex, écrit par Claude le 2026-06-30 après vérification de
> l'état réel du dépôt (logs OCR, fichiers de sortie, code). Complète les specs déjà
> existantes (`epics/EPIC_C_similarite.md`, `epics/EPIC_D_knowledge_graph.md`) avec un
> ordre d'exécution concret, les commandes exactes, et ce qui bloque réellement aujourd'hui.
> Ce n'est pas une nouvelle spec : le code de `pdfkb/similarity/` et `pdfkb/graph/` est déjà
> écrit et fonctionne (testé sur pilote). Ce qui manque, c'est de le faire tourner sur le
> corpus complet et de calibrer les seuils avec de vraies annotations humaines.

## 0. Constat de départ (vérifié, pas supposé)

- **OCR terminé** : 3 146/3 146 documents, 26 566 pages, 0 erreur (`metadata/pdfkb_full.log`,
  sortie `status=0`).
- **Audit complet déjà régénéré** sur les 3 146 documents : `outputs_v2/kb/pages.jsonl` et
  `outputs_v2/audit/pages.jsonl` ont chacun 26 566 lignes ; `outputs_v2/clean/` et
  `outputs_v2/raw/` ont chacun 3 146 fichiers.
- **`outputs_v2/similarity_pilot/` et `outputs_v2/graph_pilot/` sont des fumée-tests
  minuscules**, pas un pilote représentatif : `similarity_pilot/summary.json` ne contient
  qu'1 arête document et 2 clusters ; `graph_pilot/summary.json` ne contient que 22 nœuds /
  23 arêtes. Ces deux dossiers datent de 13h18–13h27, avant la fin de l'audit complet
  (21h23) — ils ont tourné sur un tout petit sous-ensemble initial, pas sur les 1 309 (ni a
  fortiori les 3 146) documents annoncés dans les specs EPIC C/D.
- **`outputs_v2/release_pilot/` (100 documents, généré à 21h38) est plus représentatif** et
  sert de source aux données actuellement publiées sur le site (`platform/site/public/data/`).
  C'est un bon point de départ pour vérifier le pipeline de bout en bout avant de lancer le
  build complet.
- **Le code est complet** : `pdfkb/similarity/{chunking,embeddings,lexical,index,pairs,
  graph,run}.py` et `pdfkb/graph/{gazetteers,entities,dates,linking,build,run}.py` existent
  avec toutes les étapes décrites dans les specs (chunking, MinHash/LSH, FAISS, fusion,
  clustering, extraction d'entités, liage, export RDF/Parquet/Sigma).
- **Bloquant réel n°1 — calibration** : `benchmarks/similarity_cases.json` existe mais
  contient **0 cas** (`"cases": []`). Le script `scripts/calibrate_similarity.py` est prêt
  mais n'a rien à calibrer tant que ce fichier n'est pas rempli par un humain
  (minimum 30 paires positives + 30 négatives, cf. §2).
- **Bloquant réel n°2 — gazetteers minces** : `data/gazetteers/states.csv` (12 entrées),
  `organizations.csv` (9), `places.csv` (10). Très en dessous de ce que vise la spec D.1
  (« États souverains historiques et actuels », organisations internationales courantes…).
  Le graphe tournera quand même, mais beaucoup d'entités resteront non liées ou
  `provisional` tant que ces listes ne sont pas étoffées.
- **Garde-fous à respecter (rappel)** : aucune écriture dans `raw/`, déterminisme via
  `--seed` (déjà fixé par défaut à `20260701`), aucun appel réseau Wikidata en CI (cache
  local uniquement), ne jamais committer `outputs_v2/`, `*.parquet`, `*.npy`, `*.faiss`,
  `*.index`, le SQLite ou les PDF (déjà couvert par `.gitignore` — ne pas le modifier pour
  ces chemins).

## 1. Build complet de similarité sur le corpus entier

Lancer directement sur les 3 146 documents (l'audit est déjà fait, donc `outputs_v2/kb/
pages.jsonl` est déjà à jour) :

```bash
.venv/bin/python -m pdfkb similarity build \
  --kb outputs_v2/kb/pages.jsonl \
  --output outputs_v2/similarity \
  --model sentence-transformers/LaBSE \
  --target-tokens 384 --overlap 64 \
  --seed 20260701
```

Points d'attention :
- C'est le premier run sur la taille réelle (26 566 pages, pas 1 462) : surveiller la
  mémoire/temps de l'embedding LaBSE et du FAISS `IndexFlatIP` (bascule auto vers IVFPQ au
  seuil `faiss_ivf_threshold=500000` chunks — probablement pas atteint, mais à vérifier dans
  `outputs_v2/similarity/run_config.json` une fois le run terminé).
- Si la machine ne tient pas la charge en un seul run, le flag `--limit-pages` permet de
  faire un run intermédiaire de validation avant le run complet, mais le run **complet**
  (sans `--limit-pages`) est l'objectif final à committer dans `outputs_v2/similarity/`
  (non versionné dans git — uniquement utilisé localement, puis exporté via EPIC E).
- Vérifier en sortie : `outputs_v2/similarity/summary.json` (compteurs par type d'arête,
  nombre de clusters), `outputs_v2/similarity/run_config.json` (paramètres effectifs).
- Lancer `pytest tests/test_similarity.py -q` avant et après pour confirmer l'absence de
  régression sur les fonctions déterministes (chunking, MinHash, FAISS round-trip).

## 2. Annotation humaine pour la calibration (bloquant, fait par un humain — Mohammed-Karim et/ou Reda)

`benchmarks/similarity_cases.json` doit passer de 0 à **≥ 30 cas positifs et ≥ 30 cas
négatifs** avant de pouvoir affirmer que les seuils sont calibrés (cf. note de vigilance
existante dans `PROJECT_STATUS.md` : « ne pas affirmer que les seuils de similarité sont
calibrés avant annotation humaine »).

Suggestion de méthode pour Codex, afin de **proposer des candidats** à l'humain plutôt que
de lui faire chercher des paires à l'aveugle :

1. Après le run de l'étape 1, extraire depuis `outputs_v2/similarity/doc_edges.parquet`
   un échantillon stratifié de paires à différents niveaux de score combiné :
   - quelques paires à score très haut (probables doublons/traductions) → candidats positifs
     faciles à confirmer ;
   - quelques paires à score moyen (zone grise actuelle des seuils `t_clause_reuse`/
     `t_weak_link`) → les plus utiles à trancher humainement ;
   - quelques paires à score bas mais thématiquement proches (même `doc_type`/`century`)
     → bons candidats négatifs (proches en apparence, non liés en réalité).
2. Écrire un petit script (`scripts/sample_calibration_candidates.py` ou équivalent) qui
   génère un CSV/JSON lisible par un humain : `case_id, src, dst, doc_titles, score_combiné,
   extrait_src, extrait_dst` — pour que l'annotateur n'ait pas à rouvrir chaque document.
3. L'humain remplit `label` (`positive`/`negative`) et `expected_type` (`duplicate`,
   `clause_reuse`, `translation`, `semantic_kin`, `weak_link`, `similar_to`,
   `same_instrument_as`, ou `null`) directement dans `benchmarks/similarity_cases.json`,
   au format déjà documenté dans le fichier (`case_format`).
4. Une fois ≥ 30/30 atteint :
   ```bash
   .venv/bin/python scripts/calibrate_similarity.py \
     --similarity outputs_v2/similarity \
     --cases benchmarks/similarity_cases.json \
     --output outputs_v2/similarity/calibration_report.json
   ```
   (vérifier les noms d'arguments exacts dans `scripts/calibrate_similarity.py` — le script
   balaie déjà `t_duplicate/t_clause_reuse/t_translation/t_weak_link` et `w_lexical/
   w_semantic` et calcule précision/rappel/F1 par type.)
5. Reporter les seuils retenus dans `pdfkb/similarity/config.py` (`SimilarityConfig`) **et**
   dans `metadata_design/SIMILARITY_DESIGN.md`, avec un lien vers
   `calibration_report.json` comme preuve.

## 3. Re-run du build de similarité avec les seuils calibrés

Une fois `config.py` mis à jour (ou via les flags CLI `--t-duplicate/--t-clause-reuse/
--t-translation/--t-weak-link/--w-lexical/--w-semantic`), relancer la commande de l'étape 1
pour régénérer `outputs_v2/similarity/edges.parquet`, `doc_edges.parquet`, `clusters.json`
avec les seuils définitifs. C'est cette version qui doit être utilisée par l'étape 5.

## 4. Étoffer les gazetteers avant le build de graphe complet

Avant de lancer le graphe sur le corpus entier, enrichir :
- `data/gazetteers/states.csv` : ajouter les États historiques pertinents pour un corpus de
  traités du XVIIe–XXIe siècle (empires, royaumes disparus, noms d'époque en plus des noms
  actuels), avec QID Wikidata quand disponible.
- `data/gazetteers/organizations.csv` : organisations internationales courantes (SDN, ONU et
  ses agences, OCDE, OMC, UE, Conseil de l'Europe, Croix-Rouge, etc.).
- `data/gazetteers/places.csv` : lieux de signature fréquents dans le corpus (à dériver par
  exemple d'un comptage des lieux déjà mentionnés dans `outputs_v2/kb/pages.jsonl` ou dans
  les métadonnées `parsed_metadata.json`/`parsed_metadata.csv`).

Une bonne approche pour Codex : écrire un petit script qui scanne
`outputs_v2/audit/pages.jsonl` (ou `kb/pages.jsonl`) à la recherche de capitalized n-grams
fréquents non déjà couverts par les gazetteers actuels, pour produire une liste de
candidats à valider/compléter avec leurs QID plutôt que de saisir à la main depuis zéro.
Garder le format `label, aliases (séparés par |), qid, iso3/—, lang` déjà utilisé.

## 5. Build complet du knowledge graph

```bash
.venv/bin/python -m pdfkb graph build \
  --kb outputs_v2/kb/pages.jsonl \
  --similarity outputs_v2/similarity \
  --output outputs_v2/graph \
  --ontology metadata_design/ontology.ttl \
  --gazetteers data/gazetteers \
  --min-confidence 0.70 \
  --seed 20260701
```

Sorties attendues : `nodes.parquet`, `edges.parquet`, `mention_links.parquet`, `graph.ttl`,
`graph.jsonld`, `graph.sigma.json`, `summary.json`.

Points d'attention spécifiques au passage à l'échelle (3 146 documents au lieu de 6 dans
`graph_pilot`) :
- Si `graph.sigma.json` dépasse ~25 Mo (limite indiquée en spec D.5), Codex doit activer la
  vue agrégée au niveau Document/Instrument plutôt que de publier le détail complet — sinon
  le site Astro (qui charge ce fichier côté client avec Sigma.js) deviendra trop lourd.
- Lancer `pytest tests/test_graph.py -q` avant/après.
- Vérifier l'intégrité référentielle (`tout src/dst d'edges.parquet existe dans
  nodes.parquet`) — déjà couvert par les tests, mais à reconfirmer manuellement sur le run
  complet vu le changement d'échelle.

## 6. Validation humaine d'un échantillon d'entités (CA D.2)

La spec demande une précision vérifiée sur **≥ 50 mentions annotées**. Suggestion : générer
un CSV d'échantillon (`mention_links.parquet` filtré, ~50-100 lignes réparties par type
d'entité) avec le texte source autour de chaque mention, pour que Mohammed-Karim ou Reda
valide manuellement combien sont correctes. Documenter le taux de précision obtenu dans
`PROJECT_STATUS.md` (epic D) une fois fait — ne pas se contenter d'un graphe « qui tourne »
sans cette vérification, car l'extraction d'entités est plus sujette à erreur que l'OCR
déterministe.

## 7. Régénérer les tables de release complètes

```bash
.venv/bin/python scripts/build_release_tables.py
```

(vérifier dans le script les chemins d'entrée/sortie par défaut — sur le pilote ça produit
`outputs_v2/release_pilot/{documents,pages,chunks,edges,nodes,graph}` +
`release_manifest.json` + `CHECKSUMS.sha256` + `internet_archive_report.json`; sur le run
complet ça doit produire l'équivalent dans un dossier `outputs_v2/release/` dédié à la
release publique — séparé du pilote pour ne pas écraser le jeu actuellement utilisé par le
site avant d'être prêt à le remplacer).

Rappel des points de vigilance déjà notés dans `PROJECT_STATUS.md` : ne pas publier les PDF
sources sur Internet Archive tant que `rights_status` reste `to_review` pour un document
donné — `internet_archive_report.json` doit servir de checklist avant toute publication PDF.

## 8. Remplacer les données pilote du site par la release complète

Une fois la release complète prête et validée :

```bash
.venv/bin/python platform/scripts/build_site_data.py \
  --release outputs_v2/release \
  --site platform/site/public/data \
  --max-documents 500 \
  --max-graph-nodes 3000
```

- `--max-documents` et `--max-graph-nodes` bornent volontairement la taille servie au
  navigateur : avec 3 146 documents et un graphe enrichi, `documents.json`/`search.json`
  pourraient devenir lourds pour un chargement client en une fois. Vérifier la taille
  totale de `platform/site/public/data/` après génération (`du -sh`) et le temps de
  chargement de `/recherche/` et `/graphe/` avant de committer — si c'est trop lourd,
  réduire `--max-documents`/`--max-graph-nodes` ou prévoir une pagination/un chargement
  progressif côté `SearchInterface.astro`/`GraphView.astro` (actuellement ces deux
  composants chargent tout le JSON en un seul `fetch` au montage).
- Mettre à jour `manifest.json` (généré automatiquement par le script) et vérifier que la
  page d'accueil (`platform/site/src/pages/index.astro`) affiche les bons compteurs.
- `npm run build` depuis la racine pour vérifier que le site compile toujours avec le
  volume complet de données, puis committer/pousser comme pour le pilote (voir
  `PROJECT_STATUS.md` pour la procédure de push depuis la machine de l'utilisateur).

## 9. Mise à jour du suivi

Une fois les étapes 1–8 faites, mettre à jour `PROJECT_STATUS.md` :
- Epic C : `Fait`, avec le nombre d'arêtes/clusters obtenus et un lien vers
  `calibration_report.json`.
- Epic D : `Fait`, avec les compteurs de nœuds/arêtes par type et le taux de précision
  obtenu à l'étape 6.
- Epic F : passer de « données pilote » à « release complète » une fois l'étape 8 faite.
- Enchaîner ensuite sur l'étape 7 du « Prochaine séquence recommandée » déjà présente dans
  `PROJECT_STATUS.md` (release GitHub `v0.1.0`, publication Hugging Face, DOI Zenodo).

## Ordre récapitulatif

1. `pdfkb similarity build` complet (3 146 docs) → vérifier.
2. Annotation humaine `benchmarks/similarity_cases.json` (≥30/30).
3. `scripts/calibrate_similarity.py` → seuils définitifs dans `config.py`.
4. Re-run `pdfkb similarity build` avec seuils calibrés.
5. Étoffer `data/gazetteers/*.csv`.
6. `pdfkb graph build` complet.
7. Validation humaine d'un échantillon d'entités (≥50 mentions).
8. `scripts/build_release_tables.py` → release complète.
9. `platform/scripts/build_site_data.py` → remplacer les données pilote du site.
10. `npm run build` + commit/push + mise à jour `PROJECT_STATUS.md`.
