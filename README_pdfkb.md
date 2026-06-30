# PDFKB — pipeline OCR fidèle et auditable

`pdfkb` construit une double couche de texte à partir des PDF de `traites/` sans modifier
les PDF ni les anciennes sorties de `extracted/`.

## Exécution complète

Utiliser impérativement l'environnement virtuel du projet :

```bash
.venv/bin/python -m pdfkb run \
  --source traites \
  --metadata metadata/parsed_metadata.json \
  --output outputs_v2 \
  --state metadata/pipeline.sqlite3 \
  --workers 2 \
  --dpi 300 \
  --resume
```

L'état est sauvegardé après chaque page. La même commande reprend automatiquement les
pages manquantes. Un changement de version du pipeline force le recalcul concerné ; un échec
de recalcul ne remplace jamais un résultat antérieur valide.

Le traitement intégral actuellement lancé comme tâche macOS peut être suivi avec :

```bash
tail -f metadata/pdfkb_full.log
launchctl print "gui/$(id -u)/com.local.pdfkb.full"
.venv/bin/python -m pdfkb status --state metadata/pipeline.sqlite3
```

Pour l'arrêter proprement — les pages terminées resteront sauvegardées — utiliser :

```bash
launchctl remove com.local.pdfkb.full
```

Pour le relancer en arrière-plan :

```bash
launchctl submit -l com.local.pdfkb.full -- "$PWD/run_pdfkb_full.sh"
```

Pour un pilote ciblé :

```bash
.venv/bin/python -m pdfkb run \
  --source traites \
  --metadata metadata/parsed_metadata.json \
  --output outputs_v2 \
  --state metadata/pipeline.sqlite3 \
  --documents TRA20182386_001_s1,tra19780213_003_s1 \
  --workers 2 --dpi 300 --resume
```

## Livrables

- `outputs_v2/raw/*.md` : transcription sélectionnée, page par page.
- `outputs_v2/clean/*.md` : normalisation déterministe pour la recherche.
- `outputs_v2/kb/pages.jsonl` : enregistrements prêts à ingérer.
- `outputs_v2/audit/pages.jsonl` : candidats OCR, blocs, scores et transformations.
- `outputs_v2/review_queue.csv` : pages à contrôler, sans exclusion de l'export KB.
- `outputs_v2/audit/review_images/` : images réduites des pages signalées.
- `outputs_v2/comparison_report.{json,md}` : comparaison avec `extracted/`.
- `outputs_v2/manifest.json` : compte des documents, pages et erreurs.

Le fichier SQLite est la source de vérité technique. Les Markdown et JSONL peuvent être
reconstruits sans refaire l'OCR :

```bash
.venv/bin/python -m pdfkb audit \
  --state metadata/pipeline.sqlite3 \
  --output outputs_v2
```

Pendant que l'OCR complet tourne, préférer un snapshot léger vers un dossier séparé. Il
exporte les documents complets, `raw/`, `clean/`, `kb/pages.jsonl`, `review_queue.csv` et
`manifest.json`, mais évite le lourd `audit/pages.jsonl` détaillé :

```bash
nice -n 10 .venv/bin/python -m pdfkb audit \
  --state metadata/pipeline.sqlite3 \
  --output outputs_live \
  --light
```

## Validation

```bash
.venv/bin/python -m unittest discover -v
.venv/bin/python -m pdfkb benchmark \
  --source traites \
  --cases benchmarks/cases.json \
  --dpi 200 \
  --report outputs_v2/benchmark_report.json
```

Le benchmark couvre notamment une couche native, un imprimé moderne, le cyrillique, le
chinois, une page presque vide et un manuscrit historique.

## Politique de fidélité

- Aucun LLM ne corrige ou ne reformule le contenu.
- La couche brute reste intacte ; seules les sorties `clean/` reçoivent les transformations
  déterministes documentées dans l'audit.
- Une qualité inférieure à `0,85`, un désaccord entre moteurs ou une page visuellement non
  vide sans texte déclenche une révision.
- Les pages signalées restent dans `kb/pages.jsonl` avec `review_required=true`.
- Les manuscrits et scans très dégradés ne sont jamais présentés comme fiables sur la seule
  base du nombre de caractères reconnus.
