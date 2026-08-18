# Lexis Mollis — état vérifié

Dernière vérification : 9 août 2026.

## Corpus et dérivés

| Élément | État vérifié |
|---|---|
| OCR | 3 146 documents exportés, 26 566 pages dans la release, 0 erreur de document |
| Similarité | 87 451 arêtes documentaires, dont 84 842 `similar_to` et 1 549 traductions |
| Graphe complet | 8 441 nœuds, 104 206 arêtes, 12 960 arêtes provisoires |
| Release | 3 146 documents, 26 566 pages, 30 285 chunks, 414 304 arêtes et 8 441 nœuds |
| Site statique | 3 146 documents, 26 566 pages, projection de 3 000 nœuds et 17 790 arêtes organisée en communautés |
| Semantica | 0.6.0 intégré ; ContextGraph complet, projection locale et API reliée à l'UI Astro |
| Version pipeline | `2.0.1` |

Les sorties complètes se trouvent localement sous `outputs_v2/` et restent hors Git. La
projection web sous `platform/site/public/data/` est versionnée pour rendre le déploiement
Cloudflare reproductible.

## Publication et déploiement

- Site : <https://lexis-mollis.mk-74a.workers.dev>
- Dataset : <https://huggingface.co/datasets/lexis-mollis/soft-law-corpus>
- Release GitHub : `v0.1.0`
- DOI Zenodo : à confirmer ou créer, puis à reporter dans `CITATION.cff`, le README et la fiche dataset

Le site Astro est servi par Cloudflare Workers Static Assets. L'assistant peut utiliser un
relais local enregistré dans KV ; sa disponibilité dépend donc du relais tant qu'aucun backend
permanent n'est choisi. L'interface est francophone, claire et compacte ; Semantica reste derrière
la vue graphe au lieu d'imposer son Explorer comme seconde UI.

## Validation technique

La vérification de référence couvre :

- lint et format Ruff sur le code Python actif ;
- 26 tests unitaires, dont 3 tests d'intégration Semantica et 1 test de projection des communautés ;
- validation de 6 schémas, 125 triplets d'ontologie, 17 namespaces et 25 mappings documentaires ;
- contrôle des fichiers de gouvernance ;
- build Astro de 3 153 pages statiques.
- aller-retour du graphe de test via le `ContextGraph` et la session Explorer Semantica ;
- parcours local vérifié : API Semantica accessible depuis l'UI et question/réponse en français sur 10 sources retenues.

## Limites connues

- Les annotations de calibration de similarité restent un brouillon LLM tant qu'elles ne sont pas relues par un humain.
- Au moins 50 mentions/relations du graphe doivent être validées humainement avant une revendication scientifique de précision.
- 6 084 pages de la release OCR sont signalées pour révision ; elles restent volontairement dans les exports.
- Les PDF ne doivent pas être publiés sur Internet Archive tant que leur `rights_status` n'est pas confirmé.
- Le DOI Zenodo n'est pas encore présent dans les métadonnées du dépôt.
- Le graphe Semantica complet est trop volumineux pour un premier rendu navigateur ; l'UI utilise donc la projection de 17 790 arêtes et interroge l'API à la demande.

## Prochaine séquence

1. Validation humaine de la similarité et des mentions du graphe.
2. Rebuild conditionnel des dérivés si les paramètres changent.
3. Publication d'une release révisée avec DOI.
4. Automatisation CI/CD et tests du Worker.
5. Premier connecteur d'expansion de corpus.
