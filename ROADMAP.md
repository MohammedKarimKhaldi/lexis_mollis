# Feuille de route — Base ouverte mondiale de droit souple

**Auteurs / droits :** Mohammed-Karim Khaldi, Reda Rostane
**Statut :** plan de travail — conçu pour avancer **en parallèle de l'OCR** ; état opérationnel suivi dans [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
**Vision :** constituer la plus grande base de données ouverte au monde de *droit souple*
(traités, déclarations, résolutions, recommandations, codes de conduite, lignes
directrices…), entièrement **en ligne, accessible, open source et gratuite**, avec
recherche plein texte + sémantique (knowledge base), graphe de connaissances (knowledge
graph) et détection de similitudes.

> Principe directeur : **tout repose sur des briques gratuites et modernes**, sans
> dépendance payante. Quand une offre gérée a une limite de palier gratuit, on prévoit
> toujours un repli auto-hébergé statique (aucun coût, aucune limite imposée par un
> fournisseur).

---

## 1. Ce qui peut avancer MAINTENANT (sans attendre la fin de l'OCR)

L'OCR produit du texte ; tout le reste peut être bâti et testé sur les **1 309 documents
déjà complets** puis simplement relancé sur le corpus entier. Huit chantiers parallèles :

| # | Chantier | Dépend de l'OCR ? | Démarrable |
|---|----------|-------------------|-----------|
| A | Infrastructure & gouvernance (dépôts, licences, comptes) | Non | Immédiat |
| B | Modèle de données & standards (schémas, ontologie, identifiants) | Non | Immédiat |
| C | Stratégie d'expansion du corpus (sources de droit souple, ingestion) | Non | Immédiat |
| D | Pipeline embeddings + similarité | Sur sous-corpus | Immédiat |
| E | Construction du knowledge graph | Sur sous-corpus | Immédiat |
| F | Plateforme web (site + recherche + graphe) | Données d'exemple | Immédiat |
| G | Automatisation CI/CD | Non | Après A |
| H | Outils de révision & contribution communautaire | Non | Après B |

Quand l'OCR se termine, aucun de ces chantiers n'est à refaire : on **réexécute les
pipelines** sur l'ensemble complet.

---

## 2. Stack technique recommandée — 100 % gratuite

| Couche | Choix recommandé | Pourquoi / palier gratuit | Repli gratuit |
|--------|------------------|---------------------------|---------------|
| Code & orchestration | **GitHub** (organisation publique) | Dépôts publics illimités ; **GitHub Actions gratuit et illimité pour le public** | GitLab / Codeberg (Forgejo) |
| CI/CD | **GitHub Actions** | Nettoyage → embeddings → index → graphe → déploiement automatisés | Forgejo Actions |
| Corpus texte & données dérivées | **Hugging Face Datasets** | **1 To gratuit** pour datasets publics, versionné (git), format Parquet, *dataset viewer* intégré | Zenodo + Git LFS |
| Versions citables (DOI) | **Zenodo** | DOI persistant, 50 Go/enregistrement (extensible à 150 Go), idéal citation académique | OSF |
| PDF sources (volumineux) | **Internet Archive** et/ou HF | Pas de limite stricte, conservation pérenne ; respecter les droits | HF Datasets |
| Embeddings | **sentence-transformers** local (LaBSE ou `paraphrase-multilingual-mpnet`) | Multilingue, exécuté gratuitement (CI ou poste local), fort pour aligner traductions | `bge-m3` |
| Recherche sémantique (service) | **Hugging Face Space** (FAISS + API) | CPU gratuit 2 vCPU / 16 Go ; index FAISS embarqué = pas de limite de fournisseur (le Space s'endort après 48 h d'inactivité) | Qdrant Cloud (1 Go gratuit à vie) / Supabase pgvector (500 Mo) |
| Recherche lexicale / hybride | **BM25** (Tantivy/Lyra) + **MinHash/LSH** (`datasketch`) | Robuste au bruit OCR, détecte quasi-doublons | MiniSearch (client) |
| Knowledge graph (construction) | **Python** `rdflib` + `networkx` | RDF (Turtle/JSON-LD) **et** graphe de propriétés (Parquet) | — |
| Knowledge graph (exploration) | **Sigma.js / Cytoscape.js** rendu statique sur le site | 100 % gratuit, aucun serveur ; graphe précalculé | Quartz (vue graphe intégrée) |
| Knowledge graph (requêtes) | **Oxigraph** (SPARQL) dans un HF Space | Triplestore open source, endpoint SPARQL gratuit | Wikibase Cloud / Neo4j Aura Free |
| Site public / KB | **Quartz** ou **Astro** sur **Cloudflare Pages** | Quartz : style « second cerveau » (vue graphe, rétroliens, recherche) ; Cloudflare Pages : **bande passante illimitée gratuite** | GitHub Pages / Netlify / Vercel |

**Identifiants & interopérabilité :** réutiliser les identifiants **Wikidata** pour les
États, organisations et personnes ; exposer en **JSON-LD / schema.org** pour le
référencement et l'interopérabilité.

---

## 3. Architecture cible (vue d'ensemble)

```
            SOURCES (PDF, portails de droit souple)
                         │
                         ▼
   ┌─────────────────────────────────────────────┐
   │  pdfkb  (OCR fidèle + nettoyage déterministe) │  ← en cours
   └─────────────────────────────────────────────┘
                         │  outputs_v2/kb/pages.jsonl + clean/*.md
        ┌────────────────┼─────────────────────────┐
        ▼                ▼                          ▼
  Chunking +        Extraction d'entités       Empreintes lexicales
  embeddings        (États, dates, orgs…)      (MinHash/LSH)
        │                │                          │
        ▼                ▼                          ▼
   Index FAISS      Knowledge graph (RDF +     Graphe de similarité
   (sémantique)     property graph)            (clauses, traductions)
        └────────────────┼──────────────────────────┘
                         ▼
        PUBLICATION : Hugging Face Datasets + Zenodo (DOI)
                         │
                         ▼
   SITE PUBLIC (Cloudflare Pages) :
     • recherche plein texte + sémantique (HF Space)
     • exploration du knowledge graph (Sigma.js + SPARQL Oxigraph)
     • fiches documents, similarités, familles, sources citées
```

---

## 4. Détail des chantiers

### A. Infrastructure & gouvernance
- Créer une **organisation GitHub publique** (ex. `softlaw-open` / `droit-souple`).
- Dépôts : `pipeline` (pdfkb), `corpus-data` (miroir / sous-modules), `platform` (site web),
  `knowledge-graph`.
- Créer une **organisation Hugging Face** (datasets + Spaces).
- Compte **Zenodo** lié à GitHub (release → DOI automatique).
- **Licences :** code en **Apache-2.0** (ou MIT) ; données en **CC-BY-4.0** (attribution
  Khaldi & Rostane) — les textes officiels sous-jacents relèvent souvent du domaine public,
  mais la *curation, l'OCR, les métadonnées, le graphe et les similarités* constituent
  l'œuvre dérivée protégée. Ajouter `LICENSE`, `LICENSE-DATA`, `CITATION.cff`,
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`.
- **Provenance & droits :** champ `rights_status` par document (déjà prévu), traçabilité
  source → URL → empreinte.

### B. Modèle de données & standards
- Finaliser les schémas de `metadata_design/` (document, page, chunk, review_event, tags).
- Définir l'**ontologie du knowledge graph** (voir §5).
- Stabiliser les **identifiants** : `document_id`, `source_sha256`, `treaty_id`, +
  alignement Wikidata pour entités.
- Geler la **taxonomie de tags** (`namespace:value`) : `doc_type`, `period`, `century`,
  `language`, `script`, `quality`, `review`, `rights_status`, et nouveaux : `instrument_type`
  (déclaration, résolution, recommandation, code…), `issuing_body`, `legal_force`.

### C. Stratégie d'expansion du corpus (« la plus grande au monde »)
Objectif : dépasser les seuls traités pour couvrir tout le droit souple. Cartographier et
ingérer progressivement des **sources ouvertes** :
- **ECOLEX** (FAO/IUCN/UNEP) — droit souple environnemental, guidances non contraignantes.
- **Résolutions et déclarations de l'AGNU**, documents des conférences internationales.
- **OCDE, OIT, OMS, OMC** — recommandations, lignes directrices, codes de conduite.
- **UE** : communications, recommandations, avis (soft law) via EUR-Lex.
- **Refworld / HCR**, organes de traités des droits de l'homme.
- Construire des **connecteurs d'ingestion** standardisés (un module par source) →
  inventaire → OCR/extraction → mêmes schémas.
- **Déduplication** inter-sources via SHA-256 + MinHash (le pipeline le fait déjà au niveau
  page).
- **Respect des droits/robots** : ne récolter que ce qui est librement diffusable ;
  conserver l'URL source et le statut de droits.

### D. Pipeline embeddings + similarité
- Implémenter selon `metadata_design/SIMILARITY_DESIGN.md` : chunking → embeddings (FAISS)
  + MinHash/LSH → fusion pondérée par la qualité OCR → graphe de similarité → familles.
- **Démarrer dès maintenant sur les 1 309 documents complets** pour calibrer les seuils.
- Module `pdfkb/similarity/`, CLI `python -m pdfkb similarity build`.

### E. Knowledge graph
- Voir l'ontologie §5. Extraction d'entités (États, organisations, dates, lieux, personnes,
  thèmes) + relations (partie à, signé le, amende, abroge, référence, traduction de,
  similaire à, cite).
- Sorties : **RDF** (`graph.ttl`, JSON-LD) **et** `nodes.parquet` / `edges.parquet`.
- Liens de similarité (chantier D) injectés comme arêtes `similar_to` pondérées.

### F. Plateforme web
- Site statique (Quartz ou Astro) sur **Cloudflare Pages**.
- **Recherche** : HF Space (FastAPI/Gradio) servant FAISS + BM25 (hybride).
- **Graphe** : vue interactive Sigma.js/Cytoscape (données précalculées) + endpoint SPARQL
  Oxigraph optionnel.
- **Fiche document** : texte propre, métadonnées, sources, documents similaires, position
  dans le graphe, lien PDF d'origine, statut de révision.
- **Accessibilité** : multilingue, responsive, export des données (JSONL/Parquet/RDF).

### G. Automatisation CI/CD
- GitHub Actions :
  1. à chaque push sur les données nettoyées → re-chunk + ré-embed incrémental → rebuild
     index/graphe → déploiement du site ;
  2. sur tag de version → **push dataset HF** + **release Zenodo (DOI)**.
- Tout gratuit pour dépôts publics.

### H. Révision & communauté
- Exploiter `review_queue.csv` : petite interface de validation (issues GitHub, ou page
  statique + formulaire) pour traiter en priorité les pages `high`.
- `CONTRIBUTING.md` : comment ajouter une source, corriger une transcription, signaler une
  relation. Modèle de gouvernance ouverte.

---

## 5. Ontologie du knowledge graph (esquisse)

**Entités (nœuds) :**
`Document` · `Instrument` (traité, déclaration, résolution, recommandation, code…) ·
`State`/`Party` · `Organization` · `Person` · `Place` · `Date` · `Topic` · `Clause`.

**Relations (arêtes) :**
`party_to` · `issued_by` · `signed_at` (lieu) · `dated` · `amends` · `supersedes` ·
`references` / `cites` · `translation_of` · `same_instrument_as` · `similar_to` (pondérée) ·
`about_topic`.

**Alignements externes :** `owl:sameAs` vers Wikidata (États, organisations, personnes) ;
vocabulaire **schema.org/Legislation** + **FRBR** (œuvre / expression / manifestation) pour
distinguer un instrument de ses versions linguistiques et de ses scans.

---

## 6. Phases & jalons

**Phase 0 — Fondations (semaine 1)**
Orgs GitHub + HF + Zenodo, licences, squelette des dépôts, gel du modèle de données,
décisions de stack confirmées.

**Phase 1 — Tranche verticale MVP (semaines 2–4)** *sur les 1 309 docs déjà complets*
Dataset publié sur HF ; embeddings + index FAISS ; HF Space de recherche ; site statique
minimal ; premier graphe (entités + similarités basiques) ; CI de base. → **Démo
end-to-end en ligne.**

**Phase 2 — Profondeur & passage à l'échelle (semaines 4–8)**
Modules pipeline finalisés (similarité, KG) ; ontologie complète + liage Wikidata ;
calibration des seuils ; site public v1 (recherche hybride + graphe interactif + fiches) ;
premiers connecteurs d'expansion de corpus.

**Phase 3 — Corpus complet & lancement (après fin OCR)**
Réexécution sur l'ensemble ; release Zenodo (DOI) ; communiqué / page d'accueil ;
publication open source complète.

**Phase 4 — Croissance continue (en continu)**
Ingestion progressive des sources de droit souple (chantier C) ; contributions
communautaires ; objectif « plus grande base au monde ».

---

## 7. Limites des paliers gratuits & parades

- **HF Space CPU gratuit** s'endort après 48 h sans visite et est limité en RAM : garder
  l'index FAISS compact (quantification `IndexIVFPQ`), ou réveiller via un ping CI
  programmé. Repli : recherche client-side sur sous-index.
- **Qdrant/Supabase gratuits** (1 Go / 500 Mo) ne tiennent pas des millions de vecteurs :
  les réserver à une recherche filtrée légère ; l'index FAISS embarqué reste la voie sans
  limite de fournisseur.
- **GitHub Actions** : gratuit/illimité **uniquement pour dépôts publics** — garder les
  dépôts publics.
- **Zenodo** : 50 Go/enregistrement par défaut ; scinder les gros dumps, demander une
  extension si besoin. Les **PDF volumineux → Internet Archive**.
- **Embeddings** : calculer par lots en CI ou en local pour rester gratuit (pas d'API
  payante) ; mettre en cache les vecteurs (versionnés sur HF).

---

## 8. Décisions arrêtées

- **Nom / handles :** « Lexis Mollis » — `github.com/lexis-mollis`, `hf.co/lexis-mollis`.
- **Licence données :** **CC-BY-4.0** (attribution Khaldi & Rostane). Code : Apache-2.0.
- **Site :** **Astro** (UI sur-mesure) ; vue graphe via **Sigma.js**.
- **Embeddings :** **LaBSE** (alignement inter-langues) ; repli `paraphrase-multilingual-mpnet`.
- **Expansion du corpus (ordre) :** EUR-Lex → OCDE/OIT/OMS/OMC → ECOLEX → AGNU.

---

## 9. À faire cette semaine (amorce concrète)

1. Créer l'organisation GitHub publique + les 4 dépôts et y déposer `pdfkb` et `metadata_design`.
2. Ajouter `LICENSE` (Apache-2.0), `LICENSE-DATA` (CC-BY-4.0), `CITATION.cff` (Khaldi, Rostane).
3. Créer l'organisation Hugging Face et y pousser un **dataset des 1 309 documents complets**
   (clean + pages.jsonl en Parquet).
4. Démarrer le module `pdfkb/similarity/` sur ce sous-corpus (chantier D) pour calibrer.
5. Monter un **HF Space** minimal de recherche sémantique (FAISS) sur ce dataset → première
   mise en ligne.

---

### Sources (offres et outils, juin 2026)
- Hugging Face — paliers Spaces & stockage datasets : <https://huggingface.co/pricing>, <https://huggingface.co/docs/hub/en/storage-limits>
- Comparatif bases vectorielles (Qdrant 1 Go gratuit, pgvector/Supabase) : <https://www.datacamp.com/blog/the-top-5-vector-databases>
- Quartz (site statique, vue graphe) : <https://quartz.jzhao.xyz/>
- Zenodo — quotas : <https://help.zenodo.org/docs/deposit/manage-quota/>
- Internet Archive — limites d'upload : <https://help.archive.org/help/uploading-tips/>
- ECOLEX (source de droit souple) : <https://www.ecolex.org/>
