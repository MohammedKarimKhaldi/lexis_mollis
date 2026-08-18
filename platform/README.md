# Plateforme Lexis Mollis

La plateforme publie une projection web du corpus complet : 3 146 documents, 26 566 pages
et un sous-graphe borné pour le navigateur.

## Structure

- `site/` : site Astro statique, composants de recherche/graphe et Worker assistant ;
- `scripts/build_site_data.py` : conversion d'une release Parquet/RDF vers les JSON web ;
- `spaces/search/` : service FastAPI optionnel pour la recherche hybride ;
- `spaces/sparql/` : endpoint SPARQL public optionnel en lecture seule.

La source complète reste la release sous `outputs_v2/release` et le dataset Hugging Face.
`site/public/data/` est une projection optimisée et versionnée afin que Cloudflare puisse
reconstruire le déploiement depuis Git.

## Régénérer les données du site

```bash
.venv/bin/python platform/scripts/build_site_data.py \
  --release outputs_v2/release \
  --site platform/site/public/data \
  --max-documents 3146 \
  --max-graph-nodes 3000
```

Après génération, vérifier le manifeste, les tailles des assets et le build avant de
committer la projection.

## Build local

Depuis la racine :

```bash
npm ci
npm run build
npm run deploy -- --dry-run
```

Ou depuis `platform/site` :

```bash
npm ci
npm run build
npm run deploy:dry-run
```

Le build actuel produit 3 153 pages statiques. Les fichiers `dist/`, `.astro/` et `.wrangler/`
sont générés et ignorés par Git.

## Interface locale avec Semantica

Le site conserve une seule vue claire et légère. Les communautés Louvain sont préparées au build
dans `graph.communities.json`, puis Semantica 0.6.0 enrichit la recherche, les voisinages et la
provenance derrière cette même vue :

```bash
.venv-semantica/bin/python -m pdfkb semantica export \
  --input platform/site/public/data/graph.sigma.json \
  --output outputs_v2/graph/graph.semantica.web.json

.venv-semantica/bin/python -m pdfkb semantica serve \
  --graph outputs_v2/graph/graph.semantica.web.json \
  --no-browser
```

Dans un second terminal, construire et lancer le site avec son Worker :

```bash
npm run build
cd platform/site
npx wrangler dev --port 8787
```

L'interface complète est disponible sur <http://127.0.0.1:8787>. La page `/graphe/` détecte
l'API Semantica sur le port 8000 et affiche discrètement `Semantica actif`. L'Explorer officiel
servi sur le port 8000 reste disponible pour le diagnostic, mais l'utilisateur n'a pas à changer
d'interface. L'assistant reçoit les questions en français naturel et répond en français par
défaut. Le serveur Astro seul sur le port 4321 reste utile pour travailler l'UI, mais ne fournit
pas l'endpoint Worker de l'assistant.

Le graphe complet peut aussi être exporté avec `python -m pdfkb semantica export`. Il contient
104 206 relations ; la projection web de 17 790 relations est le meilleur point d'entrée
interactif, tandis que le graphe complet reste disponible pour les traitements hors navigateur.

## Cloudflare

Configuration recommandée :

```text
Root directory: platform/site
Build command: npm ci && npm run build
Deploy command: npx wrangler deploy
```

La configuration racine est également supportée par `package.json` et `wrangler.jsonc`.
Les deux fichiers Wrangler doivent conserver le même binding KV `RELAY_STATE`.

Le Worker `site/worker/ask.ts` sert les assets statiques et ajoute les endpoints de
l'assistant/relais. Les secrets restent dans Cloudflare ou `.dev.vars`, jamais dans Git.

## Hugging Face Spaces optionnels

```bash
cd platform/spaces/search
python -m pip install -r requirements.txt
uvicorn app:app --reload --port 7860
```

```bash
cd platform/spaces/sparql
python -m pip install -r requirements.txt
uvicorn app:app --reload --port 7861
```

Ces services consomment uniquement les données publiques et ne sont pas requis pour le
fonctionnement de base du site statique.
