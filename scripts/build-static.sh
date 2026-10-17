#!/usr/bin/env bash
# Build the PHP-free copy of the page into dist/static/ and serve it at http://localhost:8081/
# Usage: scripts/build-static.sh [--models /path/to/onnx]   (add --serve to start the server)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python3
test -x .venv/bin/python && PY=.venv/bin/python
serve=0
args=()
for a in "$@"; do
  if [ "$a" = "--serve" ]; then serve=1; else args+=("$a"); fi
done
"$PY" -I tools/build_static.py "${args[@]}" || true
if [ "$serve" = 1 ]; then exec "$PY" -I tools/serve_static.py; fi
