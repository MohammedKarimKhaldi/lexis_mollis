# Lexis Mollis — statut de déploiement

Cinquième mise à jour du 2026-07-06 (Claude) : correctif de péremption du relais. Bug trouvé en
conditions réelles : `run_relay_stack.sh` n'enregistrait l'URL du tunnel qu'une seule fois, à sa
première détection — un tunnel stable garde la même URL indéfiniment, donc l'horodatage stocké
dans `RELAY_STATE` (KV) n'était jamais rafraîchi, et au bout de `RELAY_STALE_MS` (10 min, `ask.ts`)
le Worker traitait un relais parfaitement fonctionnel comme hors ligne. Correctif : la boucle
ré-enregistre désormais aussi en heartbeat toutes les `HEARTBEAT_INTERVAL_SECONDS` (240 s par
défaut, largement sous les 10 min, surchageable via `LEXIS_RELAY_HEARTBEAT_SECONDS`), pas
seulement quand l'URL change. Testé dans le sandbox avec un intervalle raccourci (6 s) sur une
fenêtre de 20 s : 2 enregistrements confirmés, prouvant le heartbeat. Autres incidents résolus en
conditions réelles pendant ce déploiement : compte Cloudflare local (`wrangler login`) différent
du compte propriétaire du Worker (`wrangler whoami` vs l'id de compte dans les erreurs de déploi) ;
processus orphelins du relais/tunnel survivant à la mort du script orchestrateur (terminal fermé
sans passer par le trap `EXIT`) ; `python3` résolu différemment sous `launchd` (PATH minimal, sans
les fichiers de profil du shell) que dans un terminal interactif, faisant échouer `import requests`
tant que le bon interpréteur n'a pas le paquet installé. Tous documentés ici pour référence future.

Quatrième mise à jour du 2026-07-06 (Claude) : relais multi-machines, sans accès Cloudflare
requis pour qui l'exécute. L'utilisateur veut qu'un ami puisse faire tourner le relais depuis
son propre ordinateur (même token OpenCode) avec une seule commande, sans lui donner accès au
compte Cloudflare. Auparavant, `run_relay_stack.sh` appelait `npx wrangler secret put RELAY_URL`
— nécessitait d'être authentifié sur le compte Cloudflare de l'utilisateur, donc impossible à
partager tel quel. Changement : nouvel endpoint `POST /api/relay/register` sur le Worker
(`platform/site/worker/ask.ts`), protégé par `RELAY_SHARED_SECRET` (secret Worker déjà existant,
moins sensible que la clé OpenCode — partageable). Le relais qui s'enregistre le plus récemment
(champ `RELAY_STATE`, binding KV Cloudflare, clé `active_relay`, horodaté) devient le backend
actif ; une entrée de plus de 10 min (`RELAY_STALE_MS`) est considérée hors ligne plutôt que
d'essayer une URL morte. `run_relay_stack.sh` ne fait plus qu'un `curl` vers cet endpoint après
avoir détecté l'URL du tunnel — aucune dépendance Cloudflare/wrangler pour qui exécute le script,
seulement `python3`, `pip install requests` et `cloudflared`. Le script ne dépend plus non plus du
`.venv` complet du projet (`scripts/llm_relay.py` n'a besoin que de la stdlib + `requests`) — donc
un ami n'a besoin que de deux fichiers (`llm_relay.py`, `run_relay_stack.sh`), pas de tout le
dépôt. Ordre de résolution du backend dans `ask.ts` : KV (`RELAY_STATE`, dynamique, multi-
machines) → secret statique `RELAY_URL` (ancien mode mono-machine, conservé pour compatibilité)
→ appel direct `OPENCODE_API_KEY` (probablement throttlé) → message d'erreur explicite.
Reste à faire par l'utilisateur (hors d'atteinte d'un agent sandboxé — nécessite son compte
Cloudflare) :
```bash
npx wrangler kv namespace create RELAY_STATE
# coller l'id imprimé dans wrangler.jsonc ET platform/site/wrangler.jsonc (placeholder
# REPLACE_WITH_KV_NAMESPACE_ID dans les deux fichiers)
cd platform/site && npm run build && npx wrangler deploy
```
`RELAY_SHARED_SECRET` reste le même qu'avant (déjà posé comme secret Worker) — c'est cette même
valeur qu'il faut donner à quiconque doit pouvoir exécuter `run_relay_stack.sh` (avec sa propre
copie de `OPENCODE_API_KEY`, ou la même si elle est explicitement partagée). Testé dans le sandbox
avec un faux serveur imitant le Worker (autorisation 401 sur mauvais secret, enregistrement 200 sur
bon secret, valeur transmise correctement) ; la création réelle du namespace KV et le déploiement
restent à faire par l'utilisateur.

Troisième mise à jour du 2026-07-06 (Claude) : automatisation complète du relais résidentiel.
L'utilisateur a explicitement refusé de passer à Cloudflare Workers AI (qui aurait supprimé toute
dépendance à sa machine mais changé de modèle par rapport à `big-pickle`/OpenCode Zen) et refusé
de devoir manuellement ouvrir des terminaux à chaque fois. Solution : `scripts/
run_relay_stack.sh`, orchestrateur qui lance `scripts/llm_relay.py` + `cloudflared tunnel` et
met à jour lui-même le secret Worker `RELAY_URL` à chaque nouvelle URL `*.trycloudflare.com`
(parsée depuis le log du tunnel, `wrangler secret put RELAY_URL` appelé automatiquement via
stdin) — plus besoin de copier-coller l'URL manuellement à chaque redémarrage. `scripts/
com.lexismollis.relay.plist` : agent `launchd` macOS qui démarre ce script à la connexion et le
relance s'il plante (`KeepAlive`), pour un fonctionnement permanent sans terminal ouvert au
quotidien (la machine doit rester allumée et connectée — c'est le compromis assumé pour garder
OpenCode Zen/`big-pickle` plutôt que Workers AI). Logs dans `~/Library/Logs/lexis-mollis-relay/`.
Testé dans le sandbox avec de faux `cloudflared`/`npx wrangler` (parsing d'URL, appel de
`wrangler secret put` avec la bonne valeur, déduplication pour ne pas rappeler à chaque itération
de la boucle) ; l'installation réelle du launchd agent et le premier tunnel réel restent à faire
par l'utilisateur (hors d'atteinte d'un agent sandboxé — nécessite son compte Homebrew/
Cloudflare/macOS). `RELAY_SHARED_SECRET` reste un secret fixe à poser une seule fois
manuellement (il ne change pas comme `RELAY_URL`, donc pas besoin de l'automatiser).

Seconde mise à jour du 2026-07-06 (Claude) : relais résidentiel pour contourner le throttling
Cloudflare d'OpenCode Zen documenté ci-dessous. Après avoir configuré `OPENCODE_API_KEY` comme
secret Worker, l'appel direct depuis `/assistant/` reste probablement bloqué par
`FreeUsageLimitError` (IP Workers throttlée, pas la clé). Nouveau `scripts/llm_relay.py` : petit
serveur HTTP (stdlib + `requests` uniquement, aucune dépendance supplémentaire) tournant sur une
machine résidentielle, exposé publiquement via un tunnel Cloudflare (`cloudflared tunnel --url
http://127.0.0.1:8799`, tunnel éphémère sans domaine requis). La clé OpenCode ne quitte jamais
cette machine — elle n'est plus un secret Cloudflare dans ce mode ; le Worker authentifie ses
requêtes vers le relais avec un secret différent (`RELAY_SHARED_SECRET`). `platform/site/worker/
ask.ts` essaie `RELAY_URL`/`RELAY_SHARED_SECRET` en priorité, puis retombe sur l'appel direct
(`OPENCODE_API_KEY`) si le relais n'est pas configuré — aucune régression pour qui n'a pas encore
mis en place le relais. Testé en local dans le sandbox avec un faux serveur OpenCode (vérifie
auth 401, validation 400, transmission correcte du modèle/de la clé, réponse 200) ; le tunnel et
l'appel réel à OpenCode Zen restent à vérifier en conditions réelles par l'utilisateur.
Configuration à faire par l'utilisateur (nécessite sa machine + son compte Cloudflare, hors
d'atteinte d'un agent sandboxé) :
```bash
export OPENCODE_API_KEY=...
export RELAY_SHARED_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(24))")
.venv/bin/python scripts/llm_relay.py &
cloudflared tunnel --url http://127.0.0.1:8799   # imprime https://xxxx.trycloudflare.com
cd platform/site
npx wrangler secret put RELAY_URL                # coller .../ask
npx wrangler secret put RELAY_SHARED_SECRET      # coller la même valeur que ci-dessus
```
Point de vigilance : ce mode exige que la machine et `cloudflared` restent actifs pour que
`/assistant/` fonctionne en production ; l'URL `trycloudflare.com` change à chaque redémarrage du
tunnel (secret `RELAY_URL` à remettre à jour en conséquence). Choix délibéré de l'utilisateur
(plutôt que changer de modèle ou rester local uniquement) pour garder `big-pickle` gratuit sans
exposer la clé OpenCode à Cloudflare.

Mise à jour du 2026-07-06 (Claude) : amélioration du graphe de similarité pour que l'assistant
gratuit (`scripts/rag_ask.py`, `/assistant/`) puisse répondre précisément à des questions
comparatives comme « compare les types de documents (traité, accord, déclaration) et dis-moi
s'il y a des différences de forme/rédaction ». Constat de départ : la similarité/le graphe ne
capturaient que la proximité sémantique/lexicale entre chunks — aucune donnée agrégée sur la
forme/rédaction typique par `doc_type`, donc une question comparative n'obtenait qu'une poignée
de chunks retrouvés par recherche sémantique brute, potentiellement tous du même type.
Changements :
- Nouveau module `pdfkb/similarity/doc_type_profiles.py` (+ `scripts/build_doc_type_profiles.py`
  pour le régénérer sans refaire tout le build) : calcule, par `doc_type`, des statistiques
  réelles sur le corpus OCR (fraction de documents avec préambule « pleins pouvoirs », clause
  « Considérant que », formule « sont convenus… », structure en articles numérotés (+ moyenne
  d'articles/document), clause « En foi de quoi », clause de lieu/date, mention de ratification,
  clause d'entrée en vigueur, clause de dénonciation…) et une narration française générée à partir
  de ces chiffres. Sorties vérifiées sur les 3 146 documents : les trois types de l'exemple
  ci-dessus ont des profils nettement différenciés (ex. structure en articles numérotés : 79,3 %
  pour Accord contre 15,1 % pour Déclaration ; mention de ratification : 75,9 % pour Traité contre
  12,9 % pour Accord). Nouveau livrable `outputs_v2/similarity/doc_type_profiles.json`, généré
  automatiquement par `pdfkb similarity build` (`pdfkb/similarity/run.py`) et copié dans
  `outputs_v2/release/` par `scripts/build_release_tables.py`. Testé (`tests/test_similarity.py`,
  1 nouveau test, tous verts).
- `scripts/rag_ask.py` (local) et `platform/site/worker/ask.ts` (site) détectent maintenant les
  questions de comparaison (≥2 `doc_type` connus nommés dans la question) et construisent un
  contexte différent : les profils agrégés des types cités, plus une recherche stratifiée *par
  type* (au lieu d'un top-k global qui pouvait écraser les types sous-représentés — 152
  « Déclaration » contre 807 « Autre ») pour fournir de vrais extraits de chaque type. Le prompt
  système demande explicitement au modèle de citer les pourcentages exacts plutôt qu'une
  impression générale. Publication côté site : `platform/scripts/build_site_data.py` écrit une
  copie allégée dans `platform/site/public/data/doc_type_profiles.json`.
- Identifiant de modèle OpenCode Zen restauré à `big-pickle` dans les deux fichiers (une
  expérimentation locale non committée l'avait basculé sur `deepseek-v4-flash-free` pour tester
  le throttling Workers documenté ci-dessous — sans effet, donc annulée).
- Reste à faire pour aller plus loin : régénérer `outputs_v2/release` et
  `platform/site/public/data/` avec `scripts/build_release_tables.py` puis
  `platform/scripts/build_site_data.py` pour publier `doc_type_profiles.json` sur le site en
  production (généré ici en local uniquement, dans `outputs_v2/similarity/`) ; étoffer la liste de
  marqueurs si d'autres questions comparatives récurrentes apparaissent.

Dernière mise à jour vérifiée précédente : 2026-07-01 (Codex : évaluation LLM provisoire, graphe/release complets, dataset Hugging Face publié, site Cloudflare déployé, release GitHub `v0.1.0` créée).

Troisième mise à jour du même jour (Claude) : ajout d'un assistant de question/réponse gratuit
sur le corpus, en deux volets.
- **Local (`scripts/rag_ask.py`)** : recherche vectorielle locale et gratuite (FAISS +
  sentence-transformers/LaBSE déjà construits dans `outputs_v2/similarity/`), enrichie par le
  graphe de connaissances (`outputs_v2/graph/`), puis appel du modèle gratuit `big-pickle`
  d'OpenCode Zen pour la réponse finale. Bug macOS trouvé et corrigé : FAISS et PyTorch chargés
  dans le même process s'y font planter (segfault) sauf à forcer FAISS en mono-thread et
  `KMP_DUPLICATE_LIB_OK=TRUE`.
- **En ligne (`/assistant/`, `platform/site/worker/ask.ts`)** : le site n'était que des assets
  statiques Cloudflare (pas de logique serveur) — ajout d'un Worker (`main` dans `wrangler.jsonc`,
  toujours combiné aux `assets` existants) qui gère `/api/ask` et sert le reste normalement via
  `env.ASSETS.fetch()`. Recherche par recouvrement de mots-clés sur un petit index pré-calculé au
  build (`platform/scripts/build_site_data.py` écrit `ask_index.json`, ~1,5 Mo), enrichissement
  par documents similaires (déjà présents dans les fiches JSON), puis appel serveur du même modèle
  `big-pickle` — la clé API reste un secret Cloudflare (`wrangler secret put OPENCODE_API_KEY`),
  jamais exposée au navigateur.
  Bug de production trouvé et corrigé : la première version indexait le corpus complet avec
  MiniSearch à chaque requête, ce qui dépassait le quota CPU du palier gratuit Workers (erreur
  Cloudflare 1102) — remplacé par le petit index pré-calculé + un score de recouvrement de mots
  simple, sans bibliothèque de recherche en texte intégral côté Worker.
  Identifiant de modèle correct découvert par tâtonnement : `big-pickle` (pas `opencode/big-pickle`
  malgré la documentation/les résultats de recherche web) — vérifié via `GET
  https://opencode.ai/zen/v1/models`.

Seconde mise à jour du même jour (Claude) : après le premier correctif du graphe, l'utilisateur
a signalé que `/graphe/` restait bloqué sur « Chargement du graphe… » en test réel, et a demandé
un rendu plus moderne. Deux changements ont été faits dans
`platform/site/src/components/GraphView.astro` :
1. Ajout d'une gestion d'erreur explicite (sonde WebGL, timeout réseau de 30 s sur le fetch,
   `try/catch` autour de toute l'initialisation) qui affiche désormais un message d'erreur
   visible et un bouton « Réessayer » au lieu d'un spinner infini silencieux en cas d'échec —
   utile pour diagnostiquer si le problème revient.
2. Un bug introduit par ce correctif a été détecté et corrigé avant déploiement : l'overlay de
   chargement/erreur partagait une classe CSS `display: flex` qui prenait le pas sur l'attribut
   HTML `hidden` (une règle auteur bat toujours une règle user-agent, même à spécificité égale),
   ce qui aurait maintenu l'overlay visible en permanence par-dessus un graphe pourtant rendu
   correctement. Ajout de la règle `.graph-overlay[hidden] { display: none; }`. Vérifié en local
   avant déploiement : le graphe s'affiche et les 6 000 nœuds / 27 200 arêtes sont bien rendus.
3. Refonte visuelle : fond canevas sombre avec dégradés colorés, nouvelle palette de couleurs
   par type d'entité, labels dessinés sur des pastilles arrondies (au lieu de texte brut qui se
   chevauchait), effet de survol, entrée animée de la caméra, arêtes atténuées hors focus.

Redéploiement vérifié : `https://lexis-mollis.mk-74a.workers.dev`, Version ID
`7c43c68d-4dc4-4b8c-9a4d-64d210f1a028`. Si le graphe reste bloqué malgré ce correctif dans un
navigateur donné, l'overlay affiche maintenant un message d'erreur exploitable (au lieu de rien) —
le récupérer pour diagnostiquer la cause exacte (WebGL désactivé, réseau, etc.).

Mise à jour du même jour (Claude) : le graphe interactif `/graphe/` ne s'affichait en réalité
jamais en production — un bug bloquant faisait que Sigma.js levait une exception silencieuse
dès l'initialisation (`could not find a suitable program for node type "Document"`), la page
restant figée sur « Chargement du graphe… » sans qu'aucune erreur ne soit visible sans ouvrir
la console. Trois bugs cumulés ont été corrigés dans `platform/site/src/components/GraphView.astro` :
1. le champ `type` des nœuds/arêtes est réservé en interne par Sigma pour choisir le programme
   de rendu WebGL — l'écraser avec des valeurs métier (`Document`, `similar_to`, …) faisait
   planter le constructeur ; renommé en `entityType`/`edgeType`.
2. les coordonnées de layout ne sont pas dans `[0,1]` alors que la caméra par défaut de Sigma
   est centrée sur `(0.5, 0.5)` avec un ratio de 1 — sans normalisation explicite, seule une
   infime tranche du graphe était cadrée. Coordonnées renormalisées à l'affichage.
3. le champ `size` des nœuds est un compteur de connexions non borné (jusqu'à 1 113 pour les
   nœuds les plus centraux) utilisé tel quel comme rayon en pixels — quelques nœuds hubs
   recouvraient tout le canevas. Passage à une échelle en racine carrée bornée (3–18 px).

En même temps, `platform/scripts/build_site_data.py::reduce_graph` a été réécrit : l'ancienne
troncature positionnelle (`nodes[:max_nodes]`) supprimait silencieusement tous les nœuds
d'entités (États, organisations, lieux, instruments, thèmes) dès que le nombre de documents
dépassait le plafond — le graphe publié ne contenait donc que des documents. La sélection
priorise maintenant l'ensemble des documents, puis les entités par ordre de degré pondéré, et
conserve les liens les plus forts de chaque nœud plutôt qu'un sous-ensemble arbitraire. Le
graphe publié passe de 3 000 nœuds / 9 000 arêtes (documents uniquement) à 6 000 nœuds /
27 200 arêtes couvrant les 3 146 documents, 1 201 instruments, 1 561 thèmes les plus connectés,
59 parties, 18 organisations et 15 lieux. L'UI `/graphe/` gagne aussi des filtres par type de
nœud/lien, un seuil de similarité minimale, et une mise en évidence des voisins directs au clic
(pour explorer les documents similaires). Vérifié en local (Astro preview) puis déployé sur
Cloudflare : `https://lexis-mollis.mk-74a.workers.dev/data/manifest.json` annonce
`graph_node_count: 6000`, `graph_edge_count: 27200`.

## Résumé

**L'OCR est terminé.** Le run est sorti avec `status=0` à 22:23:22+0100 :
3 146/3 146 documents exportés, 26 566 pages, 0 document incomplet, 0 erreur.
**L'audit complet a déjà tourné sur l'ensemble du corpus** dans la foulée :
`outputs_v2/kb/pages.jsonl` et `outputs_v2/audit/pages.jsonl` contiennent chacun
26 566 lignes, `outputs_v2/clean/` et `outputs_v2/raw/` contiennent chacun 3 146
fichiers Markdown. Le blocage « attendre la fin de l'OCR » des versions précédentes de
ce document n'existe donc plus.

Le socle local est opérationnel : pipeline OCR v2, schémas, similarité, knowledge graph,
outillage de release et CI GitHub. Le dépôt GitHub est public, le dataset Hugging Face
`lexis-mollis/soft-law-corpus` existe et est public, et Zenodo est connecté à GitHub selon
la configuration effectuée côté compte.

Le scaffold EPIC F n'est plus seulement testable localement : il a été alimenté depuis
`outputs_v2/release` et déployé sur Cloudflare Workers Static Assets. Le site public est :
`https://lexis-mollis.mk-74a.workers.dev`. Le manifeste public
`/data/manifest.json` annonce 3 146 documents, 26 566 pages, un graphe réduit à
6 000 nœuds et 27 200 arêtes pour l'affichage navigateur (documents, instruments, thèmes,
parties, organisations et lieux — voir la note de mise à jour ci-dessus). Les exports lourds restent hors
Git et hors bundle statique complet ; Hugging Face est maintenant la cible canonique publiée
pour les tables complètes, et Zenodo reste la cible DOI après release GitHub.

Une passe d'amélioration UI a aussi été faite sur `platform/site/src/` (favicon + balises
OG/Twitter, état actif dans la navigation, pied de page avec liens GitHub/Hugging Face,
légende des couleurs du graphe, recherche avec état de chargement + debounce, secours
`<noscript>` pour recherche/graphe, et surtout un sommaire + regroupement par paquets de
25 pages (`<details>`) sur les fiches document longues. Build Astro vérifié en local et
déployé sur Cloudflare avec les données complètes optimisées.

Le build **complet** de similarité a maintenant été lancé sur les 3 146 documents :
`outputs_v2/similarity/manifest.json` indique 30 285 chunks, 24 446 paires lexicales,
461 840 paires sémantiques, 310 098 arêtes chunk, 87 451 arêtes document et 116 clusters.
À la demande de l'utilisateur, Codex a rempli automatiquement toute la shortlist de
calibration comme **brouillon d'annotation LLM** : `benchmarks/similarity_cases.json`
contient maintenant 120 candidats annotés, dont 54 positifs, 50 négatifs et 16 exclus
comme non informatifs (numéros de page, renvois mécaniques, fragments trop courts).
`scripts/calibrate_similarity.py` marque explicitement ce rapport comme
`llm_draft_calibrated`, avec `human_validated=false`. Les seuils proposés sont donc utiles
pour avancer l'ingénierie, mais ne doivent pas être présentés comme une calibration
scientifique validée humainement.

Les gazetteers ont été enrichis avec les entités évidentes, puis le graphe et la release
ont été reconstruits sur le corpus complet. `benchmarks/gazetteer_candidates_llm_review.csv`
contient l'annotation LLM-draft des 300 candidats gazetteer restants. Après enrichissement,
`outputs_v2/graph/summary.json` indique 8 441 nœuds, 104 206 arêtes, 2 011 nœuds
provisoires et 12 786 arêtes provisoires.
`outputs_v2/release/release_manifest.json` indique 3 146 documents, 26 566 pages,
30 285 chunks, 414 304 arêtes et 8 441 nœuds.

Ce qui reste avant une publication académique vraiment solide : remplacer ou confirmer
les annotations LLM par une validation humaine, valider un échantillon de mentions d'entités,
puis reporter le DOI Zenodo lorsqu'il sera visible.

## État vérifié

| Élément | Statut | Preuve / note |
|---|---:|---|
| GitHub repo | OK | `MohammedKarimKhaldi/lexis_mollis`, public, branche `main`; PR #1 fusionnée dans `main` via `7c198a58fd2eca2e8b19834e1dff6b903a76349e`. |
| CI GitHub | OK | Workflow `CI` actif ; dernier run vérifié en succès. |
| `HF_TOKEN` | OK ponctuel | Le token exposé initialement ne doit plus être utilisé ; l'utilisateur a relancé l'upload avec un token corrigé. Ne pas stocker de token dans Git. |
| Hugging Face dataset | **Publié** | `lexis-mollis/soft-law-corpus`, public, non gated, non disabled ; 13 fichiers attendus visibles, manifest HF vérifié : 3 146 documents, 26 566 pages, 30 285 chunks, 414 304 arêtes, 8 441 nœuds. Commit HF vérifié : `bf89fd4aafcb905baaa0d54e1b171a7b9e65121a`. |
| GitHub release | **Créée** | Release publique `v0.1.0` : `https://github.com/MohammedKarimKhaldi/lexis_mollis/releases/tag/v0.1.0`. |
| Zenodo | En attente | `.zenodo.json` cohérent avec `CITATION.cff`, mais aucun record Zenodo public trouvé après création de la release. À vérifier dans le tableau de bord Zenodo GitHub. |
| Cloudflare | **Déployé** | Worker `lexis-mollis` déployé sur `https://lexis-mollis.mk-74a.workers.dev` ; `/`, `/recherche/`, `/graphe/` et `/data/manifest.json` vérifiés en HTTP 200. Config Git Cloudflare préférée : root `platform/site`, build `npm ci && npm run build`, deploy `npx wrangler deploy`. |
| Site local | OK | Build Astro complet vérifié ; `platform/site/public/data/manifest.json` annonce 3 146 documents, 26 566 pages, graphe réduit 6 000 nœuds / 27 200 arêtes (documents + entités, tous types représentés). |
| Branch protection | À configurer | Pas encore de protection `main`/required checks. |
| OCR | **Terminé** | 3 146/3 146 documents, 26 566 pages, 0 erreur, run sorti `status=0`. |
| Audit complet | **Terminé** | `outputs_v2/kb/` et `outputs_v2/audit/` régénérés sur le corpus complet (26 566 lignes chacun), 6 084 pages en file de révision (`outputs_v2/review_queue.csv` : 6 085 lignes avec en-tête). |
| Similarité complète | **Construite, calibrage LLM-draft complet** | `outputs_v2/similarity/` : 30 285 chunks, 87 451 arêtes document, 116 clusters. `benchmarks/similarity_cases.json` contient 120 candidats annotés : 54 positifs, 50 négatifs, 16 exclus ; `calibration_report.json` = `llm_draft_calibrated`, `human_validated=false`. |
| Gazetteers / graphe | **Graphe complet construit** | Gazetteers enrichis à 92 entrées ; `outputs_v2/graph/summary.json` : 8 441 nœuds, 104 206 arêtes. Annotation LLM des 300 candidats restants dans `benchmarks/gazetteer_candidates_llm_review.csv`. Reste : validation humaine d'un échantillon d'entités avant revendication scientifique. |

## Statut par epic

| Epic | Statut | Bloqué par / reste à faire |
|---|---:|---|
| A — Infrastructure & gouvernance | Partiel avancé | GitHub public OK, dataset HF publié, CI OK, release GitHub `v0.1.0` créée. Reste : branch protection, éventuelle org GitHub `lexis-mollis`, DOI Zenodo si le webhook a bien archivé la release. |
| B — Modèle de données & standards | Fait | Schémas, taxonomie, ontologie, identifiants et validation automatisée en place. |
| C — Similarité | Build complet fait, calibration LLM-draft | `outputs_v2/similarity/` construit sur 3 146 documents. Fix appliqué : IDs de chunks document-scoped pour conserver les alias de PDF exacts ; scores FAISS clampés à `[0,1]`. `benchmarks/similarity_cases.json` contient 54 positifs / 50 négatifs / 16 exclus évalués par Codex. Reste : validation humaine si publication scientifique. |
| D — Knowledge graph | **Complet provisoire construit** | Gazetteers enrichis et graphe complet construit : 8 441 nœuds, 104 206 arêtes, 114 963 mentions. Reste : validation humaine d'au moins 50 mentions si revendication scientifique. |
| E — Export & publication | **HF publié ; release GitHub créée** | `outputs_v2/release` construit sur 3 146 documents / 26 566 pages ; `outputs_v2/hf_dataset` préparé localement puis publié sur `lexis-mollis/soft-law-corpus`; GitHub release `v0.1.0` créée. Reste : vérifier/récupérer le DOI Zenodo, puis le reporter dans `CITATION.cff`, `README.md` et la card Hugging Face. |
| F — Plateforme web | **Déployé avec données complètes optimisées ; graphe interactif corrigé** | Astro + Workers Static Assets déployé sur `https://lexis-mollis.mk-74a.workers.dev`, avec manifest complet, recherche statique, fiches document et graphe interactif désormais fonctionnel (bug Sigma.js bloquant corrigé le 2026-07-01, voir note en tête de document). Les JSON statiques complets optimisés sont versionnés pour rendre le déploiement Git reproductible. Reste : domaine personnalisé éventuel, recherche HF Space/FAISS réelle. |
| G — CI/CD | Partiel | CI qualité OK. Reste : `build-derive.yml`, `release.yml`, `deploy-site.yml`, `keepalive.yml`. |
| H — Expansion corpus | Non commencé | Choisir et implémenter le premier connecteur, probablement EUR-Lex, avec droits/provenance explicites. |
| I — Révision communauté | Non commencé | Générer lots de révision ; choisir mini-interface Astro ou workflow issues GitHub ; stocker `review_events.jsonl`. |

## Base de données publique & affichage — plan verrouillé

Décision d'architecture : **Hugging Face Dataset est la source canonique complète** et
Cloudflare reste la vitrine publique optimisée. Les exports lourds (`outputs_v2/release`,
Parquet, RDF, embeddings, index FAISS) ne sont pas committés dans Git ; ils sont publiés via
Hugging Face/Zenodo, tandis que le site charge des JSON statiques réduits produits depuis la
release.

Flux prévu :

État actuel : les étapes 1 à 3 ont été exécutées automatiquement avec une annotation
LLM-draft, pas une validation humaine. Cette distinction est volontairement conservée dans
les fichiers de sortie et dans le rapport de calibration.

1. Calibration de similarité :
   - fait en brouillon LLM sur toute la shortlist : 54 cas positifs, 50 cas négatifs et
     16 cas exclus dans `benchmarks/similarity_cases.json` ;
   - `outputs_v2/similarity/calibration_report.json` signale
     `status=llm_draft_calibrated` et `human_validated=false` ;
   - à refaire ou confirmer humainement avant publication scientifique.
2. Gazetteers et graphe :
   - gazetteers enrichis pour les entités évidentes ;
   - annotation LLM-draft des 300 candidats restants dans
     `benchmarks/gazetteer_candidates_llm_review.csv` ;
   - graphe complet construit dans `outputs_v2/graph` ;
   - reste : audit humain d'un échantillon d'entités/relations.
3. Release complète :
   ```bash
   .venv/bin/python scripts/build_release_tables.py \
     --kb outputs_v2/kb/pages.jsonl \
     --similarity outputs_v2/similarity \
     --graph outputs_v2/graph \
     --output outputs_v2/release \
     --scope full_corpus_v0_1
   ```
   Fait : `outputs_v2/release/release_manifest.json` indique 3 146 documents et
   26 566 pages.
4. Préparer puis publier la base canonique sur Hugging Face :
   ```bash
   .venv/bin/python scripts/export_hf_dataset.py --release outputs_v2/release
   .venv/bin/python scripts/export_hf_dataset.py --release outputs_v2/release --upload
   ```
   Fait le 2026-07-01 : préparation locale dans `outputs_v2/hf_dataset`, puis publication
   sur `lexis-mollis/soft-law-corpus`. Vérification publique sans token : 13 fichiers
   attendus visibles (`README.md`, `release_manifest.json`, `CHECKSUMS.sha256`, tables
   Parquet et exports `graph/`) ; commit HF `bf89fd4aafcb905baaa0d54e1b171a7b9e65121a`.
5. Générer la couche Cloudflare depuis la release :
   ```bash
   .venv/bin/python platform/scripts/build_site_data.py \
     --release outputs_v2/release \
     --site platform/site/public/data \
     --max-documents 4000 \
     --max-graph-nodes 3000 \
     --search-text-chars 1200
   ```
6. Tester et déployer :
   ```bash
   npm run build
   npx wrangler deploy --dry-run
   npx wrangler deploy
   ```
   Fait : site public `https://lexis-mollis.mk-74a.workers.dev`.

Critères d'acceptation de la base publique :

- `outputs_v2/release/release_manifest.json` indique 3 146 documents et 26 566 pages. **OK**
- Le dataset HF expose les tables `documents`, `pages`, `chunks`, `edges`, `nodes` et le
  dossier `graph/`. **OK : publication vérifiée publiquement sur
  `lexis-mollis/soft-law-corpus`.**
- Le site Cloudflare expose `manifest.json`, `documents.json`, `search.json`,
  `facets.json`, `docs/<document_id>.json` et `graph.sigma.json`. **OK**
- Les fiches documents affichent titre, type, année, langues, score qualité, statut de
  révision, texte OCR, documents similaires, licence et liens vers les données.
- Les pages faibles restent visibles avec `review_required` / `review_priority` et les
  relations incertaines restent marquées `provisional`.
- Aucun asset statique Cloudflare ne dépasse 25 MiB et le nombre de fichiers reste sous la
  limite du palier gratuit ; les gros exports complets restent servis par HF/Zenodo. **OK
  sur la génération actuelle : 3 151 fichiers de données, 75 MiB avant build.**

## Déploiement Cloudflare — configuration

Si Cloudflare demande un build command et un deploy command, utiliser :

```text
Root directory: platform/site
Build command: npm ci && npm run build
Deploy command: npx wrangler deploy
```

Si le log Cloudflare montre `Installing project dependencies: pip install .`, alors le build
part de la racine Python du dépôt au lieu de `platform/site`. Dans ce cas, utiliser la
configuration racine tolérante :

```text
Root directory: /
Build command: npm ci && npm run build
Deploy command: npm run deploy
```

Les configurations Workers Static Assets sont versionnées dans `platform/site/wrangler.jsonc`
et `wrangler.jsonc` à la racine. La configuration racine déploie `platform/site/dist`.
Le lockfile racine `package-lock.json` est nécessaire pour que `npm ci` fonctionne depuis
la racine Cloudflare. Les fichiers `.npmrc` forcent l'installation des dépendances natives
optionnelles ; les bindings Linux nécessaires à Astro, esbuild, Rolldown et Lightning CSS sont aussi
déclarés directement pour éviter les échecs de résolution optionnelle/transitive.
Les deux configurations utilisent `assets.not_found_handling = "single-page-application"` :
cela évite le 404 sur `/` et les routes Astro servies via Workers Static Assets.

Déploiement direct vérifié :

```text
URL: https://lexis-mollis.mk-74a.workers.dev
Version ID: 5eeb3783-b203-44e6-a91d-bc1355195531
Checks: /, /recherche/, /graphe/ et /data/manifest.json en HTTP 200
```

Redéploiement du 2026-07-01 (correctif graphe interactif + graphe 6 000/27 200) :

```text
URL: https://lexis-mollis.mk-74a.workers.dev
Version ID: c941dbf8-4491-4541-a1ba-85184f430b38
Checks: /, /recherche/, /graphe/, /donnees/ et /data/manifest.json en HTTP 200
/data/manifest.json: graph_node_count=6000, graph_edge_count=27200
/data/graph.sigma.json vérifié en direct : 6000 nœuds (Document 3146, TopicConcept 1561,
Instrument 1201, Party 59, Organization 18, Place 15), 27200 arêtes
```

À faire côté Cloudflare :

1. Créer ou choisir un compte Cloudflare.
2. Connecter le dépôt GitHub et choisir le root `platform/site`.
3. Déployer avec les commandes ci-dessus. Fait une première fois via Wrangler local.
4. Optionnel pour EPIC G : créer un token API Cloudflare limité au déploiement.
5. Optionnel pour GitHub Actions : ajouter les secrets :
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
6. Ajouter `deploy-site.yml` seulement si on choisit le déploiement via GitHub Actions plutôt que via l’intégration Git Cloudflare.

Commandes prévues après obtention des valeurs :

```bash
read -s CLOUDFLARE_API_TOKEN
gh secret set CLOUDFLARE_API_TOKEN --repo MohammedKarimKhaldi/lexis_mollis --body "$CLOUDFLARE_API_TOKEN"
unset CLOUDFLARE_API_TOKEN

read -r CLOUDFLARE_ACCOUNT_ID
gh secret set CLOUDFLARE_ACCOUNT_ID --repo MohammedKarimKhaldi/lexis_mollis --body "$CLOUDFLARE_ACCOUNT_ID"
unset CLOUDFLARE_ACCOUNT_ID
```

## Prochaine séquence recommandée

1. Décision appliquée : versionner aussi `platform/site/public/data/` complet optimisé
   pour que le déploiement Cloudflare Git reste reproductible, tout en gardant les gros
   artefacts (`outputs_v2`, Parquet bruts, embeddings, SQLite, PDF) hors Git.
2. Committer/pousser les changements de code, statut, annotations LLM-draft, gazetteers et
   données statiques optimisées :
   `PROJECT_STATUS.md`, `benchmarks/similarity_cases.json`,
   `benchmarks/gazetteer_candidates_llm_review.csv`, `scripts/calibrate_similarity.py`,
   `data/gazetteers/*.csv`, `wrangler.jsonc`, `platform/site/wrangler.jsonc` et
   `platform/site/public/data/`.
3. Pour une validation scientifique, remplacer le brouillon LLM par une annotation humaine :
   - relire les 120 cas dans `benchmarks/similarity_cases.json` ;
   - ajuster `label`, `expected_type` et `notes` ;
   - changer `annotation_source` seulement lorsque l'annotation est effectivement humaine.
4. Relancer la calibration après validation humaine :
   ```bash
   .venv/bin/python scripts/calibrate_similarity.py \
     --similarity-dir outputs_v2/similarity \
     --cases benchmarks/similarity_cases.json \
     --output outputs_v2/similarity/calibration_report.json
   ```
   Si les seuils changent substantiellement, re-builder la similarité puis le graphe.
5. Valider ≥50 mentions d'entités/relations dans le graphe, puis relancer si nécessaire :
   ```bash
   .venv/bin/python -m pdfkb graph build \
     --kb outputs_v2/kb/pages.jsonl \
     --similarity outputs_v2/similarity \
     --output outputs_v2/graph \
     --ontology metadata_design/ontology.ttl \
     --gazetteers data/gazetteers \
     --min-confidence 0.70 \
     --seed 20260701
   ```
6. Régénérer la release si la similarité ou le graphe changent :
   ```bash
   .venv/bin/python scripts/build_release_tables.py \
     --kb outputs_v2/kb/pages.jsonl \
     --similarity outputs_v2/similarity \
     --graph outputs_v2/graph \
     --output outputs_v2/release \
     --scope full_corpus_v0_1
   ```
7. Publier le dataset HF :
   ```bash
   .venv/bin/python scripts/export_hf_dataset.py --release outputs_v2/release --upload
   ```
   Fait : dataset publié et manifest vérifié depuis Hugging Face.
8. Créer le tag/release GitHub `v0.1.0`, récupérer le DOI Zenodo et le reporter dans
   `CITATION.cff`, `README.md` et la card Hugging Face.
   Fait côté GitHub : release `v0.1.0` publiée sur le commit
   `7c198a58fd2eca2e8b19834e1dff6b903a76349e`. En attente côté Zenodo : aucun record
   public trouvé via l'API Zenodo après le webhook ; vérifier le tableau de bord Zenodo.
9. Ajouter `deploy-site.yml` seulement si le déploiement doit passer par GitHub Actions
   plutôt que par l'intégration Git Cloudflare ou Wrangler local.

## Points de vigilance

- Ne pas publier les PDF sur Internet Archive tant que `rights_status` reste `to_review`.
- Ne pas affirmer que les seuils de similarité sont calibrés avant annotation humaine.
- Ne pas committer de secrets, sorties OCR, bases SQLite, fichiers Parquet, embeddings ou PDF.
- Le token Hugging Face exposé précédemment ne doit pas être conservé ni réutilisé ; garder
  uniquement des tokens `write` finement scoped au dataset, hors Git et hors logs.
