# Politique de sécurité

Merci de ne pas divulguer publiquement une vulnérabilité avant coordination avec
les mainteneurs.

## Signaler une vulnérabilité

Envoyer un signalement privé aux mainteneurs avec :

- description du problème ;
- étapes de reproduction ;
- impact potentiel ;
- version/commit concerné ;
- preuve de concept minimale si possible.

Adresse de contact à préciser avant publication publique :
`contact@lexis-mollis.example`.

## Secrets

Aucun token Hugging Face, Zenodo, GitHub, `.env`, base SQLite de production, PDF
source ou artefact massif ne doit être commité. Les tokens doivent être stockés
comme secrets GitHub Actions (`HF_TOKEN`, `ZENODO_TOKEN`) ou équivalent Forgejo.

