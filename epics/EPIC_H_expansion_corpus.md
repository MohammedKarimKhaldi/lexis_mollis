# EPIC H — Expansion du corpus `pdfkb/ingest/` (spec détaillée)

> Déclinaison exécutable de l'EPIC H. Permet d'atteindre l'objectif « plus grande base de
> droit souple au monde » en ingérant de nouvelles sources via un **cadre standardisé**, qui
> réutilise le **même pipeline et les mêmes schémas**. Ordre de priorité arrêté :
> **(1) EUR-Lex → (2) OCDE/OIT/OMS/OMC → (3) ECOLEX → (4) AGNU**. **DoD en §H.7.**

Garde-fous : respecter `robots.txt` / conditions d'utilisation de chaque source ; ne récolter
que le **librement diffusable** ; renseigner systématiquement `source_db`, `source_url`,
`rights_status` (jamais inféré), `instrument_type`, `legal_force` ; déduplication stricte ;
aucune écriture dans `raw/` autre que via le pipeline OCR normal.

---

## H.0 Structure
```
pdfkb/ingest/
  __init__.py
  base.py            # interface Source + types (SourceRecord, IngestReport)
  registry.py        # enregistrement des connecteurs
  dedup.py           # déduplication inter-sources (SHA-256 + MinHash)
  eurlex.py          # connecteur EUR-Lex (priorité 1)
  intl_orgs.py       # OCDE / OIT / OMS / OMC (priorité 2)
  ecolex.py          # ECOLEX (priorité 3)
  ungao.py           # résolutions/déclarations AGNU (priorité 4)
  cli.py             # sous-commande `ingest`
data/ingest/<source>/   # PDF/téléchargements bruts par source (hors git)
```

---

## H.1 Cadre d'ingestion — `base.py`
Interface commune que chaque connecteur implémente :
```python
@dataclass
class SourceRecord:
    source_db: str
    source_url: str
    external_id: str            # identifiant natif de la source
    title: str
    instrument_type: str        # taxonomie EPIC B
    legal_force: str            # binding/non_binding/mixed/unknown
    issuing_body: str | None
    year: int | None
    languages: list[str]
    rights_status: str          # public_domain_claimed/open_data_source/restricted/to_review
    extra: dict                 # métadonnées natives brutes

class Source(Protocol):
    name: str
    def discover(self, **filters) -> Iterator[SourceRecord]: ...
    def fetch(self, rec: SourceRecord, dest: Path) -> Path: ...      # télécharge le PDF/fichier
    def to_document_meta(self, rec: SourceRecord, file_sha256: str) -> dict: ...  # -> document.schema.json
```
Règles transverses :
- **Politesse réseau** : respect `robots.txt`, `User-Agent` identifiable, *rate limiting*,
  *backoff*, cache local (ne pas retélécharger).
- `to_document_meta` produit un enregistrement conforme à `document.schema.json` avec
  `rights_status` issu de la source (jamais deviné), `aliases`, `source_url`.
- **Conformité au filtrage réseau** : toute récupération web passe par les outils autorisés ;
  pas de contournement.
**CA H.1** : interface implémentée ; un enregistrement produit valide `document.schema.json` ;
politesse réseau respectée.

---

## H.2 Connecteur de référence — EUR-Lex (`eurlex.py`, priorité 1)
Premier connecteur **complet et exemplaire** (API ouverte, métadonnées riches) :
- `discover()` : interroger l'API EUR-Lex / SPARQL Cellar pour les actes de **soft law**
  (communications, recommandations, avis, lignes directrices) ; filtres par type, langue,
  période ; pagination.
- `fetch()` : télécharger le PDF/HTML officiel ; stocker dans `data/ingest/eur_lex/`.
- `to_document_meta()` : mapper CELEX → `external_id` ; `instrument_type` (recommendation,
  communication, opinion…), `legal_force="non_binding"` (soft law), `issuing_body`
  (`eu_commission`/`eu_council`…), `rights_status="open_data_source"` (EUR-Lex réutilisable
  selon ses conditions — vérifier et documenter), multilinguisme (versions linguistiques =
  documents liés par `translation_of`/`same_instrument_as`).
- Sortie : enregistrements + fichiers prêts pour `pdfkb run`.
**CA H.2** : un lot EUR-Lex découvert → téléchargé → métadonnées normalisées + provenance +
droits ; versions linguistiques rattachées ; rapport d'ingestion écrit.

---

## H.3 Connecteurs organisations internationales (`intl_orgs.py`, priorité 2)
OCDE, OIT, OMS, OMC : recommandations, codes de conduite, lignes directrices, déclarations.
- Implémenter par sous-classes partageant la logique commune ; chaque source : `discover`
  (portail/API ou sitemap), `fetch`, `to_document_meta` (`issuing_body` = `oecd|ilo|who|wto`,
  `legal_force="non_binding"` par défaut sauf mention contraire, `rights_status` selon
  conditions de la source).
**CA H.3** : au moins une des quatre opérationnelle de bout en bout ; les autres cadrées
(stubs + notes droits) ; rapports d'ingestion.

---

## H.4 Connecteur ECOLEX (`ecolex.py`, priorité 3)
Base FAO/IUCN/UNEP : traités + **soft law environnemental** + guidances.
- `discover()` : parcours du catalogue ECOLEX (respect des conditions) ; filtrer le soft law.
- `to_document_meta()` : `source_db="ecolex"`, thèmes environnementaux → tags `about_topic`,
  `rights_status` selon ECOLEX.
**CA H.4** : lot ECOLEX ingéré avec thèmes et droits ; intégré au pipeline.

---

## H.5 Connecteur AGNU (`ungao.py`, priorité 4)
Résolutions et déclarations de l'Assemblée générale de l'ONU (gros volume, cœur du droit
souple) :
- `discover()` : source ouverte des résolutions AGNU (cotes, sessions) ; pagination par
  session/année.
- `to_document_meta()` : `instrument_type ∈ {resolution, declaration}`,
  `issuing_body="un_general_assembly"`, `legal_force="non_binding"`,
  `rights_status` selon conditions ONU ; multilinguisme (6 langues officielles) lié.
**CA H.5** : lot AGNU ingéré ; volume significatif géré (pagination, reprise) ; versions
linguistiques rattachées.

---

## H.6 Déduplication inter-sources — `dedup.py` + intégration inventaire
- **Exacts** : fusionner par **SHA-256** (un même fichier diffusé par plusieurs sources →
  un PDF physique, plusieurs alias documentaires — réutilise la logique existante de
  `pdfkb`).
- **Quasi-doublons** : signaler via **MinHash** (réutiliser EPIC C) entre sources ; ne pas
  fusionner automatiquement, marquer pour révision.
- Étendre l'inventaire (`pdfkb/inventory.py`) pour intégrer les documents ingérés (mêmes
  `source_sha256`/`document_id`/alias) et éviter le double comptage dans les statistiques et
  la KB.
**CA H.6** : aucun double comptage ; alias préservés ; rapport de doublons (exacts + quasi)
écrit.

---

## H.7 CLI & Definition of Done
CLI (subparser conforme `pdfkb/cli.py`) :
```bash
.venv/bin/python -m pdfkb ingest run \
  --source eurlex \
  --dest data/ingest/eur_lex \
  --metadata metadata/parsed_metadata.json \
  --filters "type=recommendation,year>=2000"
# puis le pipeline OCR habituel sur les nouveaux fichiers :
.venv/bin/python -m pdfkb run --source data/ingest/eur_lex --metadata … --output outputs_v2 --resume
```
**DoD (EPIC H)** :
- [ ] Cadre `Source` + `registry` + `dedup` en place ; CLI `ingest run`.
- [ ] **EUR-Lex** complet (connecteur de référence), bout en bout jusqu'au pipeline.
- [ ] OCDE/OIT/OMS/OMC : au moins un opérationnel, les autres cadrés.
- [ ] ECOLEX et AGNU implémentés ou cadrés avec notes de droits.
- [ ] `source_db`/`source_url`/`rights_status`/`instrument_type`/`legal_force` renseignés ;
      jamais d'inférence de droits.
- [ ] Déduplication exacte + signalement quasi-doublons ; pas de double comptage.
- [ ] Politesse réseau et conformité respectées ; rapports d'ingestion produits.

> **Suite :** EPIC I — révision & communauté (outil de révision, contribution ouverte), qui
> traite les pages incertaines et ouvre le projet aux contributeurs.
