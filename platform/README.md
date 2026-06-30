# Lexis Mollis platform

EPIC F scaffold for the public Lexis Mollis platform:

- `site/`: Astro static site deployed through Cloudflare Workers Static Assets.
- `scripts/build_site_data.py`: release export → lightweight static JSON.
- `spaces/search/`: Hugging Face Space scaffold for hybrid search.
- `spaces/sparql/`: optional read-only SPARQL Space scaffold.

## Cloudflare setup

Preferred setup if Cloudflare lets you choose the site root:

```text
Root directory: platform/site
Build command: npm ci && npm run build
Deploy command: npx wrangler deploy
```

If Cloudflare ignores the site root or starts installing the Python package with
`pip install .`, use the repository root instead:

```text
Root directory: /
Build command: npm ci && npm run build
Deploy command: npm run deploy
```

The root-level `package.json` and `wrangler.jsonc` delegate to `platform/site` and deploy
`platform/site/dist`.
The committed `.npmrc` files force npm to include optional native dependencies, which is
needed for Astro/Rolldown on Cloudflare Linux builds.

The site deploys with `wrangler.jsonc`:

```jsonc
{
  "name": "lexis-mollis",
  "compatibility_date": "2026-06-30",
  "assets": {
    "directory": "./dist"
  }
}
```

## Local build

```bash
.venv/bin/python platform/scripts/build_site_data.py \
  --release outputs_v2/release_pilot \
  --site platform/site/public/data \
  --max-documents 500

cd platform/site
npm ci
npm run build
npx wrangler deploy --dry-run
```

Root-level equivalent, matching the fallback Cloudflare setup:

```bash
npm ci
npm run build
npm run deploy -- --dry-run
```

The committed `site/public/data` folder contains a tiny sample dataset so Cloudflare can
build even before the full OCR/release export is ready.

## Hugging Face Spaces

Search Space:

```bash
cd platform/spaces/search
python -m pip install -r requirements.txt
uvicorn app:app --reload --port 7860
```

SPARQL Space:

```bash
cd platform/spaces/sparql
python -m pip install -r requirements.txt
uvicorn app:app --reload --port 7861
```

Both services are public-data only and require no secrets for the initial scaffold.
