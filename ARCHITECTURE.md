# Architecture de Lexis Mollis

État de référence : 9 août 2026.

## Principes

- **Fidélité** : la transcription brute ne reçoit aucune correction générative.
- **Auditabilité** : chaque dérivé conserve sa source, sa méthode, sa version de pipeline et ses indicateurs de qualité.
- **Déterminisme** : les identifiants, seeds et paramètres sont stables et enregistrés dans les manifests.
- **Droits** : `rights_status` est conservé et n'est jamais inféré.
- **Publication légère** : les artefacts complets sont publiés comme dataset ; le site embarque une projection JSON optimisée.

## Flux de données

```text
PDF + métadonnées
      │
      ▼
pdfkb OCR ──► SQLite (source de vérité locale)
      │
      ├──► raw / clean / pages JSONL / audit / review queue
      │
      ├──► chunks + embeddings + FAISS + similarités
      │
      ├──► entités + relations + RDF/JSON-LD + graphe Sigma
      │                                      └──► ContextGraph + API Semantica
      │                                                    │
      │                                                    ▼
      │                                      UI Astro légère et francophone
      │
      └──► release Parquet ──► Hugging Face / Zenodo
                                │
                                └──► JSON statique ──► Astro + Cloudflare Worker
```

`metadata/pipeline.sqlite3` est la source de vérité technique locale. Les fichiers sous
`outputs_v2/` sont reconstruisibles et restent hors Git. Les données optimisées sous
`platform/site/public/data/` sont versionnées pour rendre le déploiement statique reproductible.
`graph.communities.json` projette les communautés Louvain déjà calculées par le pipeline de
similarité ; la vue les espace et les colore sans recalcul coûteux dans le navigateur.

## Composants

| Composant | Responsabilité | Interfaces principales |
|---|---|---|
| `pdfkb/` | inventaire, OCR, nettoyage, qualité, état et export | CLI `pdfkb run/audit/status/benchmark` |
| `pdfkb/similarity/` | chunking, MinHash, embeddings, FAISS, arêtes et clusters | CLI `pdfkb similarity build` |
| `pdfkb/graph/` | extraction conservatrice, résolution, RDF et graphe web | CLI `pdfkb graph build` |
| `pdfkb/semantica.py` | adaptation Sigma vers ContextGraph et service API Semantica | CLI `pdfkb semantica export/serve` |
| `metadata_design/` | schémas JSON, taxonomie, ontologie et dictionnaire | validateurs hors ligne |
| `scripts/` | calibration, release et publication | commandes Python explicites |
| `platform/` | données web, site Astro, Worker assistant et services optionnels | site statique, `/api/*`, Spaces |

Le graphe source utilise `rdflib`, `networkx` et des contrats Parquet/JSON. La recherche
sémantique utilise `sentence-transformers` et FAISS. Semantica consomme un export de ce graphe
sans remplacer ces couches. Toutes partagent les identifiants et champs de qualité du pipeline OCR.

## Frontières de stockage

Sont versionnés : code, schémas, ontologie, petits benchmarks, gazetteers et projection JSON
du site. Restent locaux ou sont publiés hors Git : PDF sources, SQLite, OCR complet, Parquet,
embeddings, index FAISS et images de révision.

Les répertoires `legacy/` et `epics/` documentent respectivement les anciens essais OCR et les
spécifications ayant guidé l'implémentation. Ils ne constituent pas la voie de production.

## Couche Semantica

[Semantica 0.6.0](https://github.com/semantica-agi/semantica) est intégré comme dépendance
optionnelle `semantica`. L'adaptateur conserve les identifiants, types, poids, métadonnées et
coordonnées du graphe Sigma, puis laisse le `ContextGraph` officiel valider et sérialiser
l'artefact utilisé par Semantica Knowledge Explorer.

Cette frontière évite de dupliquer l'OCR, FAISS, NetworkX ou les exports RDF : le graphe Lexis
Mollis reste la source déterministe. Semantica apporte son `ContextGraph` et ses API de recherche,
voisinage et provenance derrière l'unique interface Astro. Son Explorer officiel reste accessible
directement pour le diagnostic, mais n'est pas l'interface du produit. Deux artefacts locaux sont
utiles :

- `graph.semantica.json` : graphe complet de 8 441 nœuds et 104 206 arêtes ;
- `graph.semantica.web.json` : projection interactive de 3 000 nœuds et 17 790 arêtes.

Le second est recommandé pour l'interface interactive : il borne le volume initial rendu par le
navigateur, tandis que l'API Semantica enrichit à la demande la recherche et le détail d'un nœud.
Les artefacts restent sous `outputs_v2/` et hors Git. La dépendance n'est importée que par les
commandes `pdfkb semantica`, donc le pipeline OCR de base reste utilisable sans elle.

## Déploiement

Le build Astro génère un site statique servi par Cloudflare Workers Static Assets. Le Worker
`platform/site/worker/ask.ts` ajoute l'assistant et les endpoints de relais sans modifier les
assets statiques. L'assistant répond en français par défaut. Le dataset Hugging Face reste la
publication complète ; le site sert une projection bornée du graphe et utilise Semantica comme
service local optionnel, sans alourdir l'interface publique.
