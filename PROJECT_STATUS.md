# Lexis Mollis — statut de déploiement

Dernière mise à jour vérifiée : 2026-07-01 (Codex : évaluation LLM provisoire, graphe/release complets, site Cloudflare déployé).

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

Le scaffold EPIC F n'est plus seulement testable localement : il a été alimenté depuis
`outputs_v2/release` et déployé sur Cloudflare Workers Static Assets. Le site public est :
`https://lexis-mollis.mk-74a.workers.dev`. Le manifeste public
`/data/manifest.json` annonce 3 146 documents, 26 566 pages, un graphe réduit à
3 000 nœuds et 9 000 arêtes pour l'affichage navigateur. Les exports lourds restent hors
Git et hors bundle statique complet ; Hugging Face/Zenodo restent la cible canonique pour
les tables complètes.

Une passe d'amélioration UI a aussi été faite sur `platform/site/src/` (favicon + balises
OG/Twitter, état actif dans la navigation, pied de page avec liens GitHub/Hugging Face,
légende des couleurs du graphe, recherche avec état de chargement + debounce, secours
`<noscript>` pour recherche/graphe, et surtout un sommaire + regroupement par paquets de
25 pages (`<details>`) sur les fiches document longues. Build Astro vérifié en local et
déployé sur Cloudflare avec les données complètes optimisées.

Le build **complet** de similarité a maintenant été lancé sur les 3 146 documents :
`outputs_v2/similarity/manifest.json` indique 30 285 chunks, 24 446 paires lexicales,
461 840 paires sémantiques, 310 098 arêtes chunk, 87 451 arêtes document et 116 clusters.
À la demande de l'utilisateur, Codex a rempli automatiquement toute la shortlist de
calibration comme **brouillon d'annotation LLM** : `benchmarks/similarity_cases.json`
contient maintenant 120 candidats annotés, dont 54 positifs, 50 négatifs et 16 exclus
comme non informatifs (numéros de page, renvois mécaniques, fragments trop courts).
`scripts/calibrate_similarity.py` marque explicitement ce rapport comme
`llm_draft_calibrated`, avec `human_validated=false`. Les seuils proposés sont donc utiles
pour avancer l'ingénierie, mais ne doivent pas être présentés comme une calibration
scientifique validée humainement.

Les gazetteers ont été enrichis avec les entités évidentes, puis le graphe et la release
ont été reconstruits sur le corpus complet. `benchmarks/gazetteer_candidates_llm_review.csv`
contient l'annotation LLM-draft des 300 candidats gazetteer restants. Après enrichissement,
`outputs_v2/graph/summary.json` indique 8 441 nœuds, 104 206 arêtes, 2 011 nœuds
provisoires et 12 786 arêtes provisoires.
`outputs_v2/release/release_manifest.json` indique 3 146 documents, 26 566 pages,
30 285 chunks, 414 304 arêtes et 8 441 nœuds.

Ce qui reste avant une publication académique/release v0.1.0 propre : remplacer ou confirmer
les annotations LLM par une validation humaine, valider un échantillon de mentions d'entités,
fournir un token Hugging Face avec droit `write` sur `lexis-mollis/soft-law-corpus`, créer le
tag GitHub pour Zenodo, puis reporter le DOI.

## État vérifié

| Élément | Statut | Preuve / note |
|---|---:|---|
| GitHub repo | OK | `MohammedKarimKhaldi/lexis_mollis`, public, branche `main`. |
| CI GitHub | OK | Workflow `CI` actif ; dernier run vérifié en succès. |
| `HF_TOKEN` | **Bloqué write** | Le token fourni identifie l'utilisateur et voit `lexis-mollis/soft-law-corpus`, mais l'upload LFS/Xet échoue en `403 Forbidden`. Il faut un token `write` ayant accès à l'organisation/dataset, puis révoquer le token exposé. |
| Hugging Face dataset | OK | `lexis-mollis/soft-law-corpus`, public, non gated, non disabled. |
| Zenodo | Connecté côté compte | Webhook/intégration annoncé comme connecté ; DOI vérifiable seulement après première release GitHub. |
| Cloudflare | **Déployé** | Worker `lexis-mollis` déployé sur `https://lexis-mollis.mk-74a.workers.dev` ; `/`, `/recherche/`, `/graphe/` et `/data/manifest.json` vérifiés en HTTP 200. Config Git Cloudflare préférée : root `platform/site`, build `npm ci && npm run build`, deploy `npx wrangler deploy`. |
| Site local | OK | Build Astro complet vérifié ; `platform/site/public/data/manifest.json` annonce 3 146 documents, 26 566 pages, graphe réduit 3 000 nœuds / 9 000 arêtes. |
| Branch protection | À configurer | Pas encore de protection `main`/required checks. |
| OCR | **Terminé** | 3 146/3 146 documents, 26 566 pages, 0 erreur, run sorti `status=0`. |
| Audit complet | **Terminé** | `outputs_v2/kb/` et `outputs_v2/audit/` régénérés sur le corpus complet (26 566 lignes chacun), 6 084 pages en file de révision (`outputs_v2/review_queue.csv` : 6 085 lignes avec en-tête). |
| Similarité complète | **Construite, calibrage LLM-draft complet** | `outputs_v2/similarity/` : 30 285 chunks, 87 451 arêtes document, 116 clusters. `benchmarks/similarity_cases.json` contient 120 candidats annotés : 54 positifs, 50 négatifs, 16 exclus ; `calibration_report.json` = `llm_draft_calibrated`, `human_validated=false`. |
| Gazetteers / graphe | **Graphe complet construit** | Gazetteers enrichis à 92 entrées ; `outputs_v2/graph/summary.json` : 8 441 nœuds, 104 206 arêtes. Annotation LLM des 300 candidats restants dans `benchmarks/gazetteer_candidates_llm_review.csv`. Reste : validation humaine d'un échantillon d'entités avant revendication scientifique. |

## Statut par epic

| Epic | Statut | Bloqué par / reste à faire |
|---|---:|---|
| A — Infrastructure & gouvernance | Partiel avancé | GitHub public OK, repo HF visible, CI OK. Reste : droit d'écriture effectif sur le dataset HF, branch protection, éventuelle org GitHub `lexis-mollis`, premier DOI Zenodo après release. |
| B — Modèle de données & standards | Fait | Schémas, taxonomie, ontologie, identifiants et validation automatisée en place. |
| C — Similarité | Build complet fait, calibration LLM-draft | `outputs_v2/similarity/` construit sur 3 146 documents. Fix appliqué : IDs de chunks document-scoped pour conserver les alias de PDF exacts ; scores FAISS clampés à `[0,1]`. `benchmarks/similarity_cases.json` contient 54 positifs / 50 négatifs / 16 exclus évalués par Codex. Reste : validation humaine si publication scientifique. |
| D — Knowledge graph | **Complet provisoire construit** | Gazetteers enrichis et graphe complet construit : 8 441 nœuds, 104 206 arêtes, 114 963 mentions. Reste : validation humaine d'au moins 50 mentions si revendication scientifique. |
| E — Export & publication | Release locale complète prête ; HF bloqué token | `outputs_v2/release` construit sur 3 146 documents / 26 566 pages ; `outputs_v2/hf_dataset` préparé localement. Upload HF tenté puis bloqué par `403 Forbidden` sur LFS/Xet avec le token fourni ; un commit test minimal est également refusé en `403`. Reste : token HF write valide, tag GitHub, DOI Zenodo après release. |
| F — Plateforme web | **Déployé avec données complètes optimisées** | Astro + Workers Static Assets déployé sur `https://lexis-mollis.mk-74a.workers.dev`, avec manifest complet, recherche statique, fiches document et graphe réduit. Les JSON statiques complets optimisés sont maintenant destinés à être versionnés pour rendre le déploiement Git reproductible. Reste : domaine personnalisé éventuel, recherche HF Space/FAISS réelle, publication canonique HF. |
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

État actuel : les étapes 1 à 3 ont été exécutées automatiquement avec une annotation
LLM-draft, pas une validation humaine. Cette distinction est volontairement conservée dans
les fichiers de sortie et dans le rapport de calibration.

1. Calibration de similarité :
   - fait en brouillon LLM sur toute la shortlist : 54 cas positifs, 50 cas négatifs et
     16 cas exclus dans `benchmarks/similarity_cases.json` ;
   - `outputs_v2/similarity/calibration_report.json` signale
     `status=llm_draft_calibrated` et `human_validated=false` ;
   - à refaire ou confirmer humainement avant publication scientifique.
2. Gazetteers et graphe :
   - gazetteers enrichis pour les entités évidentes ;
   - annotation LLM-draft des 300 candidats restants dans
     `benchmarks/gazetteer_candidates_llm_review.csv` ;
   - graphe complet construit dans `outputs_v2/graph` ;
   - reste : audit humain d'un échantillon d'entités/relations.
3. Release complète :
   ```bash
   .venv/bin/python scripts/build_release_tables.py \
     --kb outputs_v2/kb/pages.jsonl \
     --similarity outputs_v2/similarity \
     --graph outputs_v2/graph \
     --output outputs_v2/release \
     --scope full_corpus_v0_1
   ```
   Fait : `outputs_v2/release/release_manifest.json` indique 3 146 documents et
   26 566 pages.
4. Préparer puis publier la base canonique sur Hugging Face :
   ```bash
   .venv/bin/python scripts/export_hf_dataset.py --release outputs_v2/release
   .venv/bin/python scripts/export_hf_dataset.py --release outputs_v2/release --upload
   ```
   Préparation locale faite dans `outputs_v2/hf_dataset`. Upload tenté le 2026-07-01 avec
   le token fourni, mais Hugging Face renvoie `403 Forbidden` sur LFS/Xet malgré un
   `whoami` valide et un repo visible. Dataset cible : `lexis-mollis/soft-law-corpus`.
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
   Fait : site public `https://lexis-mollis.mk-74a.workers.dev`.

Critères d'acceptation de la base publique :

- `outputs_v2/release/release_manifest.json` indique 3 146 documents et 26 566 pages. **OK**
- Le dataset HF expose les tables `documents`, `pages`, `chunks`, `edges`, `nodes` et le
  dossier `graph/`. **Bloqué actuellement : le repo est visible mais l'écriture est refusée
  en `403 Forbidden`, même pour un fichier test minimal.**
- Le site Cloudflare expose `manifest.json`, `documents.json`, `search.json`,
  `facets.json`, `docs/<document_id>.json` et `graph.sigma.json`. **OK**
- Les fiches documents affichent titre, type, année, langues, score qualité, statut de
  révision, texte OCR, documents similaires, licence et liens vers les données.
- Les pages faibles restent visibles avec `review_required` / `review_priority` et les
  relations incertaines restent marquées `provisional`.
- Aucun asset statique Cloudflare ne dépasse 25 MiB et le nombre de fichiers reste sous la
  limite du palier gratuit ; les gros exports complets restent servis par HF/Zenodo. **OK
  sur la génération actuelle : 3 151 fichiers de données, 75 MiB avant build.**

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
Les deux configurations utilisent `assets.not_found_handling = "single-page-application"` :
cela évite le 404 sur `/` et les routes Astro servies via Workers Static Assets.

Déploiement direct vérifié :

```text
URL: https://lexis-mollis.mk-74a.workers.dev
Version ID: 7793e9f4-b261-43ea-a7cd-569b15c65d92
Checks: /, /recherche/, /graphe/ et /data/manifest.json en HTTP 200
```

À faire côté Cloudflare :

1. Créer ou choisir un compte Cloudflare.
2. Connecter le dépôt GitHub et choisir le root `platform/site`.
3. Déployer avec les commandes ci-dessus. Fait une première fois via Wrangler local.
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

1. Décision appliquée : versionner aussi `platform/site/public/data/` complet optimisé
   pour que le déploiement Cloudflare Git reste reproductible, tout en gardant les gros
   artefacts (`outputs_v2`, Parquet bruts, embeddings, SQLite, PDF) hors Git.
2. Committer/pousser les changements de code, statut, annotations LLM-draft, gazetteers et
   données statiques optimisées :
   `PROJECT_STATUS.md`, `benchmarks/similarity_cases.json`,
   `benchmarks/gazetteer_candidates_llm_review.csv`, `scripts/calibrate_similarity.py`,
   `data/gazetteers/*.csv`, `wrangler.jsonc`, `platform/site/wrangler.jsonc` et
   `platform/site/public/data/`.
3. Pour une validation scientifique, remplacer le brouillon LLM par une annotation humaine :
   - relire les 120 cas dans `benchmarks/similarity_cases.json` ;
   - ajuster `label`, `expected_type` et `notes` ;
   - changer `annotation_source` seulement lorsque l'annotation est effectivement humaine.
4. Relancer la calibration après validation humaine :
   ```bash
   .venv/bin/python scripts/calibrate_similarity.py \
     --similarity-dir outputs_v2/similarity \
     --cases benchmarks/similarity_cases.json \
     --output outputs_v2/similarity/calibration_report.json
   ```
   Si les seuils changent substantiellement, re-builder la similarité puis le graphe.
5. Valider ≥50 mentions d'entités/relations dans le graphe, puis relancer si nécessaire :
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
6. Régénérer la release si la similarité ou le graphe changent :
   ```bash
   .venv/bin/python scripts/build_release_tables.py \
     --kb outputs_v2/kb/pages.jsonl \
     --similarity outputs_v2/similarity \
     --graph outputs_v2/graph \
     --output outputs_v2/release \
     --scope full_corpus_v0_1
   ```
7. Publier le dataset HF :
   ```bash
   .venv/bin/python scripts/export_hf_dataset.py --release outputs_v2/release --upload
   ```
   Bloqué tant que `HF_TOKEN` n'a pas un droit `write` effectif sur
   `lexis-mollis/soft-law-corpus`.
8. Ajouter `release.yml`, créer le tag GitHub `v0.1.0`, récupérer le DOI Zenodo et le
   reporter dans `CITATION.cff`, `README.md` et la card Hugging Face.
9. Ajouter `deploy-site.yml` seulement si le déploiement doit passer par GitHub Actions
   plutôt que par l'intégration Git Cloudflare ou Wrangler local.

## Points de vigilance

- Ne pas publier les PDF sur Internet Archive tant que `rights_status` reste `to_review`.
- Ne pas affirmer que les seuils de similarité sont calibrés avant annotation humaine.
- Ne pas committer de secrets, sorties OCR, bases SQLite, fichiers Parquet, embeddings ou PDF.
- Le token Hugging Face exposé précédemment a été utilisé à la demande de l'utilisateur,
  mais il ne permet pas l'upload (`403 Forbidden`). Le révoquer et le remplacer par un
  token `write` de préférence finement scoped au dataset.
