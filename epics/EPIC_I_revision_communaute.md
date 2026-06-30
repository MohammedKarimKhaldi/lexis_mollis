# EPIC I — Révision & communauté (spec détaillée)

> Déclinaison exécutable de l'EPIC I. Met en place le **traitement humain des pages
> incertaines** (file de révision) et **l'ouverture du projet aux contributeurs**, sans
> jamais altérer la couche brute. S'appuie sur `review_queue.csv`,
> `audit/review_images/` et `review_event.schema.json` (existants). **DoD en §I.6.**

Garde-fous : `raw/` **immuable** ; toute correction crée un **événement de révision** et,
si validée, une couche **`corrected/` distincte et tracée** ; aucune correction générative
automatique ; chaque action attribuée et horodatée.

---

## I.0 Principe
La file de révision (`review_queue.csv`) classe les pages par priorité (`high`/`normal`).
Un réviseur traite en priorité les pages `high` (score < 0,65 ou page non vide sans texte).
Les corrections ne réécrivent jamais `raw/` : elles produisent des `review_event` (décision)
et, le cas échéant, une transcription corrigée stockée à part, réintégrée de façon explicite
et auditable dans les exports.

---

## I.1 Génération du lot de révision — `scripts/build_review_batch.py`
À partir de l'état + `review_queue.csv` + `audit/review_images/` :
- produire un **lot statique** par tranche (ex. 50 pages `high`) :
  `outputs_v2/review/batch_XXX/` contenant, par page, l'**image** (review image), le **texte
  OCR** sélectionné, le **score**, les **raisons** (`review_reasons`), la **méthode**, la
  langue/scripts détectés, et un **gabarit d'événement** pré-rempli (`source_sha256`,
  `page_number`, `document_id`).
- générer un `index.json` du lot (liste, statuts).
**CA I.1** : lot reproductible ; chaque page a image + texte + contexte + gabarit
d'événement ; tri par priorité respecté.

---

## I.2 Interface de révision (légère, gratuite)
Deux options, au choix, sans backend payant :
- **(A) Issues GitHub générées** : un script crée une issue par page `high`
  (template `transcription_fix.yml`, EPIC A.2.9) avec l'image (lien Internet Archive/HF), le
  texte OCR et les champs à remplir (décision, transcription corrigée éventuelle). Le réviseur
  répond ; un script récolte les réponses.
- **(B) Mini-page statique** intégrée au site Astro (`/revision`) : affiche le lot
  `outputs_v2/review/`, le réviseur saisit décision/correction, **export** d'un fichier
  d'événements (JSON) à committer en PR (pas de serveur).
Recommandation : démarrer avec **(B)** pour les auteurs, ouvrir **(A)** à la communauté.
**CA I.2** : un réviseur peut, pour une page, choisir une `decision` et saisir une
correction ; la sortie est un `review_event` valide.

---

## I.3 Enregistrement des événements — `pdfkb/review/`
```
pdfkb/review/
  __init__.py
  events.py     # load/append d'événements (review_events.jsonl) validés au schéma
  apply.py      # construit la couche corrected/ à partir des événements validés
```
- `events.py` : ajouter des événements conformes à `review_event.schema.json`
  (`event_id`, `reviewer`, `issue_type`, `decision`, `confidence_after_review`, `notes`,
  `linked_commit`). Stockage : `outputs_v2/review/review_events.jsonl` (versionné/publié).
- `apply.py` : pour les décisions `needs_manual_transcription` validées, écrire la
  transcription corrigée dans **`outputs_v2/corrected/{document_id}.md`** (couche séparée),
  en conservant le lien vers l'événement. Les exports KB (EPIC E) peuvent alors **préférer**
  la version corrigée quand elle existe, en le signalant (`text_source="corrected"`), sans
  jamais modifier `raw/`.
**CA I.3** : événements valides au schéma ; couche `corrected/` séparée et tracée ; lien
événement ↔ correction ↔ commit ; `raw/` inchangé (vérifié par hash).

---

## I.4 Réintégration & priorisation
- Mettre à jour les tags de page (`review:reviewed_confirmed`/`reviewed_corrected`/`deferred`)
  et la qualité effective après révision.
- Prioriser : pages `high`, puis pages affectant des **arêtes de similarité non provisional**
  ou des **nœuds de graphe** importants (effet de levier sur la KB/KG).
- Exposer l'avancement (compteurs : `high` restants, traités, corrigés) dans le `manifest`/
  le site.
**CA I.4** : statuts de révision propagés ; avancement mesurable ; priorisation à effet de
levier documentée.

---

## I.5 Contribution ouverte — gouvernance (lien EPIC A)
- `CONTRIBUTING.md` (déjà créé en A) détaille les **trois voies** :
  1. **ajouter une source** (EPIC H) — template `source_request.yml` ;
  2. **corriger une transcription** (cet EPIC) — template `transcription_fix.yml` ;
  3. **signaler une relation** (similarité/graphe) — template `relation_report.yml`.
- Définir un **flux de validation** : une correction proposée par un contributeur externe
  passe en PR, est revue par un mainteneur (Khaldi/Rostane ou délégués) avant d'entrer dans
  `corrected/`. Crédit des contributeurs (`CONTRIBUTORS.md`/section README).
- Étiquettes d'issues (`good first issue`, `source`, `transcription`, `relation`,
  `priority:high`) pour guider la communauté.
**CA I.5** : un contributeur externe peut suivre le guide sans contexte privé ; le flux de
validation est explicite ; crédits prévus.

---

## I.6 Definition of Done (EPIC I)
- [ ] `build_review_batch.py` produit des lots `high` (image + texte + contexte + gabarit).
- [ ] Interface de révision opérationnelle (mini-page Astro et/ou issues GitHub).
- [ ] `pdfkb/review/` : événements valides (`review_event.schema.json`), couche `corrected/`
      séparée et tracée, **`raw/` immuable** (vérifié).
- [ ] Statuts de révision et avancement propagés ; priorisation à effet de levier.
- [ ] Contribution ouverte documentée (3 voies, templates, flux de validation, crédits).
- [ ] Aucune correction générative ; chaque action attribuée et horodatée.

> **Fin du détail des épics (A→I).** Le `BUILD_PLAYBOOK.md` reste l'index ; chaque
> `epics/EPIC_*.md` en est la spec exécutable. Séquencement global et MVP : voir
> `BUILD_PLAYBOOK.md` §2.
