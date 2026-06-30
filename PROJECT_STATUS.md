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
22 nœuds graphe, 23 arêtes. Ce jeu pilote est utile pour tester l'interface, mais il faut
décider avant commit si l'on garde ces données pilotes ou si l'on revient au minuscule
sample prévu pour Cloudflare.

Ce qui reste avant le déploiement public complet : lancer les builds **complets** (pas
pilotes) de similarité/graphe/release sur les 3 146 documents, finaliser le déploiement
Cloudflare, et faire l'annotation humaine de calibration des seuils de similarité.

**Changements locaux à traiter avant tout build public :** `.gitignore`,
`PROJECT_STATUS.md`, la configuration Node/Wrangler racine (`package.json`,
`package-lock.json`, `wrangler.jsonc`, `.nvmrc`, `.npmrc`) et le dossier `platform/` sont
modifiés/non suivis. `node_modules/`, `dist/`, `.astro/` et `.wrangler/` sont exclus par le
`.gitignore` modifié. À faire : choisir si `platform/site/public/data/` doit contenir le
sample minimal ou le pilote de 100 documents, puis committer/pousser les fichiers retenus
vers `origin/main`.

## État vérifié

| Élément | Statut | Preuve / note |
|---|---:|---|
| GitHub repo | OK | `MohammedKarimKhaldi/lexis_mollis`, public, branche `main`. |
| CI GitHub | OK | Workflow `CI` actif ; dernier run vérifié en succès. |
| `HF_TOKEN` | Configuré | Secret GitHub Actions présent. À régénérer si le token exposé précédemment n'a pas encore été révoqué. |
| Hugging Face dataset | OK | `lexis-mollis/soft-law-corpus`, public, non gated, non disabled. |
| Zenodo | Connecté côté compte | Webhook/intégration annoncé comme connecté ; DOI vérifiable seulement après première release GitHub. |
| Cloudflare | Scaffold prêt | `platform/site` ajouté pour Workers Static Assets ; configuration Git Cloudflare préférée : root `platform/site`, build `npm ci && npm run build`, deploy `npx wrangler deploy`. Configuration racine aussi ajoutée pour les builds qui partent de `/` ; optional deps npm forcées et bindings Linux Astro/esbuild/Rolldown déclarés explicitement ; `npm ci && npm run build` et `npm run deploy -- --dry-run` validés depuis la racine. |
| Site local | OK | Astro dev server testé en HTTP 200 sur `http://127.0.0.1:4321/`; données actuelles : pilote `outputs_v2/release_pilot` limité à 100 documents. |
| Branch protection | À configurer | Pas encore de protection `main`/required checks. |
| OCR | **Terminé** | 3 146/3 146 documents, 26 566 pages, 0 erreur, run sorti `status=0`. |
| Audit complet | **Terminé** | `outputs_v2/kb/` et `outputs_v2/audit/` régénérés sur le corpus complet (26 566 lignes chacun), 6 084 pages en file de révision (`outputs_v2/review_queue.csv` : 6 085 lignes avec en-tête). |

## Statut par epic

| Epic | Statut | Bloqué par / reste à faire |
|---|---:|---|
| A — Infrastructure & gouvernance | Partiel avancé | GitHub public OK, HF dataset OK, CI OK. Reste : branch protection, éventuelle org GitHub `lexis-mollis`, premier DOI Zenodo après release. |
| B — Modèle de données & standards | Fait | Schémas, taxonomie, ontologie, identifiants et validation automatisée en place. |
| C — Similarité | Implémenté, pilote fait | OCR terminé : build complet à lancer maintenant sur les 3 146 documents (le `similarity_pilot` actuel n'a qu'1 arête/2 clusters, donc non représentatif). Annoter ≥30 paires positives et ≥30 négatives pour calibrer les seuils (`scripts/calibrate_similarity.py` existe, aucune annotation humaine trouvée sur le disque). |
| D — Knowledge graph | Implémenté, pilote fait | Build complet à lancer après le build de similarité complet ; enrichir gazetteers ; valider un échantillon d'entités. |
| E — Export & publication | Outillage local fait | Publier vers HF après release complète ; DOI Zenodo après tag ; droits PDF à revoir avant Internet Archive. |
| F — Plateforme web | Scaffold déployable, test local OK | Astro + Workers Static Assets, données pilote locales, pages principales, Sigma.js et Spaces search/SPARQL scaffolds. Reste : décider sample vs pilote à committer, brancher release complète, recherche FAISS/BM25 réelle, URL publique. |
| G — CI/CD | Partiel | CI qualité OK. Reste : `build-derive.yml`, `release.yml`, `deploy-site.yml`, `keepalive.yml`. |
| H — Expansion corpus | Non commencé | Choisir et implémenter le premier connecteur, probablement EUR-Lex, avec droits/provenance explicites. |
| I — Révision communauté | Non commencé | Générer lots de révision ; choisir mini-interface Astro ou workflow issues GitHub ; stocker `review_events.jsonl`. |

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
optionnelles ; les bindings Linux nécessaires à Astro, esbuild et Rolldown sont aussi
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
3. Lancer le build complet sur les 3 146 documents (OCR et audit déjà faits, donc
   l'étape `audit` ci-dessous est surtout une re-vérification rapide) :
   ```bash
   .venv/bin/python -m pdfkb audit --state metadata/pipeline.sqlite3 --output outputs_v2 --light
   .venv/bin/python -m pdfkb similarity build --kb outputs_v2/kb/pages.jsonl --output outputs_v2/similarity
   .venv/bin/python -m pdfkb graph build --kb outputs_v2/kb/pages.jsonl --similarity outputs_v2/similarity --output outputs_v2/graph
   .venv/bin/python scripts/build_release_tables.py
   ```
4. Annoter ≥30 paires positives et ≥30 négatives et lancer
   `scripts/calibrate_similarity.py` pour calibrer les seuils avant de communiquer
   sur la qualité de la similarité.
5. Déployer le scaffold Astro Cloudflare avec les commandes ci-dessus.
6. Ajouter `deploy-site.yml` Cloudflare si le déploiement doit passer par GitHub Actions.
7. Ajouter `release.yml`, publier le dataset HF, créer le tag GitHub `v0.1.0`, récupérer le DOI Zenodo et le reporter dans `CITATION.cff`, `README.md` et la card Hugging Face.

## Points de vigilance

- Ne pas publier les PDF sur Internet Archive tant que `rights_status` reste `to_review`.
- Ne pas affirmer que les seuils de similarité sont calibrés avant annotation humaine.
- Ne pas committer de secrets, sorties OCR, bases SQLite, fichiers Parquet, embeddings ou PDF.
- Si le token Hugging Face exposé précédemment n'a pas été remplacé, le révoquer et mettre à jour `HF_TOKEN`.
