# Dictionnaire des données

Version: `0.1-draft`

Ce dictionnaire décrit les champs publiables du corpus OCR. Les noms de champs
sont ceux utilisés dans `kb/pages.jsonl`, les schémas JSON et les futurs index KB.

## 1. Champs documentaires

| Champ | Type | Niveau | Définition |
|---|---|---|---|
| `document_id` | string | document/page/chunk | Identifiant lisible dérivé du nom de fichier sans extension. |
| `source_filename` | string | document/page/chunk | Nom de fichier documentaire original. |
| `canonical_filename` | string | document/page | Nom canonique associé au SHA-256 en cas de doublons exacts. |
| `source_sha256` | string | document/page/chunk | SHA-256 du PDF physique; identifiant principal de provenance. |
| `source_url` | string/null | document | URL source lorsque présente dans les métadonnées. |
| `title` | string | document/page/chunk | Titre documentaire issu des métadonnées sources. |
| `treaty_id` | string/null | document/page/chunk | Identifiant de traité. |
| `treaty_number` | string/null | document/page | Numéro ou sous-référence du traité. |
| `doc_type` | string | document/page/chunk | Type documentaire normalisé. |
| `year` | integer/null | document/page/chunk | Année extraite des métadonnées. |
| `page_count` | integer | document/page | Nombre total de pages du PDF. |
| `file_size_bytes` | integer/null | document | Taille du PDF en octets. |

## 2. Champs page OCR

| Champ | Type | Définition |
|---|---|---|
| `page_number` | integer | Numéro de page, base 1. |
| `text` | string | Texte nettoyé destiné à la KB dans `kb/pages.jsonl`. |
| `raw_text` | string | Texte brut du candidat sélectionné dans l’audit complet. |
| `cleaned_text` | string | Texte normalisé déterministiquement dans l’audit complet. |
| `method` | string | Méthode sélectionnée: `native_pymupdf`, `apple_vision`, ou `tesseract:<model>:psm<n>`. |
| `language` | array[string] | Langues détectées. |
| `script` | array[string] | Scripts détectés. |
| `quality_score` | number | Score composite borné entre 0 et 1. |
| `review_required` | boolean | Indique si la page doit être revue. |
| `review_priority` | string | `none`, `normal` ou `high`. |
| `review_reasons` | array[string] | Raisons contrôlées de révision. |
| `pipeline_version` | string | Version du pipeline ayant produit la page. |

## 3. Champs audit complet

| Champ | Type | Définition |
|---|---|---|
| `ink_ratio` | number | Proportion approximative de pixels sombres sur l’image réduite. |
| `agreement` | number/null | Accord normalisé entre Apple Vision et Tesseract lorsque calculable. |
| `removed_lines` | array[string] | Lignes retirées de la couche nettoyée. |
| `selected_blocks` | array[object] | Blocs/ligne du candidat sélectionné. |
| `candidates` | array[object] | Tous les candidats OCR conservés. |
| `bbox` | array[number] | Coordonnées normalisées `[x0, y0, x1, y1]`. |
| `confidence` | number/null | Confiance moteur ou agrégée. |
| `variant` | string | `original` ou `enhanced`. |
| `metrics` | object | Métriques de bruit, longueur, imprimabilité et scripts. |

## 4. Champs chunk KB

| Champ | Type | Définition |
|---|---|---|
| `chunk_id` | string | Identifiant stable du chunk: `<sha>:p####:c###`. |
| `chunk_index` | integer | Numéro du chunk dans la page. |
| `char_start` | integer | Début du chunk dans le texte de page. |
| `char_end` | integer | Fin du chunk dans le texte de page. |
| `text_sha256` | string | SHA-256 du texte du chunk pour éviter les réindexations inutiles. |
| `embedding_model` | string/null | Modèle d’embedding utilisé. |
| `embedding_created_at` | datetime/null | Date de création de l’embedding. |

## 5. Champs review event

| Champ | Type | Définition |
|---|---|---|
| `event_id` | string | Identifiant unique de l’événement de révision. |
| `created_at` | datetime | Date de l’événement. |
| `reviewer` | string | Personne ou rôle ayant révisé. |
| `issue_type` | string | Type d’anomalie ou raison de révision. |
| `decision` | string | Décision de révision. |
| `confidence_after_review` | string/null | Niveau après contrôle humain. |
| `notes` | string/null | Notes libres. |
| `linked_commit` | string/null | Commit Forgejo/Git associé à la décision. |
| `linked_paperless_id` | string/null | Identifiant Paperless si disponible. |

## 6. Champs dérivés recommandés

Ces champs ne sont pas toujours présents dans les exports actuels mais sont
recommandés pour la publication et l’indexation:

| Champ | Règle |
|---|---|
| `quality_band` | `accepted_ge_0_85`, `review_0_65_0_85`, `priority_review_lt_0_65`. |
| `period` | Période historique dérivée de `year`. |
| `century` | Siècle dérivé de `year`, format `c16`, `c17`, etc. |
| `method_family` | Famille extraite de `method`: native, Apple Vision, Tesseract. |
| `document_review_required` | Vrai si au moins une page du document doit être revue. |
| `mean_quality` | Moyenne des scores de page du document. |
| `min_quality` | Score minimal du document. |

## 7. Valeurs contrôlées principales

### `review_priority`

- `none`: aucune révision requise;
- `normal`: révision recommandée;
- `high`: révision prioritaire.

### `review_reasons`

- `engine_disagreement`;
- `high_noise`;
- `low_confidence`;
- `mixed_scripts`;
- `no_text_on_nonblank_page`;
- `possible_handwriting_or_historical_print`;
- `sparse_extraction`.

### `method_family`

- `native_pymupdf`;
- `apple_vision`;
- `tesseract`;
- `unknown`.

## 8. Champs knowledge graph node

| Champ | Type | Niveau | Provenance | Définition |
|---|---|---|---|---|
| `node_id` | string | node | `pdfkb.ids.node_id`, EPIC D | Identifiant déterministe du nœud (`doc:*`, `instr:*`, `ent:*`, `clause:*`). |
| `type` | enum | node | extracteurs KG | Type contrôlé : `Document`, `Instrument`, `Party`, `Organization`, `Person`, `Place`, `TopicConcept`, `Clause`. |
| `label` | string | node | métadonnées ou extraction déterministe | Libellé humain affichable. |
| `aliases` | array[string] | node | métadonnées / alignement | Variantes connues du libellé. |
| `wikidata_qid` | string/null | node | alignement externe vérifiable | Identifiant Wikidata `Q...`, jamais inventé. |
| `document_id` | string/null | node | export OCR | Document associé lorsqu'applicable. |
| `source_sha256` | string/null | node | inventaire OCR | SHA-256 du PDF source lorsqu'applicable. |
| `year` | integer/null | node | métadonnées | Année documentaire si disponible. |
| `confidence` | number/null | node | extracteur KG | Confiance bornée 0–1. |
| `provisional` | boolean | node | propagation qualité | Vrai si le nœud dépend d'une page à revoir. |
| `pipeline_version` | string/null | node | pipeline | Version du code ayant produit le nœud. |
| `tags` | array[string] | node | taxonomie | Tags `namespace:value`. |

## 9. Champs knowledge graph / similarité edge

| Champ | Type | Niveau | Provenance | Définition |
|---|---|---|---|---|
| `src` | string | edge | EPIC C/D | Identifiant source : chunk, document ou nœud. |
| `dst` | string | edge | EPIC C/D | Identifiant cible. |
| `level` | enum | edge | EPIC C/D | `chunk`, `document` ou `entity`. |
| `type` | enum | edge | EPIC C/D | Type de relation (`duplicate`, `clause_reuse`, `semantic_kin`, `translation`, `weak_link`, `party_to`, etc.). |
| `lexical` | number/null | edge | `pdfkb.similarity.lexical` | Score lexical MinHash/Jaccard. |
| `semantic` | number/null | edge | `pdfkb.similarity.index` | Score cosinus sur embeddings normalisés. |
| `combined` | number/null | edge | `pdfkb.similarity.pairs` | Fusion pondérée lexical/sémantique. |
| `quality_weight` | number/null | edge | propagation qualité | Minimum des qualités des deux extrémités. |
| `provisional` | boolean | edge | propagation qualité | Vrai si au moins une extrémité requiert révision. |
| `method` | string/null | edge | pipeline dérivé | Méthode ou modèle utilisé. |
| `evidence` | string/null | edge | extracteur KG / similarité | Span, page ou explication courte vérifiable. |
| `pipeline_version` | string | edge | pipeline | Version du code ayant produit l'arête. |

## 10. Mapping `doc_type` → `instrument_type` / `legal_force`

Le fichier `metadata_design/doc_type_mapping.json` établit la passerelle entre les
types documentaires sources et les catégories publiques larges. Le champ
`legal_force` reste `unknown` par défaut, sauf preuve explicite dans la source ; le
pipeline ne doit pas inférer le caractère contraignant d'un instrument par son seul
titre.

| Champ | Type | Provenance | Définition |
|---|---|---|---|
| `instrument_type` | enum | `doc_type_mapping.json` | Catégorie large : `treaty`, `declaration`, `resolution`, `recommendation`, etc. |
| `legal_force` | enum | `doc_type_mapping.json` / source vérifiée | `binding`, `non_binding`, `mixed`, `unknown`. |
| `issuing_body` | tag libre | métadonnées / EPIC H | Autorité émettrice sous forme slug, alignable à Wikidata. |
| `source_db` | enum | ingestion / export | Base source (`traites_mineae`, `eur_lex`, `oecd`, etc.). |
