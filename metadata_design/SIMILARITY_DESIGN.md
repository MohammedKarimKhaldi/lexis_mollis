# Couche d'analyse de similarité — conception et plan d'implémentation

Document de travail (Mohammed-Karim Khaldi, Reda Rostane). Complément concret à la
section « Couche d'analyse de similarité documentaire » de
`scientific_methods_full.tex`. Objectif : identifier les similitudes entre traités
(réutilisations de clauses, filiations textuelles, versions multilingues, familles
diplomatiques) à partir de la couche `clean/`, sans jamais modifier le texte source.

## Principe : double similarité

Deux signaux complémentaires, calculés séparément puis combinés :

- **Lexical** — empreintes de n-grammes de caractères (MinHash + LSH). Robuste au bruit
  OCR, détecte les réutilisations quasi littérales et les doublons. Bon marché.
- **Sémantique** — embeddings denses multilingues + distance cosinus. Relie des
  formulations différentes et des traductions d'un même contenu. Plus coûteux.

Le score combiné pondère chaque arête par la qualité OCR des pages impliquées
(`quality_score`, `review_required`), pour ne pas tirer de conclusions sur du texte
incertain.

## Pipeline (étapes)

1. **Source** : lire `outputs_v2/kb/pages.jsonl` (un enregistrement par page, déjà
   nettoyé). Filtrer/annoter les pages `review_required=true` mais ne pas les exclure.
2. **Segmentation** : chunks de ~256–512 tokens, recouvrement ~15 %, sans franchir les
   frontières de page. Conserver `document_id`, `source_sha256`, `page_number`,
   `chunk_index`, offsets caractères.
3. **Empreintes lexicales** : n-grammes de caractères (n=5), MinHash (~128 permutations),
   index LSH par bandes. Sortie : paires candidates avec Jaccard estimé.
4. **Embeddings** : encoder chaque chunk avec un modèle multilingue local
   (cf. choix ci-dessous). Normalisation L2.
5. **Index sémantique** : FAISS (`IndexFlatIP` pour démarrer, puis `IVF`/`HNSW` si le
   volume l'exige). Recherche kNN (k≈20) par chunk.
6. **Fusion** : pour chaque paire candidate (lexicale ∪ sémantique), score combiné
   `s = w_l·jaccard + w_s·cosine`, pondéré par qualité OCR. Seuils distincts par type de
   relation (cf. ci-dessous).
7. **Graphe** : nœuds = documents et/ou chunks ; arêtes pondérées. Agrégation
   chunk→document (max ou moyenne pondérée des meilleures paires).
8. **Familles** : composantes connexes + clustering communautaire (Louvain/Leiden) sur le
   graphe document-document.
9. **Exports** : `similarity/edges.parquet` (paires + scores + type), `clusters.json`,
   et un graphe sérialisé pour exploration.

## Choix techniques (tous locaux / open-source)

| Composant | Choix de départ | Notes |
|---|---|---|
| Segmentation | tokenizer du modèle d'embedding | respecter les frontières de page |
| Embeddings | `sentence-transformers` multilingue (ex. `paraphrase-multilingual-mpnet-base-v2` ou `LaBSE`) | local, multilingue ; LaBSE fort pour l'alignement de traductions |
| Index sémantique | FAISS | cosinus via produit scalaire sur vecteurs L2-normalisés |
| Index lexical | `datasketch` (MinHashLSH) | n=5 caractères, robuste OCR |
| Graphe / clustering | `networkx` + `python-louvain` (ou `igraph`/`leidenalg`) | |
| Stockage | Parquet + SQLite | réutiliser le pattern « SQLite = source de vérité » |

Le latin historique étant mal océrisé (cf. limites), prévoir une variante d'embedding ou
un repli purement lexical pour les périodes anciennes, et toujours pondérer par la qualité.

## Seuils indicatifs (à calibrer)

| Type de relation | Signal dominant | Seuil indicatif |
|---|---|---|
| Doublon / quasi-identique | Jaccard lexical | ≥ 0,9 |
| Réutilisation de clause | Jaccard lexical | 0,6–0,9 |
| Parenté sémantique / traduction | cosinus | ≥ 0,80 |
| Lien faible (à explorer) | cosinus | 0,70–0,80 |

À fixer sur un jeu de validation annoté manuellement (quelques dizaines de paires
positives/négatives).

## Schéma de données ajouté

- **chunk** : `chunk_id`, `document_id`, `source_sha256`, `page_number`, `chunk_index`,
  `text`, `n_tokens`, `quality_score`, `review_required`, `embedding_ref`.
- **edge** : `src`, `dst` (chunk ou document), `type`, `lexical`, `semantic`, `combined`,
  `quality_weight`, `provisional` (true si une page à réviser est impliquée).
- **cluster** : `cluster_id`, membres, méthode, paramètres.

Cohérent avec `metadata_design/chunk.schema.json` — étendre ce schéma plutôt que d'en
créer un nouveau.

## Validation

- Petit jeu annoté de paires connues (versions multilingues d'un même traité, clauses
  réutilisées) → précision/rappel par type de relation.
- Contrôle des faux positifs dus au bruit OCR (vérifier que `provisional` les capture).
- Stabilité du clustering sous variation de seuils.

## Étapes d'implémentation suggérées

1. Module `pdfkb/similarity/` (chunking, embeddings, lexical, index, graphe, export).
2. CLI : `python -m pdfkb similarity build --kb outputs_v2/kb/pages.jsonl --output outputs_v2/similarity`.
3. Démarrer sur un sous-corpus complet (ex. les 1 309 documents déjà finis) pour calibrer
   avant de lancer sur l'ensemble.
4. Publier graphe + clusters dans `kb_repository/` (Forgejo) avec mention des droits
   d'auteur et du statut open-source.

## Droits d'auteur

Les relations et le graphe sont des données dérivées ; conserver la mention
« Mohammed-Karim Khaldi, Reda Rostane » et le statut de droits (`rights_status`) au niveau
document, comme pour la couche texte. Les droits de diffusion des sources restent à établir
indépendamment.
