# EPIC G — Automatisation CI/CD (spec détaillée)

> Déclinaison exécutable de l'EPIC G. Orchestre tout : qualité du code (lint/tests/schémas),
> construction des **dérivés** (similarité + graphe), déploiement du **site**, et **releases**
> (HF + Zenodo/DOI). Tout en **GitHub Actions, gratuit et illimité pour dépôts publics**.
> Dépend d'EPIC A (secrets) ; déclenche les chaînes C/D/E/F. **DoD en §G.7.**

Garde-fous : aucun secret en clair ; seeds fixés (reproductibilité) ; dépôts **publics** ;
jobs déterministes et idempotents.

---

## G.0 Fichiers
```
.github/workflows/
  ci.yml             # lint + tests + validation schémas/gouvernance (push/PR)
  build-derive.yml   # similarity build + graph build (manuel / changement données)
  deploy-site.yml    # build + déploiement du site Astro
  release.yml        # tag v* -> tables release + push HF + DOI Zenodo
  keepalive.yml      # cron: ping du Space de recherche (anti-veille 48 h)
```

---

## G.1 `ci.yml` — qualité (obligatoire pour merger)
Déclencheurs : `push` sur `main`, `pull_request`.
Étapes :
- `actions/setup-python@v5` (3.11) ; `pip install -e .[derive]` + `ruff black jsonschema
  rdflib cffconvert` ;
- `ruff check .` ; `black --check .` ;
- `python -m unittest discover -v` ;
- `python scripts/validate_schemas.py` (EPIC B) ;
- `python scripts/check_governance.py` (EPIC A) ;
- `cffconvert --validate`.
Cache pip (`actions/cache`). Job requis par la protection de branche (EPIC A.1.5).
**CA G.1** : vert sur `main` ; bloque une PR si lint/tests/schémas/gouvernance échouent.

---

## G.2 `build-derive.yml` — dérivés (similarité + graphe)
Déclencheurs : `workflow_dispatch` (manuel) + `push` touchant les données nettoyées
(quand applicable) ; `concurrency` pour éviter les runs concurrents.
Étapes :
- restaurer le **cache d'embeddings** (`actions/cache` sur `embeddings_cache.parquet` +
  `embeddings.npy`, clé = hash des `text_sha256`) ;
- `pdfkb similarity build --kb … --output outputs_v2/similarity` ;
- `pdfkb graph build --kb … --similarity outputs_v2/similarity --output outputs_v2/graph` ;
- publier les artefacts (`actions/upload-artifact`) : `summary.json`, `edges.parquet`,
  `graph.sigma.json`, rapports.
> Le corpus complet peut excéder le temps/RAM d'un runner gratuit : pour les gros volumes,
> exécuter en **local/poste** puis pousser les dérivés ; la CI valide et publie. Le cache
> rend les relances incrémentales.
**CA G.2** : run reproductible ; cache d'embeddings réutilisé (0 ré-encodage si inchangé) ;
artefacts disponibles.

---

## G.3 `deploy-site.yml` — site Astro
Déclencheurs : `push` sur `main` touchant `platform/` ; `workflow_dispatch`.
Étapes :
- `scripts/build_site_data.py` (EPIC F.1) — peut télécharger le dataset HF public ;
- `npm ci && npm run build` dans `platform/site` ;
- **déploiement** : Cloudflare Pages (action officielle + `CLOUDFLARE_API_TOKEN` en secret)
  **ou** GitHub Pages (`actions/deploy-pages`).
**CA G.3** : déploiement automatique sur `main` ; site en ligne reproductible.

---

## G.4 `release.yml` — publication versionnée (HF + Zenodo)
Déclencheur : `push` de tag `v*.*.*`.
Étapes :
- build tables release (`scripts/build_release_tables.py`, EPIC E.1) + checksums ;
- `python scripts/export_hf_dataset.py` (secret `HF_TOKEN`) → push dataset HF ;
- `python scripts/make_zenodo_metadata.py` (cohérence `.zenodo.json`/`CITATION.cff`) ;
- créer la **release GitHub** (`gh release create`) → webhook Zenodo émet le **DOI** ;
  (option) dépôt Zenodo dataset via API + `ZENODO_TOKEN` ;
- ouvrir une PR auto mettant à jour le DOI dans `CITATION.cff`/README/card.
**CA G.4** : une release de test exécute E.1→E.4 de bout en bout ; dataset HF mis à jour ;
DOI obtenu.

---

## G.5 `keepalive.yml` — anti-veille du Space
Déclencheur : `schedule` (cron, ex. toutes les 6 h).
Étape : `curl -fsS https://lexis-mollis-search.hf.space/health` (réveille le Space avant les
heures de visite). Ne jamais en faire un usage abusif.
**CA G.5** : le Space répond après le ping ; le site reste fonctionnel même s'il dormait
(repli MiniSearch).

---

## G.6 Conventions CI
- **Secrets** au niveau org/dépôt (`HF_TOKEN`, `ZENODO_TOKEN`, `CLOUDFLARE_API_TOKEN`) ;
  jamais imprimés (`::add-mask::` si dérivés).
- **Permissions minimales** par workflow (`permissions:` au plus juste ; `contents:read`
  par défaut, `pages:write`/`id-token:write` seulement où nécessaire).
- **Pinner** les actions (SHA ou version) ; `concurrency` pour éviter les doublons ;
  `timeout-minutes` raisonnables.
- Tout reste **gratuit** (dépôts publics) ; pas d'auto-hébergement de runner requis.
**CA G.6** : audit des permissions OK ; aucun secret loggé ; actions pinnées.

---

## G.7 Definition of Done (EPIC G)
- [ ] `ci.yml` vert et **requis** pour merger (lint, tests, schémas, gouvernance, CFF).
- [ ] `build-derive.yml` reconstruit similarité + graphe avec cache d'embeddings, artefacts
      publiés.
- [ ] `deploy-site.yml` déploie le site Astro automatiquement.
- [ ] `release.yml` : tag `v*` → tables → push HF → DOI Zenodo → MAJ des liens.
- [ ] `keepalive.yml` maintient le Space joignable ; dégradation gracieuse sinon.
- [ ] Secrets sécurisés, permissions minimales, actions pinnées, tout gratuit/public.

> **Suite :** EPIC H — connecteurs d'expansion du corpus (EUR-Lex → OCDE/OIT/OMS/OMC →
> ECOLEX → AGNU), qui alimentent le même pipeline et les mêmes schémas.
