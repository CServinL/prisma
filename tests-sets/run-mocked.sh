#!/usr/bin/env bash
# Run the mocked test set — no network, no Zotero, no Ollama required.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
unset PRISMA_CONFIG
~/prisma/bin/pytest tests-sets/mocked/ -v "$@"
