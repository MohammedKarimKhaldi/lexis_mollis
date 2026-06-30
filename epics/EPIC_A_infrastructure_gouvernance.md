# EPIC A — Infrastructure & gouvernance (spec détaillée)

> Déclinaison exécutable de l'EPIC A du `BUILD_PLAYBOOK.md`. Objectif : poser les fondations
> publiques du projet **Lexis Mollis** — organisation, dépôts, licences, fichiers de
> gouvernance, comptes de publication et secrets — pour que tous les autres épics aient un
> socle propre. Aucune dépendance à l'OCR. **Définition de fin (DoD) en §A.6.**

Décisions verrouillées appliquées ici : nom **Lexis Mollis** / `lexis-mollis` ; données
**CC-BY-4.0** (attribution Mohammed-Karim Khaldi, Reda Rostane) ; code **Apache-2.0**.

---

## A.0 Prérequis
- Comptes : GitHub, Hugging Face, Zenodo (les trois gratuits). ORCID recommandé pour chaque
  auteur (améliore Zenodo/citation).
- Outils locaux : `git`, **GitHub CLI** (`gh`), `python ≥ 3.11`, `pipx` (optionnel pour
  `cffconvert`).
- Authentifier `gh` : `gh auth login` (scopes `repo`, `admin:org`, `workflow`).

---

## A.1 Organisation et dépôts

### A.1.1 Créer l'organisation
Créer l'organisation GitHub **`lexis-mollis`** (plan Free) via l'interface
(`github.com/account/organizations/new`). Réglages :
- Visibilité des dépôts par défaut : **Public**.
- Ajouter Mohammed-Karim Khaldi et Reda Rostane comme **Owners**.
- Photo/description : « Lexis Mollis — base ouverte mondiale de droit souple ».

### A.1.2 Créer les trois dépôts
| Dépôt | Rôle | Visibilité |
|-------|------|-----------|
| `pipeline` | code (pdfkb + similarity + graph + scripts + CI + docs) | Public |
| `platform` | site Astro + Spaces de service (search, sparql) | Public |
| `corpus-data` | pointeurs/sous-modules vers les données HF (pas les gros binaires) | Public |

```bash
gh repo create lexis-mollis/pipeline   --public --description "Lexis Mollis — pipeline OCR, similarité, knowledge graph"
gh repo create lexis-mollis/platform   --public --description "Lexis Mollis — site web et services de recherche/graphe"
gh repo create lexis-mollis/corpus-data --public --description "Lexis Mollis — pointeurs vers les jeux de données ouverts"
```

### A.1.3 Pousser le code existant dans `pipeline`
Depuis le répertoire de travail actuel (qui contient `pdfkb/`, `metadata_design/`, `tests/`,
`benchmarks/`, `pyproject.toml`, les `.md`) :
```bash
git init -b main                       # si pas déjà un dépôt
# .gitignore AVANT le premier commit (voir A.1.4) — ne PAS committer données/PDF/venv
git add pdfkb tests benchmarks pyproject.toml *.md metadata_design epics
git commit -m "chore: import initial pipeline pdfkb + design"
git remote add origin https://github.com/lexis-mollis/pipeline.git
git push -u origin main
```

### A.1.4 `.gitignore` (dépôt `pipeline`) — ne jamais committer données lourdes ni secrets
```gitignore
# Environnements
.venv/
__pycache__/
*.pyc
# Données lourdes et sorties (vivent sur HF / Internet Archive, pas dans git)
traites/
extracted/
outputs_v2/
outputs_live*/
outputs/
metadata/*.sqlite3
metadata/*.log
*.faiss
*.npy
*.parquet
# Secrets
.env
*.token
# Systèmes
.DS_Store
```
> Les **schémas** (`metadata_design/*.json`, `*.ttl`) et la **doc** sont versionnés ; les
> **données** ne le sont pas (elles seront publiées via EPIC E sur HF/Zenodo).

### A.1.5 Protection de branche + réglages
- Protéger `main` : exiger une PR, exiger le passage de `ci.yml` (mis en place en EPIC G),
  interdire le push direct.
- Activer Issues, Discussions ; ajouter des *topics* : `soft-law`, `open-data`,
  `knowledge-graph`, `ocr`, `legal-nlp`, `semantic-search`.
```bash
gh repo edit lexis-mollis/pipeline --enable-issues --enable-discussions \
  --add-topic soft-law --add-topic open-data --add-topic knowledge-graph \
  --add-topic ocr --add-topic legal-nlp --add-topic semantic-search
```
- **CA A.1** : 3 dépôts publics existent ; `pipeline` contient le code (sans données ni
  `.venv`) ; `main` protégé ; topics présents.

---

## A.2 Licences et fichiers de gouvernance (dépôt `pipeline`)

Créer les fichiers ci-dessous **à la racine** de `pipeline`. Contenus fournis prêts à
committer (compléter les `<…>`).

### A.2.1 `LICENSE` (code — Apache-2.0)
Texte intégral de la licence Apache-2.0 (récupérer la version officielle depuis
`apache.org/licenses/LICENSE-2.0.txt`). En-tête de copyright :
`Copyright 2026 Mohammed-Karim Khaldi, Reda Rostane`.

### A.2.2 `LICENSE-DATA` (données — CC-BY-4.0)
Texte intégral CC-BY-4.0 (depuis `creativecommons.org/licenses/by/4.0/legalcode.txt`),
précédé d'un en-tête :
```
Les jeux de données produits par Lexis Mollis (texte OCR, métadonnées, chunks,
embeddings, arêtes de similarité, knowledge graph) sont publiés sous licence
Creative Commons Attribution 4.0 International (CC-BY-4.0).
Attribution requise : « Mohammed-Karim Khaldi, Reda Rostane — Lexis Mollis ».
Les textes officiels sous-jacents (traités, résolutions, etc.) peuvent relever du
domaine public ou de conditions propres à leur source ; voir le champ rights_status
de chaque document.
```

### A.2.3 `CITATION.cff`
```yaml
cff-version: 1.2.0
message: "Si vous utilisez Lexis Mollis, merci de citer ce dépôt."
title: "Lexis Mollis — base ouverte de droit souple"
abstract: >-
  Corpus ouvert de droit souple (traités, déclarations, résolutions, recommandations,
  lignes directrices) avec transcription OCR fidèle et auditable, knowledge base,
  knowledge graph et détection de similarités.
type: dataset
authors:
  - family-names: Khaldi
    given-names: Mohammed-Karim
    # orcid: "https://orcid.org/0000-0000-0000-0000"
  - family-names: Rostane
    given-names: Reda
    # orcid: "https://orcid.org/0000-0000-0000-0000"
license: CC-BY-4.0
repository-code: "https://github.com/lexis-mollis/pipeline"
url: "https://github.com/lexis-mollis"
keywords:
  - soft law
  - droit souple
  - open data
  - knowledge graph
  - OCR
  - semantic search
version: "0.1.0"
date-released: "2026-07-01"
# doi: "10.5281/zenodo.XXXXXXX"   # à compléter après la première release Zenodo (EPIC E)
```
- Valider : `pipx run cffconvert --validate` (ou `pip install cffconvert && cffconvert --validate`).

### A.2.4 `.zenodo.json` (métadonnées de release → DOI, utilisé en EPIC E)
```json
{
  "title": "Lexis Mollis — base ouverte de droit souple",
  "description": "Corpus ouvert de droit souple avec OCR fidèle, knowledge base, knowledge graph et similarités. Données sous CC-BY-4.0 ; code sous Apache-2.0.",
  "upload_type": "dataset",
  "access_right": "open",
  "license": "CC-BY-4.0",
  "creators": [
    {"name": "Khaldi, Mohammed-Karim"},
    {"name": "Rostane, Reda"}
  ],
  "keywords": ["soft law", "droit souple", "open data", "knowledge graph", "OCR", "semantic search"],
  "communities": []
}
```

### A.2.5 `README.md` (racine `pipeline`) — squelette
Sections : titre + badges (licence, CI, DOI) ; pitch (1 paragraphe) ; **Avertissement
qualité/OCR** (texte historique multilingue, pages à réviser, ne pas traiter comme vérité
absolue) ; architecture (renvoi à `ROADMAP.md` et `BUILD_PLAYBOOK.md`) ; installation
(`.venv`, `pip install -e .[derive]`) ; usage CLI (`run`, `audit`, `similarity build`,
`graph build`) ; **données & licence** (liens HF/Zenodo/Internet Archive, CC-BY-4.0,
attribution) ; **citation** (renvoi `CITATION.cff`) ; contribution (`CONTRIBUTING.md`) ;
auteurs.

### A.2.6 `CONTRIBUTING.md`
Couvrir : prérequis dev (`.venv`, `pip install -e .[derive]`), style (`ruff`, `black`,
type hints), tests (`python -m unittest discover`), **garde-fous §0.3** (aucune correction
générative ; ne pas committer de données/secrets), workflow PR (Conventional Commits,
1 PR thématique), trois façons de contribuer (ajouter une source — EPIC H ; corriger une
transcription — EPIC I ; signaler une relation). Renvoi au `CODE_OF_CONDUCT.md`.

### A.2.7 `CODE_OF_CONDUCT.md`
Adopter **Contributor Covenant v2.1** (texte officiel) ; e-mail de contact :
`<contact@lexis-mollis ou e-mail des auteurs>`.

### A.2.8 `SECURITY.md`
Politique de signalement : pas de divulgation publique des vulnérabilités ; contact privé ;
rappel qu'aucun secret ne doit figurer dans le dépôt (tokens en secrets Actions).

### A.2.9 Templates GitHub (`.github/`)
- `ISSUE_TEMPLATE/source_request.yml` (proposer une source de droit souple : nom, URL,
  licence/droits, volume estimé).
- `ISSUE_TEMPLATE/transcription_fix.yml` (signaler une page à corriger : `document_id`,
  `page_number`, description).
- `ISSUE_TEMPLATE/relation_report.yml` (signaler une similarité/relation manquante ou fausse).
- `PULL_REQUEST_TEMPLATE.md` (checklist : tests verts, pas de données/secrets, garde-fous
  respectés, CA de la tâche cochés).

- **CA A.2** : tous les fichiers présents et valides ; `cffconvert --validate` OK ;
  `README` mentionne licence + attribution + avertissement qualité ; aucun secret dans le
  dépôt.

---

## A.3 Comptes de publication & secrets

### A.3.1 Organisation Hugging Face
Créer l'organisation HF **`lexis-mollis`**. Y créer (vides pour l'instant) :
- un **dataset** `lexis-mollis/soft-law-corpus` (rempli en EPIC E) ;
- réserver l'espace pour deux **Spaces** : `lexis-mollis/search` et `lexis-mollis/sparql`
  (créés en EPIC F).
Générer un **token HF** à portée *write* limitée à l'org.

### A.3.2 Zenodo
- Se connecter à Zenodo (login GitHub), accepter l'intégration GitHub.
- Activer le webhook Zenodo sur le dépôt `pipeline` (Zenodo → GitHub → activer
  `lexis-mollis/pipeline`) : une **release GitHub** créera automatiquement un dépôt Zenodo
  versionné avec **DOI**.
- Générer un **token Zenodo** (scope `deposit:write`, `deposit:actions`) pour les releases
  automatisées (EPIC E/G).

### A.3.3 Secrets GitHub Actions (org ou dépôt `pipeline`)
```bash
gh secret set HF_TOKEN     --org lexis-mollis --body "<token_hf_write>"
gh secret set ZENODO_TOKEN --org lexis-mollis --body "<token_zenodo>"
# (variante par dépôt : gh secret set HF_TOKEN --repo lexis-mollis/pipeline ...)
```
- **Ne jamais** committer ces tokens. Vérifier qu'aucun `.env`/token n'est suivi par git
  (`git ls-files | grep -iE 'token|\.env'` doit être vide).

- **CA A.3** : org HF créée + dataset vide + token write ; webhook Zenodo actif ; secrets
  `HF_TOKEN` et `ZENODO_TOKEN` configurés et non présents dans le code.

---

## A.4 `corpus-data` (pointeurs, pas de binaires)
Initialiser `corpus-data` avec un seul `README.md` expliquant que les données vivent sur
Hugging Face (`hf.co/datasets/lexis-mollis/soft-law-corpus`), Zenodo (DOI) et Internet
Archive (PDF), avec les liens et la licence CC-BY-4.0. Aucun gros fichier ici.
- **CA A.4** : dépôt présent, README avec liens (placeholders acceptés tant qu'EPIC E n'a
  pas tourné).

---

## A.5 Vérification finale (script)
Ajouter `scripts/check_governance.py` (utilisé aussi par la CI en EPIC G.1) qui vérifie la
présence et la validité des fichiers de gouvernance :
- existence de `LICENSE`, `LICENSE-DATA`, `CITATION.cff`, `README.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.zenodo.json` ;
- `CITATION.cff` valide (appel `cffconvert` ou parsing YAML + champs requis) ;
- `.zenodo.json` est un JSON valide avec `license == "CC-BY-4.0"` et 2 créateurs ;
- aucun fichier suivi ne matche `token|\.env|\.sqlite3|\.parquet|\.npy`.
- **CA A.5** : `python scripts/check_governance.py` sort en code 0.

---

## A.6 Definition of Done (EPIC A)
- [ ] Org `lexis-mollis` (GitHub + HF) créée ; auteurs Owners.
- [ ] Dépôts publics `pipeline`, `platform`, `corpus-data` créés ; code importé dans
      `pipeline` **sans** données/venv/secrets.
- [ ] `main` protégé (PR + CI requis) ; topics ; Issues/Discussions activés.
- [ ] Tous les fichiers de gouvernance présents et valides (A.2) ; `cffconvert` OK.
- [ ] Comptes HF + Zenodo opérationnels ; webhook Zenodo actif ; secrets Actions posés.
- [ ] `scripts/check_governance.py` passe.
- [ ] Aucune fuite de secret ni de donnée lourde dans l'historique git.

> **Suite :** EPIC B — modèle de données & standards (étendre schémas, ontologie, data
> dictionary), qui s'appuie sur ces dépôts.
