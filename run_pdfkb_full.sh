#!/bin/zsh
set -u

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export TESSDATA_PREFIX="/opt/homebrew/share/tessdata"

exec >> "$SCRIPT_DIR/metadata/pdfkb_full.log" 2>&1
echo ""
echo "===== pdfkb START $(date '+%Y-%m-%dT%H:%M:%S%z') pid=$$ ====="
"$SCRIPT_DIR/.venv/bin/python" -m pdfkb run \
  --source "$SCRIPT_DIR/traites" \
  --metadata "$SCRIPT_DIR/metadata/parsed_metadata.json" \
  --output "$SCRIPT_DIR/outputs_v2" \
  --state "$SCRIPT_DIR/metadata/pipeline.sqlite3" \
  --workers 4 \
  --dpi 300 \
  --resume

STATUS=$?
echo "===== pdfkb EXIT $(date '+%Y-%m-%dT%H:%M:%S%z') status=$STATUS ====="
launchctl remove com.local.pdfkb.full >/dev/null 2>&1 || true
exit $STATUS
