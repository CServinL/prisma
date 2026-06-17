#!/usr/bin/env bash
# Run all test sets. Sets whose dependencies are absent are cleanly skipped.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

echo "=== mocked ==="
bash tests-sets/run-mocked.sh

echo "=== local-zotero ==="
PRISMA_CONFIG="$REPO/tests-sets/local-zotero.yaml" \
  ~/prisma/bin/pytest tests-sets/local-zotero/ -v || true

echo "=== web-api ==="
if [[ -n "${ZOTERO_API_KEY:-}" && -n "${ZOTERO_LIBRARY_ID:-}" ]]; then
  ~/prisma/bin/pytest tests-sets/web-api/ -v || true
else
  echo "  SKIPPED — ZOTERO_API_KEY / ZOTERO_LIBRARY_ID not set"
fi

echo "=== e2e ==="
~/prisma/bin/pytest tests-sets/e2e/ -v || true
