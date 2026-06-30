# EPIC C — Module de similarité `pdfkb/similarity/` (spec détaillée)

> Déclinaison exécutable de l'EPIC C. Construit, à partir de la couche `clean`/`kb`, une
> **double similarité** : lexicale (MinHash/LSH, robuste au bruit OCR) et sémantique
> (embeddings **LaBSE** + FAISS), fusionnées et **pondérées par la qualité OCR**, puis
> agrégées en arêtes de similarité + clusters. Réalisable **dès maintenant sur les 1 309
> documents complets**. Référence conceptuelle : `metadata_design/SIMILARITY_DESIGN.md`.
> Contrats de données : `chunk.schema.json`, `edge.schema.json` (EPIC B). **DoD en §C.10.**

Garde-fous : aucune écriture dans `raw/` ; propagation de `quality_score`,
`review_required`, `review_priority` jusqu'aux chunks et aux arêtes (`provisional`) ;
déterminisme (seeds fixés, identifiants stables via `pdfkb/ids.py`).

---

## C.0 Structure du module
```
pdfkb/similarity/
  __init__.py
  config.py       # dataclass SimilarityConfig (modèle, seuils, poids, tokens)
  chunking.py     # pages -> chunks
  embeddings.py   # chunks -> vecteurs (cache par text_sha256)
  lexical.py      # MinHash + LSH -> paires candidates
  index.py        # FAISS build/query
  pairs.py        # fusion lexical+sémantique, seuils, pondération qualité -> edges
  graph.py        # agrégation document + clusters
  run.py          # orchestration `build`
```
Entrée canonique : `outputs_v2/kb/pages.jsonl` (régénérée par `pdfkb audit --light`).
Sorties : `outputs_v2/similarity/`.

---

## C.1 Configuration — `config.py`
```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class SimilarityConfig:
    model: str = "sentence-transformers/LaBSE"
    fallback_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    target_tokens: int = 384
    overlap_tokens: int = 64
    minhash_perm: int = 128
    char_ngram: int = 5
    lsh_threshold: float = 0.5      # seuil LSH (rappel lexical)
    knn: int = 20                   # voisins sémantiques par chunk
    w_lexical: float = 0.5
    w_semantic: float = 0.5
    # seuils de typage (calibrés en C.9)
    t_duplicate: float = 0.90       # jaccard
    t_clause_reuse: float = 0.60    # jaccard
    t_translation: float = 0.80     # cosine
    t_weak_link: float = 0.70       # cosine
    faiss_ivf_threshold: int = 500_000  # bascule IndexFlatIP -> IVFPQ
    seed: int = 20260701
    batch_size: int = 64
```
Tout paramètre est surchargé en CLI ; la config effective est écrite dans
`outputs_v2/similarity/run_config.json` (auditabilité).

---

## C.2 Chunking — `chunking.py`
**Objectif** : segmenter le texte propre par page en chunks de taille contrôlée, sans
franchir les frontières de page.
```python
def chunk_pages(pages: Iterable[dict], cfg: SimilarityConfig, tokenizer) -> Iterator[dict]:
    """Yield chunk dicts conformes à chunk.schema.json."""
```
Règles :
- Tokeniser avec le tokenizer du modèle d'embedding (`AutoTokenizer.from_pretrained(cfg.model)`).
- Fenêtres glissantes de `target_tokens` avec recouvrement `overlap_tokens`, **bornées à la
  page** ; une page courte = 1 chunk.
- `chunk_id = ids.chunk_id(source_sha256, page_number, chunk_index)` ;
  `text_sha256 = ids.text_sha256(text)`.
- `char_start/char_end` = offsets dans le texte de page (re-décodage des tokens).
- Propager : `document_id, source_filename, title, treaty_id, year, doc_type, language,
  script, quality_score, review_required, review_priority`.
- `tags` : reprendre les tags page utiles (`language:*`, `script:*`, `quality:*`,
  `review:*`).
**Livrable** : `outputs_v2/similarity/chunks.parquet` (colonnes = champs `chunk.schema.json`).
**CA C.2** : chaque ligne valide `chunk.schema.json` ; `#chunks ≥ #pages non vides` ;
idempotent (mêmes `chunk_id`/`text_sha256` à relance) ; aucun chunk ne chevauche deux pages.

---

## C.3 Embeddings — `embeddings.py`
**Objectif** : vecteurs denses L2-normalisés, avec cache pour ne jamais ré-encoder l'inchangé.
```python
def embed_chunks(chunks_pq: Path, cfg: SimilarityConfig, out_dir: Path) -> EmbeddingStore:
    """Charge le cache, encode les nouveaux text_sha256, écrit embeddings.npy + index."""
```
Détails :
- Modèle via `sentence_transformers.SentenceTransformer(cfg.model)`. Repli automatique sur
  `cfg.fallback_model` si chargement échoue (journaliser lequel est utilisé).
- **Cache** : `embeddings_cache.parquet` mappant `text_sha256 -> row_index` ; n'encoder que
  les `text_sha256` absents. `normalize_embeddings=True`.
- `encode(..., batch_size=cfg.batch_size, show_progress_bar=True)`.
- Renseigner `embedding_model`, `embedding_created_at` (UTC ISO) dans `chunks.parquet`.
**Livrables** : `embeddings.npy` (float32, `[N, dim]`), `embeddings_index.parquet`
(`row_index, chunk_id, text_sha256`).
**CA C.3** : `len(embeddings) == #chunks uniques par text_sha256` ; ‖v‖≈1 (tol 1e-3) ;
relance sans changement ⇒ 0 ré-encodage ; `embedding_model` renseigné.

> Coût : LaBSE = 768 dim. Sur CPU, encoder par lots ; en CI, mettre le cache en *artifact*
> pour réutilisation (EPIC G.2). Aucune API payante.

---

## C.4 Similarité lexicale — `lexical.py`
**Objectif** : détecter réutilisations quasi littérales malgré le bruit OCR.
```python
def lexical_pairs(chunks_pq: Path, cfg: SimilarityConfig, out_dir: Path) -> Path:
    """MinHash(num_perm) sur n-grammes de caractères -> MinHashLSH -> paires candidates."""
```
Détails :
- Normalisation : `unicodedata.normalize("NFKC", t)`, casefold, garder `[a-z0-9]` (+ espaces
  collapsés). N-grammes de **caractères** `cfg.char_ngram` (n=5) → plus robuste à l'OCR que
  les n-grammes de mots.
- `datasketch.MinHash(num_perm=cfg.minhash_perm)` par chunk ; `MinHashLSH(threshold=
  cfg.lsh_threshold, num_perm=...)`. Interroger chaque signature pour récupérer ses voisins.
- Estimer le Jaccard via `m_a.jaccard(m_b)`.
- Émettre les paires `(chunk_a, chunk_b, jaccard_est)` avec `chunk_a < chunk_b` (ordre stable).
**Livrable** : `lexical_pairs.parquet` (`src, dst, jaccard`).
**CA C.4** : doublons exacts ⇒ jaccard≈1 ; complexité sous-quadratique (pas de produit
cartésien) ; déterministe (seed MinHash fixé).

---

## C.5 Index sémantique — `index.py`
**Objectif** : recherche kNN rapide sur les embeddings.
```python
def build_index(embeddings_npy: Path, cfg, out_dir: Path) -> Path: ...
def query_knn(index_path: Path, vectors, k: int) -> tuple[ids, scores]: ...
```
Détails :
- Vecteurs L2-normalisés ⇒ produit scalaire = cosinus. `faiss.IndexFlatIP(dim)` par défaut ;
  si `N > faiss_ivf_threshold`, `IndexIVFPQ` (entraîné, `nlist≈sqrt(N)`, `m=…`, `nbits=8`)
  pour tenir en RAM (palier HF gratuit).
- Persister `faiss.index` + `id_map.parquet` (`row_index -> chunk_id`).
- kNN : pour chaque chunk, `k = cfg.knn` voisins, **exclure soi-même**.
**Livrables** : `faiss.index`, `id_map.parquet`, `semantic_pairs.parquet`
(`src, dst, cosine`, `src < dst`, dédupliquées).
**CA C.5** : top-1 d'un chunk = lui-même (avant exclusion, score≈1) ; sérialisation/relecture
OK ; pas d'auto-arête après exclusion.

---

## C.6 Fusion, seuils, pondération qualité — `pairs.py`
**Objectif** : combiner lexical ∪ sémantique en arêtes typées conformes `edge.schema.json`.
```python
def fuse_pairs(lexical_pq, semantic_pq, chunks_pq, cfg, out_dir) -> Path:
    """Union des paires candidates -> score combiné -> typage -> edges.parquet (level=chunk)."""
```
Logique par paire (a,b) :
- `jaccard` (0 si absente côté lexical), `cosine` (0 si absente côté sémantique) ;
- `combined = cfg.w_lexical*jaccard + cfg.w_semantic*cosine` ;
- `quality_weight = min(q_a, q_b)` ; `provisional = review_required_a or review_required_b` ;
- **typage** (ordre de priorité) :
  - `jaccard ≥ t_duplicate` → `duplicate`
  - `t_clause_reuse ≤ jaccard < t_duplicate` → `clause_reuse`
  - `cosine ≥ t_translation` → `translation` si langues différentes, sinon `semantic_kin`
  - `t_weak_link ≤ cosine < t_translation` → `weak_link`
  - sinon : rejeter la paire.
- `level="chunk"`, `pipeline_version`, écrire `lexical/semantic/combined/quality_weight/
  provisional/method`.
**Livrable** : `edges.parquet` (chunk-level) valide `edge.schema.json`.
**CA C.6** : aucune auto-arête ; une arête par paire non ordonnée ; tous les champs qualité
présents ; 100 % des lignes valident le schéma.

---

## C.7 Agrégation document & clusters — `graph.py`
**Objectif** : passer du niveau chunk au niveau document et détecter les familles.
```python
def document_edges(chunk_edges_pq, chunks_pq, cfg, out_dir) -> Path: ...
def cluster_documents(doc_edges_pq, cfg, out_dir) -> Path: ...
```
Détails :
- Agrégation chunk→document : pour chaque paire de documents, retenir le **meilleur**
  `combined` (et compter le nombre de paires de chunks au-dessus du seuil = robustesse).
  Pondérer par qualité (moyenne des `quality_weight`). Marquer `provisional` si l'évidence
  ne repose que sur des chunks `provisional`.
- Typage document : hériter du type d'arête chunk dominant (`same_instrument_as`/`translation`
  si fort cosinus inter-langue + recouvrement élevé ; `similar_to` sinon).
- Clusters : `networkx.Graph` pondéré (poids = combined) ; communautés via
  `community.louvain_communities` (ou Leiden) avec `seed=cfg.seed`.
**Livrables** : `doc_edges.parquet` (level=document, `edge.schema.json`), `clusters.json`
(`cluster_id`, membres `document_id`, méthode, params), `summary.json`
(compteurs par type, #clusters, taille médiane, % provisional).
**CA C.7** : clustering déterministe (seed) ; `doc_edges` valide le schéma ; `summary.json`
écrit.

---

## C.8 Orchestration & CLI — `run.py` + `pdfkb/cli.py`
```python
# pdfkb/similarity/run.py
def build(kb: Path, output: Path, cfg: SimilarityConfig) -> dict:
    # 1. tokenizer = AutoTokenizer.from_pretrained(cfg.model)
    # 2. chunk_pages -> chunks.parquet
    # 3. embed_chunks -> embeddings.npy (+ cache)
    # 4. lexical_pairs -> lexical_pairs.parquet
    # 5. build_index + knn -> semantic_pairs.parquet
    # 6. fuse_pairs -> edges.parquet (chunk)
    # 7. document_edges + cluster_documents -> doc_edges.parquet, clusters.json
    # 8. écrire run_config.json + manifeste compteurs
    return manifest
```
CLI (subparser conforme au motif `pdfkb/cli.py`, cf. annexe du `BUILD_PLAYBOOK.md`) :
```bash
.venv/bin/python -m pdfkb similarity build \
  --kb outputs_v2/kb/pages.jsonl \
  --output outputs_v2/similarity \
  --model sentence-transformers/LaBSE \
  --target-tokens 384 --overlap 64
```
**CA C.8** : commande exécutable de bout en bout sur les 1 309 docs ; tous les livrables
C.2–C.7 produits ; journal JSON final (compteurs) imprimé comme les autres commandes.

---

## C.9 Calibration des seuils — `benchmarks/similarity_cases.json`
Constituer un petit **jeu de validation annoté** (≥ 30 paires positives / 30 négatives) :
- positives connues : versions multilingues d'un même traité (FR/EN), protocoles amendant un
  traité, clauses réutilisées ;
- négatives : documents thématiquement proches mais non liés.
Script `scripts/calibrate_similarity.py` : balaye les seuils (`t_duplicate`, `t_clause_reuse`,
`t_translation`, `t_weak_link`) et `w_lexical/w_semantic`, calcule **précision/rappel/F1 par
type**, écrit `outputs_v2/similarity/calibration_report.json` et propose les seuils retenus.
Reporter les valeurs choisies dans `config.py` et `SIMILARITY_DESIGN.md`.
**CA C.9** : rapport produit ; seuils par défaut justifiés par les mesures (pas arbitraires).

---

## C.10 Tests & Definition of Done
`tests/test_similarity.py` :
- chunking déterministe + bornage page ;
- normalisation lexicale (accents, casse, ponctuation) ;
- MinHash : Jaccard≈1 sur textes identiques, faible sur textes disjoints ;
- FAISS round-trip (build→save→load→query) ;
- typage des seuils (paires synthétiques → bon `type`) ;
- conformité schéma d'un échantillon `edges.parquet`.

**DoD (EPIC C)** :
- [ ] `pdfkb similarity build` tourne sur les 1 309 docs et produit chunks/embeddings/edges/
      doc_edges/clusters/summary.
- [ ] `chunks.parquet` ↔ `chunk.schema.json`, `edges.parquet`/`doc_edges.parquet` ↔
      `edge.schema.json` (100 % valides).
- [ ] Embeddings L2-normalisés + cache fonctionnel (relance = 0 ré-encodage).
- [ ] Qualité propagée (`quality_weight`, `provisional`) sur toutes les arêtes.
- [ ] Déterminisme (seeds) ; `run_config.json` écrit ; tests verts.
- [ ] Seuils calibrés sur le jeu annoté ; rapport présent.
- [ ] Aucune écriture dans `raw/` ; aucune correction de texte.

> **Suite :** EPIC D — knowledge graph (`pdfkb/graph/`), qui importe `edges.parquet`
> (`similar_to`) et y ajoute entités et relations typées.
