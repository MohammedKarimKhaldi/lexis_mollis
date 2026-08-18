# Feuille de route Lexis Mollis

Mise à jour : 9 août 2026. L'état mesuré est dans [PROJECT_STATUS.md](PROJECT_STATUS.md) et
l'architecture actuelle dans [ARCHITECTURE.md](ARCHITECTURE.md).

## Acquis

- OCR terminé sur 3 146 documents et 26 566 pages, sans document en erreur.
- Schémas, ontologie, taxonomie et gouvernance présents et validés en CI.
- Similarité multilingue construite avec chunks, MinHash, LaBSE/FAISS et profils de types documentaires.
- Knowledge graph complet construit et exporté en Parquet, Turtle, JSON-LD et projection Sigma.
- Release Parquet et dataset Hugging Face publiés ; release GitHub `v0.1.0` créée.
- Site Astro/Cloudflare déployé avec recherche, fiches document, graphe et assistant.
- Semantica 0.6.0 intégré comme couche ContextGraph/API derrière l'UI Astro légère, avec profils complet et web.

## Priorité 1 — Validation scientifique

- Faire relire humainement les cas de calibration de similarité actuellement marqués comme brouillon LLM.
- Valider au moins 50 mentions/relations du knowledge graph et publier le taux de précision.
- Recalculer les seuils, le graphe et la release uniquement si les validations modifient les paramètres.
- Récupérer ou créer le DOI Zenodo et le reporter dans les métadonnées publiques.

## Priorité 2 — Exploitation fiable

- Ajouter les workflows CI/CD utiles : build dérivé contrôlé, release et déploiement du site.
- Rendre l'assistant observable et indépendant d'un relais personnel lorsque son usage le justifie.
- Ajouter des tests ciblés pour le Worker et les parcours critiques du site.
- Documenter une procédure de restauration et de régénération des artefacts publiés.

## Priorité 3 — Expansion du corpus

- Définir un contrat d'ingestion commun conservant source, droits, langue et provenance.
- Implémenter un premier connecteur sur une source ouverte clairement autorisée, puis mesurer qualité et coût.
- Étendre ensuite vers EUR-Lex, OCDE/OIT/OMS/OMC, ECOLEX et les Nations unies selon les droits disponibles.

## Priorité 4 — Révision communautaire

- Exposer des lots de pages `review_required` sans modifier la couche brute.
- Enregistrer toute correction comme `review_event` traçable dans une couche distincte.
- Permettre le signalement de relations et de métadonnées avec preuve source.

## Contraintes permanentes

- Aucun LLM ne corrige ou complète la transcription brute.
- Aucune page faible n'est supprimée des exports.
- Aucun statut de droits n'est inventé.
- Les gros artefacts dérivés restent hors Git et sont publiés sur les plateformes de données prévues.
- Les dépendances doivent résoudre un besoin concret et rester compatibles avec une exécution locale reproductible.
