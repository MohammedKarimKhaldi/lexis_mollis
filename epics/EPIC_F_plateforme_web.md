# EPIC F — Plateforme web `platform/` (spec détaillée)

> Déclinaison exécutable de l'EPIC F. Met le corpus **en ligne, accessible** : site **Astro**
> (vitrine + fiches documents), **service de recherche** plein texte + sémantique (HF Space :
> FAISS + BM25), **exploration du knowledge graph** (Sigma.js + endpoint SPARQL Oxigraph
> optionnel). Hébergement gratuit (Cloudflare Pages / GitHub Pages + HF Spaces). Consomme le
> dataset publié (EPIC E) et `graph.sigma.json` (EPIC D). **DoD en §F.7.**

Décisions appliquées : **Astro**, vue graphe **Sigma.js**, embeddings **LaBSE**.
Garde-fous : afficher la **qualité/révision** des pages ; liens vers sources et licence
visibles ; pas de réécriture du texte.

---

## F.0 Structure du dépôt `platform/`
```
platform/
  site/                     # application Astro (build statique)
    src/pages/              # index, recherche, graphe, fiche [document_id], données&licence
    src/components/         # SearchBox, GraphView (Sigma), DocCard, SimilarList, Filters
    src/lib/                # client API search, chargement data
    public/data/            # données légères buildées (index MiniSearch, sigma.json réduit)
    astro.config.mjs
  spaces/
    search/                 # HF Space (FastAPI) : FAISS + BM25
      app.py  requirements.txt  README.md
    sparql/                 # HF Space (Oxigraph) : endpoint SPARQL (optionnel)
      app.py  requirements.txt  README.md
  scripts/
    build_site_data.py      # dataset HF -> public/data (index client + sigma réduit + fiches)
```

---

## F.1 Préparation des données du site — `scripts/build_site_data.py`
À partir du dataset HF (EPIC E) :
- générer un **index de recherche client** (MiniSearch JSON) sur titres + métadonnées +
  incipit de texte (léger, pour la recherche instantanée hors-ligne) ;
- copier/réduire `graph.sigma.json` (vue Document/Instrument agrégée si trop dense) ;
- pré-rendre les **données de fiche** par document (`public/data/docs/{document_id}.json` :
  métadonnées, tags, texte propre, top-K similaires depuis `edges`, voisinage graphe, lien
  PDF, statut révision) ;
- écrire un `facets.json` (valeurs de filtres : `instrument_type`, `year`, `language`,
  `legal_force`, `source_db`).
**CA F.1** : artefacts présents sous `site/public/data/` ; tailles maîtrisées (index < ~20 Mo) ;
build reproductible.

---

## F.2 Site Astro — `site/`
- **Pages** : accueil (pitch + chiffres + accès) ; `/recherche` (barre + facettes + résultats
  hybrides) ; `/graphe` (Sigma) ; `/document/[document_id]` (fiche) ; `/donnees` (licence
  CC-BY-4.0, attribution Khaldi & Rostane, liens HF/Zenodo/IA, téléchargements
  JSONL/Parquet/RDF) ; `/methode` (rendu de la méthodo / lien PDF).
- **Fiche document** : texte propre paginé, métadonnées + tags, **documents similaires**
  (depuis `edges`), **voisinage graphe** (mini-Sigma), lien PDF source, **bandeau qualité**
  (score, `review_required`, raisons) bien visible.
- **i18n** FR/EN (intl Astro) ; responsive ; thème sobre.
- **Recherche** : MiniSearch côté client par défaut (instantané, gratuit, toujours
  disponible) + bouton « recherche sémantique » appelant le Space (F.4) pour le rappel
  multilingue.
- Déploiement : **Cloudflare Pages** (bande passante illimitée) ou GitHub Pages, build en CI
  (EPIC G.3).
**CA F.2** : site déployé à une URL publique ; navigation document ↔ similaires ↔ graphe ;
bandeau qualité présent ; build reproductible.

---

## F.3 Graphe interactif — `components/GraphView` (Sigma.js)
- Charger `sigma.json` (positions précalculées EPIC D) ; rendu **Sigma.js** (WebGL,
  performant). Fonctions : recherche de nœud, filtres par type d'arête, focus voisinage
  (n-sauts), panneau détail (lien vers fiche), légende par type de nœud/arête.
- Les arêtes `similar_to` affichent leur poids ; les éléments `provisional` sont stylés
  distinctement (pointillé/atténué).
- Repli : si `sigma.json` trop lourd, charger la vue agrégée et offrir le drill-down par
  cluster.
**CA F.3** : graphe fluide (≥ quelques milliers de nœuds) ; clics → fiches ; filtres
opérationnels ; provisional visuellement distingué.

---

## F.4 Service de recherche — `spaces/search/` (HF Space, FastAPI)
- Charger au démarrage : `faiss.index` + `id_map` + métadonnées (depuis le dataset HF) ;
  modèle **LaBSE** pour encoder la requête.
- **Endpoints** :
  - `GET /search?q=&k=&filters=` : encode q (LaBSE) → kNN FAISS **+** BM25 (rang fusionné
    type RRF) → résultats filtrés (`instrument_type`, `year`, `language`, `legal_force`) ;
  - `GET /similar?chunk_id=` ou `?document_id=` : voisins depuis l'index/`edges` ;
  - `GET /health`.
- **Tenir le palier gratuit** (2 vCPU/16 Go) : index **IVFPQ** compact ; charger les
  métadonnées en Parquet/Polars ; le Space **s'endort après 48 h** → ping programmé (CI
  cron, EPIC G) ; le site reste fonctionnel via MiniSearch si le Space dort.
- CORS autorisé pour le domaine du site ; pas de secret nécessaire (données publiques).
**CA F.4** : requêtes FR/EN/multilingue pertinentes ; filtres OK ; `/similar` cohérent avec
`edges` ; latence raisonnable sur le sous-corpus ; dégradation gracieuse si Space endormi.

---

## F.5 Endpoint SPARQL — `spaces/sparql/` (Oxigraph, optionnel)
- Charger `graph.ttl` dans **Oxigraph** ; exposer `/sparql` (lecture seule) + une page
  d'exemples de requêtes (parties d'un instrument, traductions, voisinage thématique).
- Bouton « Télécharger le RDF » (ttl/jsonld) sur le site.
**CA F.5** : quelques requêtes SPARQL d'exemple renvoient des résultats corrects ; dump RDF
téléchargeable.

---

## F.6 Accessibilité & ouverture
- Audit de base : contraste AA, navigation clavier, `alt`/aria, titres de page, responsive.
- Page **Données & licence** complète (CC-BY-4.0, attribution, `rights_status` expliqué,
  liens HF/Zenodo/IA) ; tous les exports téléchargeables (JSONL/Parquet/RDF).
- Mentions auteurs (Khaldi & Rostane) et DOI visibles en pied de page.
**CA F.6** : audit accessibilité de base passé ; exports accessibles ; licence/attribution
visibles partout.

---

## F.7 Definition of Done (EPIC F)
- [ ] Site Astro déployé (URL publique) : accueil, recherche, graphe, fiches, données&licence.
- [ ] Recherche client (MiniSearch) **et** sémantique (Space FAISS+BM25, LaBSE) fonctionnelles ;
      filtres par facettes.
- [ ] Graphe Sigma.js interactif relié aux fiches ; `provisional` distingué.
- [ ] (Option) endpoint SPARQL Oxigraph + téléchargement RDF.
- [ ] Bandeau qualité/révision sur les fiches ; licence CC-BY-4.0 + attribution visibles.
- [ ] Tout gratuit ; dégradation gracieuse si le Space dort ; build reproductible en CI.

> **Suite :** EPIC G — automatisation CI/CD (lint/tests, build des dérivés, déploiement site,
> release HF/Zenodo), qui orchestre A→F.
