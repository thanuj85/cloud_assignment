#!/usr/bin/env bash
# report/report.md -> report/report.pdf  (pandoc for the HTML, headless Chrome for the PDF)
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
OUT="report/report.pdf"
HTML="$(mktemp -d)/report.html"

pandoc report/report.md \
  --standalone \
  --css "$(pwd)/report/report.css" \
  --embed-resources \
  -o "$HTML"

"$CHROME" --headless --disable-gpu --no-sandbox --no-pdf-header-footer \
  --virtual-time-budget=10000 \
  --print-to-pdf="$OUT" "file://$HTML" 2>/dev/null

echo "wrote $OUT"
