#!/usr/bin/env bash
# Regenerate all architecture diagrams. Run from the repo root:
#   bash docs/diagrams/gen.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
rm -f docs/diagrams/*.html
for f in docs/diagrams/*.py; do
    .venv/bin/python "$f"
done
echo "done"
