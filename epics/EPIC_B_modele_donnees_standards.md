# EPIC B — Modèle de données & standards (spec détaillée)

> Déclinaison exécutable de l'EPIC B du `BUILD_PLAYBOOK.md`. Objectif : figer les **contrats
> de données** de toute la plateforme — schémas des entités dérivées (chunk, edge, node),
> taxonomie de tags, **ontologie RDF** du knowledge graph, et dictionnaire de données — afin
> que les EPIC C (similarité), D (graphe), E (publication) et F (site) produisent et
> consomment des structures stables et validables. Aucune dépendance à l'OCR.
> **DoD en §B.6.**

Tous les fichiers vivent dans `metadata_design/` (dépôt `pipeline`). Style imposé :
JSON Schema **draft 2020-12**, `$id` cohérent, `additionalProperties:false` pour les
nouveaux schémas, patterns SHA-256 `^[a-f0-9]{64}$`, tags `^[a-z_]+:.+$`.

Existant à réutiliser tel quel : `document.schema.json`, `page.schema.json`,
`chunk.schema.json`, `review_event.schema.json`, `tag_taxonomy.json`.

---

## B.1 Étendre les schémas

### B.1.1 `node.schema.json` (nœud du knowledge graph)
Créer `metadata_design/node.schema.json` :
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://local.invalid/schemas/ocr-treaties/node.schema.json",
  "title": "Lexis Mollis Knowledge Graph Node",
  "type": "object",
  "additionalProperties": false,
  "required": ["node_id", "type", "label"],
  "properties": {
    "node_id": {"type": "string", "minLength": 1},
    "type": {
      "type": "string",
      "enum": ["Document", "Instrument", "Party", "Organization", "Person", "Place", "TopicConcept", "Clause"]
    },
    "label": {"type": "string", "minLength": 1},
    "aliases": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
    "wikidata_qid": {"type": ["string", "null"], "pattern": "^Q[0-9]+$"},
    "document_id": {"type": ["string", "null"]},
    "source_sha256": {"type": ["string", "null"], "pattern": "^[a-f0-9]{64}$"},
    "year": {"type": ["integer", "null"]},
    "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
    "provisional": {"type": "boolean", "default": false},
    "tags": {"type": "array", "items": {"type": "string", "pattern": "^[a-z_]+:.+$"}, "uniqueItems": true}
  }
}
```
**Conventions `node_id`** (déterministes, stables) :
- `Document` : `doc:{document_id}` ; `Instrument` : `instr:{treaty_id}` (ou hash titre si
  absent) ; `Party`/`Organization`/`Person`/`Place`/`TopicConcept` : `ent:{type}:{slug}` où
  `slug` = forme canonique normalisée (NFKC, casefold, `[a-z0-9_]`), ou `ent:wd:{QID}` si
  aligné Wikidata ; `Clause` : `clause:{source_sha256}:p{page:04d}:c{idx:03d}`.

### B.1.2 `edge.schema.json` (arête : similarité **et** relations KG)
Créer `metadata_design/edge.schema.json` :
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://local.invalid/schemas/ocr-treaties/edge.schema.json",
  "title": "Lexis Mollis Graph Edge",
  "type": "object",
  "additionalProperties": false,
  "required": ["src", "dst", "level", "type"],
  "properties": {
    "src": {"type": "string", "minLength": 1},
    "dst": {"type": "string", "minLength": 1},
    "level": {"type": "string", "enum": ["chunk", "document", "entity"]},
    "type": {
      "type": "string",
      "enum": [
        "duplicate", "clause_reuse", "semantic_kin", "translation", "weak_link",
        "party_to", "issued_by", "signed_at", "dated", "amends", "supersedes",
        "references", "translation_of", "same_instrument_as", "similar_to", "about_topic"
      ]
    },
    "lexical": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
    "semantic": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
    "combined": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
    "quality_weight": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
    "provisional": {"type": "boolean", "default": false},
    "method": {"type": ["string", "null"]},
    "evidence": {"type": ["string", "null"]},
    "pipeline_version": {"type": "string"}
  }
}
```
**Règles :** les 5 premiers `type` (similarité, EPIC C) portent `lexical/semantic/combined/
quality_weight` ; les `type` relationnels (KG, EPIC D) portent éventuellement `evidence`
(span/source). Une **seule arête par paire non ordonnée** pour les types symétriques
(`duplicate`, `semantic_kin`, `translation`, `weak_link`, `similar_to`, `same_instrument_as`)
en ordonnant `src < dst` lexicographiquement.

### B.1.3 Étendre `tag_taxonomy.json`
Ajouter dans `namespaces` :
```json
"instrument_type": {
  "description": "Soft-law instrument family (broader than doc_type).",
  "values": ["treaty", "declaration", "resolution", "recommendation", "guideline",
             "code_of_conduct", "decision", "opinion", "communication", "standard",
             "programme_of_action", "other", "unknown"]
},
"legal_force": {
  "description": "Binding character of the instrument.",
  "values": ["binding", "non_binding", "mixed", "unknown"]
},
"issuing_body": {
  "description": "Issuing authority (free slug, aligned to Wikidata when possible).",
  "examples": ["un_general_assembly", "oecd", "ilo", "who", "wto", "eu_commission", "unep"]
},
"source_db": {
  "description": "Originating source database / connector (EPIC H).",
  "values": ["traites_mineae", "eur_lex", "oecd", "ilo", "who", "wto", "ecolex", "ungao", "other"]
}
```
> `doc_type` (existant) reste la valeur fine issue des métadonnées sources ;
> `instrument_type` est la catégorie large, pivot pour le filtrage public.

### B.1.4 Mapping `doc_type` → `instrument_type` / `legal_force`
Créer `metadata_design/doc_type_mapping.json` : table associant chaque `doc_type` existant
(Accord, Convention, Déclaration, Protocole, Résolution future, …) à `instrument_type` et
à un `legal_force` par défaut (« unknown » si incertain — **ne pas inférer abusivement** le
caractère contraignant). Ce mapping est consommé par l'export (EPIC E) pour poser les tags.
- **CA B.1** : `node.schema.json`, `edge.schema.json`, `doc_type_mapping.json` créés ;
  `tag_taxonomy.json` étendu ; tous parsables ; chaque `doc_type` du document.schema a une
  entrée de mapping.

---

## B.2 Ontologie du knowledge graph — `metadata_design/ontology.ttl`

Créer une ontologie RDF (Turtle) alignée sur le `node.schema`/`edge.schema`, réutilisant
**schema.org**, **FRBR/FaBiO** (œuvre/expression/manifestation) et **Wikidata**.

```turtle
@prefix slo:  <https://lexis-mollis.org/ontology#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix schema: <https://schema.org/> .
@prefix dcterms: <http://purl.org/dc/terms/> .

slo: a owl:Ontology ;
  rdfs:label "Lexis Mollis ontology"@en ;
  dcterms:license <https://creativecommons.org/licenses/by/4.0/> .

# ---- Classes ----
slo:Instrument a owl:Class ; rdfs:subClassOf schema:Legislation ;
  rdfs:label "Soft-law instrument"@en .            # œuvre (FRBR Work)
slo:Document a owl:Class ;
  rdfs:label "Document/manifestation"@en .          # manifestation (un scan/alias)
slo:Party a owl:Class ; rdfs:subClassOf schema:Country ; rdfs:label "Party/State"@en .
slo:Organization a owl:Class ; rdfs:subClassOf schema:Organization .
slo:Person a owl:Class ; rdfs:subClassOf schema:Person .
slo:Place a owl:Class ; rdfs:subClassOf schema:Place .
slo:TopicConcept a owl:Class ; rdfs:subClassOf schema:DefinedTerm .
slo:Clause a owl:Class ; rdfs:label "Clause/passage"@en .

# ---- Propriétés relationnelles ----
slo:partyTo a owl:ObjectProperty ; rdfs:domain slo:Party ; rdfs:range slo:Instrument .
slo:issuedBy a owl:ObjectProperty ; rdfs:domain slo:Instrument ; rdfs:range slo:Organization .
slo:signedAt a owl:ObjectProperty ; rdfs:domain slo:Instrument ; rdfs:range slo:Place .
slo:amends a owl:ObjectProperty ; rdfs:domain slo:Instrument ; rdfs:range slo:Instrument .
slo:supersedes a owl:ObjectProperty ; rdfs:domain slo:Instrument ; rdfs:range slo:Instrument .
slo:references a owl:ObjectProperty ; rdfs:domain slo:Instrument ; rdfs:range slo:Instrument .
slo:translationOf a owl:ObjectProperty ; rdfs:domain slo:Document ; rdfs:range slo:Document .
slo:sameInstrumentAs a owl:ObjectProperty, owl:SymmetricProperty .
slo:aboutTopic a owl:ObjectProperty ; rdfs:range slo:TopicConcept .
slo:similarTo a owl:ObjectProperty, owl:SymmetricProperty ;
  rdfs:comment "Weighted similarity edge; weight & type carried via reification."@en .

# ---- Propriétés littérales ----
slo:dated a owl:DatatypeProperty ; rdfs:range schema:Date .
slo:qualityScore a owl:DatatypeProperty ; rdfs:range schema:Float .
slo:reviewRequired a owl:DatatypeProperty ; rdfs:range schema:Boolean .
slo:rightsStatus a owl:DatatypeProperty ; rdfs:range schema:Text .
slo:legalForce a owl:DatatypeProperty ; rdfs:range schema:Text .
```
**Notes de modélisation :**
- Séparer `slo:Instrument` (l'acte, FRBR Work) de `slo:Document` (un scan/alias particulier) ;
  relier par `dcterms:isPartOf` / une expression linguistique. `translationOf` relie deux
  `Document`/expressions ; `sameInstrumentAs` relie deux `Document` du même `Instrument`.
- Les arêtes pondérées `similarTo` (poids, type, provisional) sont portées dans le **property
  graph** (`edges.parquet`) et, en RDF, via **réification** ou un nœud `slo:SimilarityLink`
  (`src`, `dst`, `weight`, `type`) pour ne pas perdre le poids.
- Aligner les entités via `owl:sameAs <http://www.wikidata.org/entity/Qxxx>`.
- **CA B.2** : `ontology.ttl` se charge sans erreur (`rdflib.Graph().parse("...ttl",
  format="turtle")`) ; chaque `type` d'arête KG du `edge.schema` correspond à une propriété
  `slo:` (ou à une règle de réification documentée).

---

## B.3 Identifiants & normalisation (`pdfkb/ids.py`)
Créer un module utilitaire **partagé** garantissant des identifiants déterministes et
réutilisé par C, D, E :
- `slug(text) -> str` : NFKC + casefold + `[^a-z0-9]+ -> "_"` + trim.
- `chunk_id(sha, page, idx) -> "{sha}:p{page:04d}:c{idx:03d}"`.
- `node_id(type, ...)`, `edge_key(src, dst, type)` (ordonne src/dst pour les types
  symétriques), `text_sha256(text)`.
- Tests `tests/test_ids.py` (formats, idempotence, symétrie).
- **CA B.3** : identifiants conformes aux patterns des schémas ; tests verts.

---

## B.4 Data dictionary — `metadata_design/data_dictionary.md`
Mettre à jour/compléter pour couvrir **chaque champ produit** par un pipeline, avec :
nom, niveau (document/page/chunk/node/edge), type, **provenance** (quel module l'écrit),
valeurs autorisées (renvoi taxonomie), et note qualité/droits le cas échéant. Ajouter les
sections **Node**, **Edge**, et le mapping `doc_type → instrument_type/legal_force`.
- **CA B.4** : un lecteur peut comprendre l'origine et le sens de tout champ sans lire le code.

---

## B.5 Validation automatisée — `scripts/validate_schemas.py`
Script (réutilisé par la CI, EPIC G.1) qui :
1. charge tous les `metadata_design/*.schema.json` et vérifie qu'ils sont des JSON Schema
   draft 2020-12 valides (via `jsonschema`) ;
2. parse `ontology.ttl` avec `rdflib` ;
3. valide `tag_taxonomy.json` et `doc_type_mapping.json` (JSON valide, couverture des
   `doc_type`) ;
4. **échantillon réel** : valide N enregistrements de `outputs_v2/kb/pages.jsonl` contre
   `page.schema.json` (si le fichier existe) pour détecter toute dérive.
- Dépendances : `jsonschema`, `rdflib`, `pyarrow` (déjà dans `[derive]`).
- **CA B.5** : `python scripts/validate_schemas.py` sort en code 0 ; échoue si un schéma est
  invalide ou si un enregistrement réel ne valide pas.

---

## B.6 Definition of Done (EPIC B)
- [ ] `node.schema.json` + `edge.schema.json` créés et valides (draft 2020-12).
- [ ] `tag_taxonomy.json` étendu (`instrument_type`, `legal_force`, `issuing_body`,
      `source_db`) ; `doc_type_mapping.json` couvre tous les `doc_type`.
- [ ] `ontology.ttl` complet, chargeable, aligné aux schémas (classes/propriétés ↔ types).
- [ ] `pdfkb/ids.py` + tests : identifiants déterministes conformes aux patterns.
- [ ] `data_dictionary.md` à jour (tous champs, provenance, niveaux node/edge).
- [ ] `scripts/validate_schemas.py` passe (schémas + ontologie + échantillon réel).
- [ ] Garde-fous : aucun champ n'encourage la correction générative ; `provisional`/qualité
      présents partout où une donnée dérive d'une page incertaine.

> **Suite :** EPIC C — module de similarité (`pdfkb/similarity/`), qui produit chunks,
> embeddings et arêtes conformes aux schémas figés ici.
