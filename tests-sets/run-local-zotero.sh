#!/usr/bin/env bash
# Run the local-zotero set — requires Zotero Desktop running at localhost:23119.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PRISMA_CONFIG="$REPO/tests-sets/local-zotero.yaml" \
  ~/prisma/bin/pytest tests-sets/local-zotero/ -v "$@"
