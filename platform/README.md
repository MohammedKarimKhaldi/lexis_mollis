# Lexis Mollis platform

EPIC F scaffold for the public Lexis Mollis platform:

- `site/`: Astro static site deployed through Cloudflare Workers Static Assets.
- `scripts/build_site_data.py`: release export → lightweight static JSON.
- `spaces/search/`: Hugging Face Space scaffold for hybrid search.
- `spaces/sparql/`: optional read-only SPARQL Space scaffold.

## Cloudflare setup

Use the Cloudflare Git screen that asks for both build and deploy commands:

```text
Root directory: platform/site
Build command: npm ci && npm run build
Deploy command: npx wrangler deploy
```

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
