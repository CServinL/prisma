#!/usr/bin/env bash
# Run the web-api set — requires ZOTERO_API_KEY and ZOTERO_LIBRARY_ID in env.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
if [[ -z "${ZOTERO_API_KEY:-}" || -z "${ZOTERO_LIBRARY_ID:-}" ]]; then
  echo "ERROR: ZOTERO_API_KEY and ZOTERO_LIBRARY_ID must be set" >&2
  exit 1
fi
~/prisma/bin/pytest tests-sets/web-api/ -v "$@"
