# Contribuer à Lexis Mollis

Merci de contribuer à une base ouverte et auditable de droit souple. Les changements doivent
rester petits, vérifiables et reproductibles.

## Environnement

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[derive,dev,semantica]'
npm ci
```

Python 3.11 ou supérieur est requis.

Semantica et son Explorer sont dans l'extra optionnel `semantica`. Une installation de
contribution les inclut afin que les tests d'adaptation `ContextGraph` s'exécutent en CI.

## Garde-fous

- Ne jamais corriger, reformuler ou compléter le texte OCR par génération.
- Ne jamais supprimer les pages faibles ; conserver les champs de qualité et de révision.
- Ne jamais inférer un statut de droits ; conserver la provenance et `rights_status`.
- Ne jamais committer secrets, `.env`, bases SQLite, PDF sources ou gros artefacts dérivés.
- Garder les pipelines déterministes et documenter modèles, paramètres et seeds.

## Style et validation

Ruff est l'unique formateur/linter Python du projet. Le dossier `legacy/` est exclu afin de
préserver les scripts archivés dans leur état historique.

```bash
ruff check .
ruff format --check .
python -m unittest discover -v
python scripts/validate_schemas.py
python scripts/check_governance.py
npm run build
```

Pour appliquer le format avant une PR :

```bash
ruff check --fix .
ruff format .
```

## Pull requests

- Utiliser des commits conventionnels : `feat:`, `fix:`, `docs:`, `test:`, `chore:`.
- Une PR doit couvrir un changement thématique.
- Décrire les données touchées, les commandes exécutées et les limites connues.
- Signaler explicitement toute modification d'un schéma, de l'ontologie ou des sorties publiées.

Les contributions prioritaires sont les nouvelles sources ouvertes avec droits vérifiés,
les signalements de transcription avec preuve et les corrections de relations documentées.

Voir aussi [ARCHITECTURE.md](ARCHITECTURE.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) et
[SECURITY.md](SECURITY.md).
