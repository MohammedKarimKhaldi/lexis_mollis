# EPIC D — Knowledge graph `pdfkb/graph/` (spec détaillée)

> Déclinaison exécutable de l'EPIC D. Construit le **graphe de connaissances** du corpus :
> entités (États/parties, organisations, personnes, lieux, dates, thèmes, clauses),
> relations typées (ontologie EPIC B), enrichi des arêtes **`similar_to`** importées de
> l'EPIC C. Sorties multi-format : **RDF** (interop/SPARQL), **property graph** (Parquet) et
> **`graph.sigma.json`** (viz web, EPIC F). Réalisable sur les 1 309 docs complets.
> Contrats : `node.schema.json`, `edge.schema.json`, `ontology.ttl` (EPIC B). **DoD en §D.8.**

Garde-fous : extraction **conservatrice** (règles + gazetteers, jamais d'invention) ; toute
mention tracée à une page ; confiance et `provisional` propagés ; pas d'écriture dans `raw/` ;
déterminisme (identifiants via `pdfkb/ids.py`).

---

## D.0 Structure du module
```
pdfkb/graph/
  __init__.py
  config.py        # GraphConfig (seuils confiance, options NER, chemins gazetteers)
  gazetteers.py    # chargement listes États/orgs (+ QID Wikidata) depuis data/gazetteers/
  entities.py      # texte -> mentions (règles + gazetteers + NER optionnel)
  dates.py         # extraction de dates multilingue
  linking.py       # mentions -> nœuds canoniques (+ owl:sameAs Wikidata)
  build.py         # nœuds + arêtes -> RDF + Parquet + sigma.json
  run.py           # orchestration `build`
data/gazetteers/   # states.csv, organizations.csv, places.csv (label, aliases, qid, lang)
```
Entrées : `outputs_v2/kb/pages.jsonl` (texte + métadonnées), `outputs_v2/similarity/`
(arêtes `similar_to`/`translation`/`same_instrument_as`). Sortie : `outputs_v2/graph/`.

---

## D.1 Gazetteers — `gazetteers.py` + `data/gazetteers/`
Listes contrôlées, versionnées, alignées Wikidata (constituées une fois, étendables) :
- `states.csv` : `label, aliases (|-séparés), qid, iso3, lang` — États souverains historiques
  et actuels (gérer les noms d'époque : « Royaume de Prusse », « Empire ottoman », etc.).
- `organizations.csv` : organisations internationales (ONU, OCDE, OIT, OMS, OMC, UE, SDN…),
  `label, aliases, qid`.
- `places.csv` : villes de signature fréquentes (Genève, Vienne, Münster, Paris…), `qid`.
```python
def load_gazetteer(path: Path) -> list[GazEntry]: ...
def build_matcher(entries) -> Matcher:  # automate Aho-Corasick (lib `pyahocorasick`) sur labels+alias normalisés
```
**CA D.1** : gazetteers chargés ; matcher construit ; lookup O(texte) ; chaque entrée a un
`qid` valide (`^Q[0-9]+$`) ou vide assumé.

---

## D.2 Extraction d'entités — `entities.py`
```python
def extract_mentions(page: dict, matcher, cfg: GraphConfig) -> list[dict]:
    """Retourne des mentions tracées: {type, surface, canonical_hint, qid?, document_id,
       page_number, char_start, char_end, confidence, provisional, method}."""
```
Stratégie (par ordre, conservatrice) :
1. **Gazetteer/règles** (haute précision) : États, organisations, lieux via le matcher
   Aho-Corasick sur texte normalisé NFKC ; confiance haute.
2. **Dates** (`dates.py`) : motifs multilingues (FR/EN/latin, « le 24 octobre 1648 »,
   « 24 October 1648 », chiffres romains d'années si présents) → `confidence` selon netteté.
3. **NER optionnel** (`method="spacy"`) : modèle multilingue (`xx_ent_wiki_sm` ou
   transformeur) pour personnes/organisations hors gazetteer ; **désactivable** ; confiance
   plus basse, jamais utilisé seul pour créer une relation forte.
4. **Filtre qualité** : sur pages `review_priority == "high"`, marquer `provisional=true` et
   ne pas produire de relation forte ; ne jamais extraire sur texte vide/bruité sous le seuil.
**CA D.2** : précision vérifiée sur un échantillon annoté (≥ 50 mentions) ≥ objectif fixé ;
chaque mention porte page + offsets + confiance ; spans cohérents avec le texte.

---

## D.3 Liage & nœuds — `linking.py`
```python
def resolve_nodes(mentions: list[dict], documents: list[dict], cfg) -> tuple[nodes, mention_links]:
    """Fusionne les mentions en nœuds canoniques; crée les nœuds Document/Instrument."""
```
Détails :
- **Entités** (Party/Org/Person/Place/Topic) : regrouper par forme canonique
  (`ids.slug`) ou par `qid` si présent → un nœud `node_id = ent:wd:{QID}` ou
  `ent:{type}:{slug}`. `owl:sameAs` Wikidata si `qid`.
- **Document** : un nœud par `document_id` (`doc:{document_id}`), portant `title`, `year`,
  `doc_type`, `instrument_type`, `legal_force`, `rights_status`, `quality` agrégée.
- **Instrument** : un nœud par `treaty_id` (`instr:{treaty_id}`) regroupant ses documents
  (versions/alias) ; relier Document→Instrument (`dcterms:isPartOf`).
- Cache Wikidata local (`data/wikidata_cache.json`) : **aucun appel réseau en CI** ; le
  liage utilise le cache + les QID des gazetteers. (Enrichissement réseau = étape offline
  optionnelle, journalisée.)
**Livrable** : `outputs_v2/graph/nodes.parquet` valide `node.schema.json` ;
`mention_links.parquet` (mention ↔ node_id, pour audit).
**CA D.3** : pas de doublon d'entité canonique ; QID au format `^Q[0-9]+$` ; chaque nœud
Document relié à un Instrument quand `treaty_id` existe.

---

## D.4 Construction des arêtes — `build.py` (relations)
Produire les arêtes typées (`edge.schema.json`, `level` ∈ {entity, document}) :
- `party_to` : Party → Instrument (États mentionnés dans un document de l'instrument).
- `issued_by` : Instrument → Organization (organisation émettrice, via métadonnées/règles).
- `signed_at` : Instrument → Place ; `dated` : Instrument → date (littéral).
- `about_topic` : Document/Instrument → TopicConcept (tags `instrument_type`, thèmes).
- **Importer depuis l'EPIC C** : `same_instrument_as`, `translation`/`translation_of`,
  `similar_to` (avec `combined` comme poids et `provisional`).
- `amends`/`supersedes`/`references` : seulement si une **règle fiable** le détecte
  (ex. mention explicite « amende le traité … » + appariement d'instrument) ; sinon ne pas
  créer (préférer l'absence à l'erreur).
Chaque arête porte `evidence` (page + span ou source métadonnée) et `provisional`.
**CA D.4** : 100 % des arêtes valident `edge.schema.json` ; intégrité référentielle
(tout `src`/`dst` existe dans `nodes.parquet`) ; arêtes pondérées importées sans perte de poids.

---

## D.5 Sérialisation multi-format — `build.py` (export)
Produire, à partir de `nodes.parquet` + `edges.parquet` :
1. **RDF** : `graph.ttl` + `graph.jsonld` via `rdflib`, conformes à `ontology.ttl`. Les
   arêtes pondérées `similar_to` sont matérialisées par un nœud de lien
   `slo:SimilarityLink` (`slo:src`, `slo:dst`, `slo:weight`, `slo:linkType`,
   `slo:provisional`) pour préserver le poids en RDF.
2. **Property graph** : `nodes.parquet`, `edges.parquet` (déjà produits) — source pour la viz
   et l'analyse.
3. **Viz web** : `graph.sigma.json` = `{nodes:[{id,label,type,x,y,size}], edges:[{source,
   target,type,weight}]}`. Positions précalculées par layout **ForceAtlas2**
   (`fa2`/`networkx.forceatlas2_layout` ou `networkx.spring_layout`, `seed=cfg.seed`).
   Si le graphe est trop dense (> ~10 k nœuds), produire une **vue agrégée** au niveau
   Document/Instrument et garder le détail dans le dump complet.
**CA D.5** : `graph.ttl` rechargeable par `rdflib` ; cohérence des `node_id` entre formats ;
`graph.sigma.json` < 25 Mo (sinon vue agrégée) ; poids des `similar_to` préservés en RDF.

---

## D.6 Orchestration & CLI — `run.py` + `pdfkb/cli.py`
```python
def build(kb: Path, similarity: Path, output: Path, ontology: Path, cfg: GraphConfig) -> dict:
    # 1. load gazetteers + matcher
    # 2. extract_mentions sur chaque page
    # 3. resolve_nodes -> nodes.parquet, mention_links.parquet
    # 4. build relation edges + import similarity edges -> edges.parquet
    # 5. serialize RDF (ttl/jsonld) + sigma.json
    # 6. summary.json (compteurs par type de nœud/arête, % provisional)
    return manifest
```
CLI (subparser conforme `pdfkb/cli.py`) :
```bash
.venv/bin/python -m pdfkb graph build \
  --kb outputs_v2/kb/pages.jsonl \
  --similarity outputs_v2/similarity \
  --output outputs_v2/graph \
  --ontology metadata_design/ontology.ttl
```
**CA D.6** : exécution complète sur le sous-corpus ; tous les livrables D.3–D.5 ; journal
JSON final imprimé.

---

## D.7 Tests
`tests/test_graph.py` :
- matcher gazetteer : surface connue → bon `qid` ;
- dates : phrases FR/EN/latin → date normalisée correcte ;
- liage : deux surfaces (alias) d'un même État → un seul nœud ;
- intégrité : tout `src`/`dst` d'arête existe dans les nœuds ;
- RDF : `graph.ttl` parse sans erreur ; un `SimilarityLink` porte bien un poids ;
- sigma.json : schéma minimal (nodes/edges, positions numériques).
**CA D.7** : tests verts ; `summary.json` écrit.

---

## D.8 Definition of Done (EPIC D)
- [ ] `pdfkb graph build` tourne sur les 1 309 docs ; produit `nodes.parquet`,
      `edges.parquet`, `graph.ttl`, `graph.jsonld`, `graph.sigma.json`, `summary.json`.
- [ ] Nœuds ↔ `node.schema.json`, arêtes ↔ `edge.schema.json` (100 % valides).
- [ ] Extraction conservatrice tracée (page + offsets + confiance) ; `provisional` propagé.
- [ ] Liage Wikidata via cache local (aucun appel réseau en CI) ; QID valides.
- [ ] Arêtes `similar_to` (EPIC C) importées avec poids ; préservées en RDF (réification).
- [ ] Intégrité référentielle nœuds/arêtes ; `graph.sigma.json` prêt pour la viz (EPIC F).
- [ ] Déterminisme (seeds/identifiants) ; tests verts ; aucune écriture dans `raw/`.

> **Suite :** EPIC E — export & publication (Hugging Face Datasets, Zenodo/DOI, Internet
> Archive), qui empaquette `documents/pages/chunks/edges/nodes` pour la mise en ligne.
