# Lexis Mollis — statut de déploiement

Dernière mise à jour vérifiée : 2026-06-30 (re-vérifiée par Codex après la fin de l'OCR et le test local de la plateforme).

## Résumé

**L'OCR est terminé.** Le run est sorti avec `status=0` à 22:23:22+0100 :
3 146/3 146 documents exportés, 26 566 pages, 0 document incomplet, 0 erreur.
**L'audit complet a déjà tourné sur l'ensemble du corpus** dans la foulée :
`outputs_v2/kb/pages.jsonl` et `outputs_v2/audit/pages.jsonl` contiennent chacun
26 566 lignes, `outputs_v2/clean/` et `outputs_v2/raw/` contiennent chacun 3 146
fichiers Markdown. Le blocage « attendre la fin de l'OCR » des versions précédentes de
ce document n'existe donc plus.

Le socle local est opérationnel : pipeline OCR v2, schémas, similarité, knowledge graph,
outillage de release et CI GitHub. Le dépôt GitHub est public, le dataset Hugging Face
`lexis-mollis/soft-law-corpus` existe et est public, et Zenodo est connecté à GitHub selon
la configuration effectuée côté compte.

Le scaffold EPIC F est maintenant testable localement : Astro répond sur
`http://127.0.0.1:4321/`, et `platform/site/public/data/` contient actuellement une
génération pilote depuis `outputs_v2/release_pilot` : 100 documents, 1 462 pages,
22 nœuds graphe, 23 arêtes. **Décision (Claude, 2026-06-30) : on garde le jeu pilote de
100 documents** plutôt que les 2 documents d'exemple fictifs — le site déployé doit
montrer du vrai contenu du corpus. À swapper pour la release complète (3 146 documents)
dès que les builds complets de similarité/graphe (EPIC C/D) seront prêts ; voir
`scripts/build_site_data.py` côté génération.

Une passe d'amélioration UI a aussi été faite sur `platform/site/src/` (favicon + balises
OG/Twitter, état actif dans la navigation, pied de page avec liens GitHub/Hugging Face,
légende des couleurs du graphe, recherche avec état de chargement + debounce, secours
`<noscript>` pour recherche/graphe, et surtout un sommaire + regroupement par paquets de
25 pages (`<details>`) sur les fiches document longues — le pilote contient un document de
445 pages qui rendait la fiche très lourde sans ce découpage). Build Astro vérifié en
local (106 pages générées, 0 erreur).

Le build **complet** de similarité a maintenant été lancé sur les 3 146 documents :
`outputs_v2/similarity/manifest.json` indique 30 285 chunks, 24 446 paires lexicales,
461 840 paires sémantiques, 310 098 arêtes chunk, 87 451 arêtes document et 116 clusters.
La calibration reste volontairement non revendiquée : `benchmarks/similarity_cases.json`
contient encore 0 cas annoté, et `outputs_v2/similarity/calibration_report.json` signale
`insufficient_annotations`. Une shortlist de 120 candidats humains est disponible dans
`outputs_v2/similarity/calibration_candidates.csv` / `.json`.

Ce qui reste avant le déploiement public complet : annoter les paires de calibration,
valider/enrichir les gazetteers puis lancer les builds **complets** graphe/release sur les
3 146 documents, finaliser le déploiement Cloudflare, et publier la release.

**Changements locaux traités par Claude (2026-06-30) :** données pilote (100 documents) et
améliorations UI ci-dessus committées sur `main`. Le push depuis le bac à sable Claude
échoue (pas de clé SSH/identifiants GitHub dans cet environnement isolé) ; un `git push
origin main` depuis la machine de l'utilisateur reste nécessaire après chaque session.

## État vérifié

| Élément | Statut | Preuve / note |
|---|---:|---|
| GitHub repo | OK | `MohammedKarimKhaldi/lexis_mollis`, public, branche `main`. |
| CI GitHub | OK | Workflow `CI` actif ; dernier run vérifié en succès. |
| `HF_TOKEN` | Configuré | Secret GitHub Actions présent. À régénérer si le token exposé précédemment n'a pas encore été révoqué. |
| Hugging Face dataset | OK | `lexis-mollis/soft-law-corpus`, public, non gated, non disabled. |
| Zenodo | Connecté côté compte | Webhook/intégration annoncé comme connecté ; DOI vérifiable seulement après première release GitHub. |
| Cloudflare | Scaffold prêt | `platform/site` ajouté pour Workers Static Assets ; configuration Git Cloudflare préférée : root `platform/site`, build `npm ci && npm run build`, deploy `npx wrangler deploy`. Configuration racine aussi ajoutée pour les builds qui partent de `/` ; optional deps npm forcées et bindings Linux Astro/esbuild/Rolldown/Lightning CSS déclarés explicitement ; `npm ci && npm run build` et `npm run deploy -- --dry-run` validés depuis la racine. |
| Site local | OK | Astro dev server testé en HTTP 200 sur `http://127.0.0.1:4321/`; données actuelles : pilote `outputs_v2/release_pilot` limité à 100 documents. |
| Branch protection | À configurer | Pas encore de protection `main`/required checks. |
| OCR | **Terminé** | 3 146/3 146 documents, 26 566 pages, 0 erreur, run sorti `status=0`. |
| Audit complet | **Terminé** | `outputs_v2/kb/` et `outputs_v2/audit/` régénérés sur le corpus complet (26 566 lignes chacun), 6 084 pages en file de révision (`outputs_v2/review_queue.csv` : 6 085 lignes avec en-tête). |
| Similarité complète | **Construite, non calibrée** | `outputs_v2/similarity/` : 30 285 chunks, 87 451 arêtes document, 116 clusters. Scores bornés `[0,1]`, IDs de chunks uniques. Calibration bloquée par annotation humaine ≥30/≥30. |
| Candidats gazetteer | Préparés | `outputs_v2/graph/gazetteer_candidates.csv` : 300 candidats fréquents non couverts à valider avant modification de `data/gazetteers/*.csv`. |

## Statut par epic

| Epic | Statut | Bloqué par / reste à faire |
|---|---:|---|
| A — Infrastructure & gouvernance | Partiel avancé | GitHub public OK, HF dataset OK, CI OK. Reste : branch protection, éventuelle org GitHub `lexis-mollis`, premier DOI Zenodo après release. |
| B — Modèle de données & standards | Fait | Schémas, taxonomie, ontologie, identifiants et validation automatisée en place. |
| C — Similarité | Build complet fait, calibration bloquée | `outputs_v2/similarity/` construit sur 3 146 documents. Fix appliqué : IDs de chunks document-scoped pour conserver les alias de PDF exacts ; scores FAISS clampés à `[0,1]`. Reste : annoter ≥30 paires positives et ≥30 négatives dans `benchmarks/similarity_cases.json`, puis relancer `scripts/calibrate_similarity.py` et re-builder avec seuils calibrés. |
| D — Knowledge graph | Implémenté, pilote fait ; préparation complète en cours | Build complet à lancer après validation/enrichissement des gazetteers et calibration ou décision explicite d'utiliser les seuils provisoires. `outputs_v2/graph/gazetteer_candidates.csv` propose 300 candidats à valider ; gazetteers actuels encore minces (12 États, 9 organisations, 10 lieux). Reste aussi : valider un échantillon d'entités (≥50 mentions). |
| E — Export & publication | Outillage local fait | Publier vers HF après release complète ; DOI Zenodo après tag ; droits PDF à revoir avant Internet Archive. |
| F — Plateforme web | Scaffold déployable, données pilote committées, UI améliorée | Astro + Workers Static Assets, 100 documents pilote committés, pages principales avec navigation active/footer/légende graphe/sommaire documents longs, Sigma.js et Spaces search/SPARQL scaffolds. Reste : brancher release complète (3 146 documents), recherche FAISS/BM25 réelle, confirmer URL publique Cloudflare. |
| G — CI/CD | Partiel | CI qualité OK. Reste : `build-derive.yml`, `release.yml`, `deploy-site.yml`, `keepalive.yml`. |
| H — Expansion corpus | Non commencé | Choisir et implémenter le premier connecteur, probablement EUR-Lex, avec droits/provenance explicites. |
| I — Révision communauté | Non commencé | Générer lots de révision ; choisir mini-interface Astro ou workflow issues GitHub ; stocker `review_events.jsonl`. |

## Base de données publique & affichage — plan verrouillé

Décision d'architecture : **Hugging Face Dataset est la source canonique complète** et
Cloudflare reste la vitrine publique optimisée. Les exports lourds (`outputs_v2/release`,
Parquet, RDF, embeddings, index FAISS) ne sont pas committés dans Git ; ils sont publiés via
Hugging Face/Zenodo, tandis que le site charge des JSON statiques réduits produits depuis la
release.

Flux prévu :

1. Finaliser la calibration humaine de similarité : annoter ≥30 positifs et ≥30 négatifs
   dans `benchmarks/similarity_cases.json`, puis relancer `scripts/calibrate_similarity.py`.
2. Valider/enrichir les gazetteers depuis `outputs_v2/graph/gazetteer_candidates.csv`, puis
   lancer le graphe complet dans `outputs_v2/graph`.
3. Construire la release complète :
   ```bash
   .venv/bin/python scripts/build_release_tables.py \
     --kb outputs_v2/kb/pages.jsonl \
     --similarity outputs_v2/similarity \
     --graph outputs_v2/graph \
     --output outputs_v2/release \
     --scope full_corpus_v0_1
   ```
4. Préparer puis publier la base canonique sur Hugging Face :
   ```bash
   .venv/bin/python scripts/export_hf_dataset.py --release outputs_v2/release
   .venv/bin/python scripts/export_hf_dataset.py --release outputs_v2/release --upload
   ```
   Dataset cible : `lexis-mollis/soft-law-corpus`.
5. Générer la couche Cloudflare depuis la release :
   ```bash
   .venv/bin/python platform/scripts/build_site_data.py \
     --release outputs_v2/release \
     --site platform/site/public/data \
     --max-documents 4000 \
     --max-graph-nodes 3000 \
     --search-text-chars 1200
   ```
6. Tester et déployer :
   ```bash
   npm run build
   npx wrangler deploy --dry-run
   npx wrangler deploy
   ```

Critères d'acceptation de la base publique :

- `outputs_v2/release/release_manifest.json` indique 3 146 documents et 26 566 pages.
- Le dataset HF expose les tables `documents`, `pages`, `chunks`, `edges`, `nodes` et le
  dossier `graph/`.
- Le site Cloudflare expose `manifest.json`, `documents.json`, `search.json`,
  `facets.json`, `docs/<document_id>.json` et `graph.sigma.json`.
- Les fiches documents affichent titre, type, année, langues, score qualité, statut de
  révision, texte OCR, documents similaires, licence et liens vers les données.
- Les pages faibles restent visibles avec `review_required` / `review_priority` et les
  relations incertaines restent marquées `provisional`.
- Aucun asset statique Cloudflare ne dépasse 25 MiB et le nombre de fichiers reste sous la
  limite du palier gratuit ; les gros exports complets restent servis par HF/Zenodo.

## Déploiement Cloudflare — configuration

Si Cloudflare demande un build command et un deploy command, utiliser :

```text
Root directory: platform/site
Build command: npm ci && npm run build
Deploy command: npx wrangler deploy
```

Si le log Cloudflare montre `Installing project dependencies: pip install .`, alors le build
part de la racine Python du dépôt au lieu de `platform/site`. Dans ce cas, utiliser la
configuration racine tolérante :

```text
Root directory: /
Build command: npm ci && npm run build
Deploy command: npm run deploy
```

Les configurations Workers Static Assets sont versionnées dans `platform/site/wrangler.jsonc`
et `wrangler.jsonc` à la racine. La configuration racine déploie `platform/site/dist`.
Le lockfile racine `package-lock.json` est nécessaire pour que `npm ci` fonctionne depuis
la racine Cloudflare. Les fichiers `.npmrc` forcent l'installation des dépendances natives
optionnelles ; les bindings Linux nécessaires à Astro, esbuild, Rolldown et Lightning CSS sont aussi
déclarés directement pour éviter les échecs de résolution optionnelle/transitive.

À faire côté Cloudflare :

1. Créer ou choisir un compte Cloudflare.
2. Connecter le dépôt GitHub et choisir le root `platform/site`.
3. Déployer avec les commandes ci-dessus.
4. Optionnel pour EPIC G : créer un token API Cloudflare limité au déploiement.
5. Optionnel pour GitHub Actions : ajouter les secrets :
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
6. Ajouter `deploy-site.yml` seulement si on choisit le déploiement via GitHub Actions plutôt que via l’intégration Git Cloudflare.

Commandes prévues après obtention des valeurs :

```bash
read -s CLOUDFLARE_API_TOKEN
gh secret set CLOUDFLARE_API_TOKEN --repo MohammedKarimKhaldi/lexis_mollis --body "$CLOUDFLARE_API_TOKEN"
unset CLOUDFLARE_API_TOKEN

read -r CLOUDFLARE_ACCOUNT_ID
gh secret set CLOUDFLARE_ACCOUNT_ID --repo MohammedKarimKhaldi/lexis_mollis --body "$CLOUDFLARE_ACCOUNT_ID"
unset CLOUDFLARE_ACCOUNT_ID
```

## Prochaine séquence recommandée

1. Choisir le contenu de `platform/site/public/data/` à committer :
   - sample minimal pour un repo léger et un build Cloudflare garanti ;
   - ou pilote 100 documents pour une démo locale/publique plus parlante.
2. Committer et pousser les changements en attente : `.gitignore`, `PROJECT_STATUS.md`,
   `package.json`, `package-lock.json`, `wrangler.jsonc`, `.nvmrc`, `.npmrc`, puis `platform/`
   (en excluant `node_modules/`, `dist/`, `.astro/`, `.wrangler/` — déjà couverts par le
   `.gitignore` modifié).
3. Annoter la calibration de similarité :
   - ouvrir `outputs_v2/similarity/calibration_candidates.csv` ;
   - copier ≥30 cas positifs et ≥30 cas négatifs validés dans `benchmarks/similarity_cases.json` ;
   - renseigner `label`, `expected_type` et `notes`.
4. Lancer la calibration et, si les seuils changent, re-builder la similarité :
   ```bash
   .venv/bin/python scripts/calibrate_similarity.py \
     --similarity-dir outputs_v2/similarity \
     --cases benchmarks/similarity_cases.json \
     --output outputs_v2/similarity/calibration_report.json

   OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
     .venv/bin/python -m pdfkb similarity build \
     --kb outputs_v2/kb/pages.jsonl \
     --output outputs_v2/similarity \
     --model sentence-transformers/LaBSE \
     --target-tokens 384 --overlap 64 \
     --seed 20260701
   ```
5. Valider/enrichir les gazetteers depuis `outputs_v2/graph/gazetteer_candidates.csv`, puis lancer le graphe complet :
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
6. Valider ≥50 mentions d'entités, puis générer la release complète :
   ```bash
   .venv/bin/python scripts/build_release_tables.py
   ```
7. Déployer le scaffold Astro Cloudflare avec les commandes ci-dessus.
8. Ajouter `deploy-site.yml` Cloudflare si le déploiement doit passer par GitHub Actions.
9. Ajouter `release.yml`, publier le dataset HF, créer le tag GitHub `v0.1.0`, récupérer le DOI Zenodo et le reporter dans `CITATION.cff`, `README.md` et la card Hugging Face.

## Points de vigilance

- Ne pas publier les PDF sur Internet Archive tant que `rights_status` reste `to_review`.
- Ne pas affirmer que les seuils de similarité sont calibrés avant annotation humaine.
- Ne pas committer de secrets, sorties OCR, bases SQLite, fichiers Parquet, embeddings ou PDF.
- Si le token Hugging Face exposé précédemment n'a pas été remplacé, le révoquer et mettre à jour `HF_TOKEN`.
