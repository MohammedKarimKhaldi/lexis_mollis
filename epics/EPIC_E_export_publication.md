# EPIC E — Export & publication des données (spec détaillée)

> Déclinaison exécutable de l'EPIC E. Empaquette les couches produites (documents, pages,
> chunks, edges, nodes, graphe RDF) en **jeux de données ouverts** et les publie : corpus
> sur **Hugging Face Datasets** (1 To gratuit), PDF lourds sur **Internet Archive**, versions
> citables avec **DOI sur Zenodo**. Licence **CC-BY-4.0**, attribution **Khaldi & Rostane**.
> Dépend d'EPIC A (comptes/secrets) et B (schémas) ; consomme les sorties de C/D.
> **DoD en §E.7.**

Garde-fous : publier la qualité **telle quelle** avec ses drapeaux (jamais « nettoyée » au
sens trompeur) ; `rights_status` par document, jamais inféré ; provenance (URL source)
conservée ; aucun secret dans les artefacts.

---

## E.0 Structure
```
scripts/
  build_release_tables.py   # SQLite + outputs_v2 -> tables Parquet normalisées
  export_hf_dataset.py      # tables -> dataset HF (push) + dataset card
  export_internet_archive.py# PDF sources -> item Internet Archive
  make_zenodo_metadata.py   # génère/valide .zenodo.json à partir de CITATION.cff
```
Sortie intermédiaire : `outputs_v2/release/` (Parquet shardé + card + checksums).

---

## E.1 Tables de release — `build_release_tables.py`
Construire des tables Parquet normalisées et **stables** à partir de l'état + des sorties :
| Table | Source | Clé | Schéma |
|-------|--------|-----|--------|
| `documents` | `documents` (SQLite) + métadonnées | `document_id` | `document.schema.json` |
| `pages` | `outputs_v2/kb/pages.jsonl` | `source_sha256,page_number` | `page.schema.json` |
| `chunks` | `outputs_v2/similarity/chunks.parquet` | `chunk_id` | `chunk.schema.json` |
| `edges` | `similarity/edges.parquet` + `graph/edges.parquet` | — | `edge.schema.json` |
| `nodes` | `graph/nodes.parquet` | `node_id` | `node.schema.json` |
Règles :
- Poser les **tags** finaux (taxonomie EPIC B) : `instrument_type`, `legal_force` (via
  `doc_type_mapping.json`), `period`, `century`, `quality`, `review`, `rights_status`,
  `source_db`.
- Sharder en Parquet < 50 Go/fichier, < 10 000 fichiers/dossier (contraintes HF) ; viser des
  shards de ~200–500 Mo (`documents/part-000.parquet`, …).
- Écrire `outputs_v2/release/CHECKSUMS.sha256` et `release_manifest.json` (comptes par table,
  version pipeline, date, périmètre — ex. « 1309 docs (sous-corpus) » ou « corpus complet »).
**CA E.1** : chaque table valide son schéma (réutiliser `validate_schemas.py`) ; manifeste +
checksums écrits ; aucune colonne secrète.

---

## E.2 Dataset Hugging Face — `export_hf_dataset.py`
Cible : `hf.co/datasets/lexis-mollis/soft-law-corpus`.
- Structure : un dossier par table (`documents/`, `pages/`, `chunks/`, `edges/`, `nodes/`) +
  `graph/` (copie de `graph.ttl`, `graph.jsonld`, `graph.sigma.json`).
- **Dataset card** `README.md` (front-matter YAML HF) : `license: cc-by-4.0`, `language:
  [fr, en, la, …]`, `tags`, `pretty_name`, `size_categories`, `configs` (un par table pour
  le *dataset viewer*) ; corps : description, **attribution Khaldi & Rostane**,
  **avertissement qualité/OCR** (texte historique/multilingue, pages `review_required`, ne
  pas traiter comme vérité absolue), dictionnaire de colonnes (renvoi `data_dictionary.md`),
  périmètre/version, liens Zenodo (DOI) et Internet Archive.
- Push via `huggingface_hub.HfApi.upload_folder(..., repo_type="dataset")`, token
  `HF_TOKEN` (secret). Versionner : tag/commit HF = version pipeline.
- Vérifier ensuite que le **dataset viewer** rend chaque `config`.
**CA E.2** : dataset public visible ; viewer fonctionnel sur les 5 tables ; card complète
(licence, attribution, avertissement, colonnes) ; reproductible (relance idempotente).

---

## E.3 PDF sources — `export_internet_archive.py`
Publier les PDF (selon droits) sur **Internet Archive** (un item collection + items par lot)
plutôt que sur HF (volumineux) :
- N'inclure que les documents dont `rights_status` ∈ {`public_domain_claimed`,
  `open_data_source`} ; exclure `restricted`/`to_review` (les lister dans un rapport).
- Métadonnées IA : titre, créateur (source d'origine), licence, identifiants
  (`document_id`, `source_sha256`), lien retour vers le dataset HF.
- Stocker l'URL IA résultante dans la table `documents` (champ `source_url`/`archive_url`) →
  régénérer la release si besoin.
**CA E.3** : items IA créés pour les documents éligibles ; chaque document publié a une URL
résolvable ; rapport des documents exclus (avec raison de droits).

---

## E.4 Release Zenodo / DOI — `make_zenodo_metadata.py` + webhook
- `make_zenodo_metadata.py` : régénère/valide `.zenodo.json` à partir de `CITATION.cff`
  (cohérence auteurs/licence/titre) ; échoue si divergence.
- Publication : créer une **release GitHub** taguée `vX.Y.Z` sur `pipeline` → le webhook
  Zenodo (EPIC A.3.2) archive et émet un **DOI**.
- Reporter le DOI dans `CITATION.cff` (`doi:`), le `README`, et la card HF.
- Pour les **données** (trop lourdes pour l'archive GitHub) : créer en complément un
  enregistrement Zenodo « dataset » pointant vers le dataset HF + checksums, ou y déposer un
  sous-ensemble (dans le quota 50 Go). Le DOI « concept » référence toutes les versions.
**CA E.4** : un DOI obtenu pour une release de test ; `.zenodo.json` cohérent avec
`CITATION.cff` ; DOI reporté partout.

---

## E.5 Versionnage & périmètre
- **Versions sémantiques** du dataset alignées sur le pipeline ; chaque release note le
  **périmètre** (sous-corpus 1 309 docs en Phase 1 ; corpus complet en Phase 3 post-OCR).
- Conserver l'historique : ne pas écraser une version publiée ; HF (git) + Zenodo (DOI
  versionné) assurent la traçabilité.
**CA E.5** : `release_manifest.json` indique version + périmètre + comptes ; versions
antérieures restent accessibles.

---

## E.6 Automatisation (lien EPIC G)
Ces scripts sont rejoués par `release.yml` (EPIC G.4) sur tag `v*` : build tables → push HF →
(option) dépôt Zenodo → mise à jour des liens. En CI, n'utiliser que les secrets ; aucune
donnée lourde commitée.
**CA E.6** : `release.yml` exécute la chaîne E.1→E.4 de bout en bout sur une release de test.

---

## E.7 Definition of Done (EPIC E)
- [ ] `build_release_tables.py` produit `documents/pages/chunks/edges/nodes` en Parquet
      shardé, valides aux schémas, + checksums + manifeste.
- [ ] Dataset HF public en ligne, *viewer* OK, **card** avec licence CC-BY-4.0, attribution
      Khaldi & Rostane, avertissement qualité et dictionnaire de colonnes.
- [ ] PDF éligibles publiés sur Internet Archive ; URLs reportées ; exclusions justifiées par
      `rights_status`.
- [ ] Release GitHub taguée → **DOI Zenodo** ; `.zenodo.json` cohérent ; DOI dans
      `CITATION.cff`/README/card.
- [ ] Périmètre et version documentés ; versions antérieures préservées.
- [ ] Aucun secret ni `rights_status` inféré ; provenance conservée.

> **Suite :** EPIC F — plateforme web (site Astro + Space de recherche + graphe Sigma.js),
> qui charge ce dataset publié.
