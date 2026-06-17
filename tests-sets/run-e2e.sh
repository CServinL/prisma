#!/usr/bin/env bash
# Run e2e tests — requires internet, Ollama, and Zotero Web API creds.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
~/prisma/bin/pytest tests-sets/e2e/ -v "$@"
