# Contribuer à Lexis Mollis

Merci de contribuer à une base ouverte et auditable de droit souple. Le projet
préfère les contributions petites, vérifiables et reproductibles.

## Préparer l'environnement

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[derive]'
```

## Garde-fous

- Ne jamais corriger, reformuler ou compléter le texte OCR par génération.
- Ne jamais supprimer les pages faibles : conserver `quality_score`,
  `review_required` et `review_priority`.
- Ne jamais inférer un statut de droits : conserver `rights_status` et la
  provenance.
- Ne jamais committer de secrets, tokens, `.env`, bases SQLite, PDF sources ou
  gros artefacts dérivés.
- Garder les pipelines déterministes et documenter les modèles/paramètres.

## Style et tests

- Code Python avec type hints quand c'est utile.
- Format recommandé : `black`, lint recommandé : `ruff`.
- Tests :

```bash
python -m unittest discover -v
python scripts/validate_schemas.py
python scripts/check_governance.py
```

## Workflow pull request

- Utiliser des commits conventionnels : `feat:`, `fix:`, `docs:`, `test:`,
  `chore:`.
- Une PR = un changement thématique.
- Décrire les données touchées, les commandes exécutées et les limites connues.
- Cocher les critères d'acceptation de l'epic concernée.

## Trois contributions prioritaires

1. Proposer une source de droit souple avec URL, droits et volume estimé.
2. Signaler une correction de transcription avec `document_id` et `page_number`.
3. Signaler une relation ou similarité manquante/fausse avec preuves.

Voir aussi [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

