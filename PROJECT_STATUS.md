# Lexis Mollis — statut de déploiement

Dernière mise à jour vérifiée : 2026-06-30.

## Résumé

Le socle local est opérationnel : pipeline OCR v2, schémas, similarité, knowledge graph,
outillage de release et CI GitHub. Le dépôt GitHub est public, le dataset Hugging Face
`lexis-mollis/soft-law-corpus` existe et est public, et Zenodo est connecté à GitHub selon
la configuration effectuée côté compte.

Le déploiement public complet reste bloqué par la configuration Cloudflare, par la fin de
l'OCR, puis par les builds complets de similarité/graphe/release.

## État vérifié

| Élément | Statut | Preuve / note |
|---|---:|---|
| GitHub repo | OK | `MohammedKarimKhaldi/lexis_mollis`, public, branche `main`. |
| CI GitHub | OK | Workflow `CI` actif ; dernier run vérifié en succès. |
| `HF_TOKEN` | Configuré | Secret GitHub Actions présent. À régénérer si le token exposé précédemment n'a pas encore été révoqué. |
| Hugging Face dataset | OK | `lexis-mollis/soft-law-corpus`, public, non gated, non disabled. |
| Zenodo | Connecté côté compte | Webhook/intégration annoncé comme connecté ; DOI vérifiable seulement après première release GitHub. |
| Cloudflare | À configurer | Aucun secret Cloudflare GitHub Actions présent, aucun workflow de déploiement site encore présent. |
| Branch protection | À configurer | Pas encore de protection `main`/required checks. |
| OCR | En cours | 23 824 / 26 540 pages, 89.766 %, 0 erreur lors de la dernière vérification. |

## Statut par epic

| Epic | Statut | Bloqué par / reste à faire |
|---|---:|---|
| A — Infrastructure & gouvernance | Partiel avancé | GitHub public OK, HF dataset OK, CI OK. Reste : branch protection, éventuelle org GitHub `lexis-mollis`, premier DOI Zenodo après release. |
| B — Modèle de données & standards | Fait | Schémas, taxonomie, ontologie, identifiants et validation automatisée en place. |
| C — Similarité | Implémenté, pilote fait | Attendre fin OCR pour build complet ; annoter ≥30 paires positives et ≥30 négatives pour calibrer les seuils. |
| D — Knowledge graph | Implémenté, pilote fait | Attendre full similarity/full OCR ; enrichir gazetteers ; valider un échantillon d'entités. |
| E — Export & publication | Outillage local fait | Publier vers HF après release complète ; DOI Zenodo après tag ; droits PDF à revoir avant Internet Archive. |
| F — Plateforme web | Non commencé | Choix Cloudflare confirmé ; créer `platform/site`, données site, workflow Cloudflare et secrets. |
| G — CI/CD | Partiel | CI qualité OK. Reste : `build-derive.yml`, `release.yml`, `deploy-site.yml`, `keepalive.yml`. |
| H — Expansion corpus | Non commencé | Choisir et implémenter le premier connecteur, probablement EUR-Lex, avec droits/provenance explicites. |
| I — Révision communauté | Non commencé | Générer lots de révision ; choisir mini-interface Astro ou workflow issues GitHub ; stocker `review_events.jsonl`. |

## Déploiement Cloudflare — besoins restants

À faire côté Cloudflare :

1. Créer ou choisir un compte Cloudflare.
2. Créer un projet Cloudflare Pages, recommandé : `lexis-mollis`.
3. Créer un token API Cloudflare limité au déploiement Pages.
4. Ajouter les secrets GitHub Actions :
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
5. Ajouter le workflow `deploy-site.yml` après création de `platform/site`.

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

1. Finir l'OCR sans interruption.
2. Construire une première plateforme Astro avec données pilote locales.
3. Ajouter `deploy-site.yml` Cloudflare.
4. À 100 % OCR :
   ```bash
   .venv/bin/python -m pdfkb audit --state metadata/pipeline.sqlite3 --output outputs_v2 --light
   .venv/bin/python -m pdfkb similarity build --kb outputs_v2/kb/pages.jsonl --output outputs_v2/similarity
   .venv/bin/python -m pdfkb graph build --kb outputs_v2/kb/pages.jsonl --similarity outputs_v2/similarity --output outputs_v2/graph
   .venv/bin/python scripts/build_release_tables.py
   ```
5. Ajouter `release.yml`, publier le dataset HF, créer le tag GitHub `v0.1.0`, récupérer le DOI Zenodo et le reporter dans `CITATION.cff`, `README.md` et la card Hugging Face.

## Points de vigilance

- Ne pas publier les PDF sur Internet Archive tant que `rights_status` reste `to_review`.
- Ne pas affirmer que les seuils de similarité sont calibrés avant annotation humaine.
- Ne pas committer de secrets, sorties OCR, bases SQLite, fichiers Parquet, embeddings ou PDF.
- Si le token Hugging Face exposé précédemment n'a pas été remplacé, le révoquer et mettre à jour `HF_TOKEN`.

