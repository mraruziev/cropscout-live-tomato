#!/usr/bin/env bash
# Build the PHP-free copy of the page into dist/static/ and deploy it to Vercel (production).
# Needs a Vercel login once:  npx vercel@64.5.0 login
# Usage: scripts/deploy-vercel.sh [--models /path/to/onnx] [--project <name>]   (default project: cropscout-vision)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python3
test -x .venv/bin/python && PY=.venv/bin/python
project=cropscout-vision
args=()
while [ $# -gt 0 ]; do
  if [ "$1" = "--project" ]; then project=$2; shift 2; else args+=("$1"); shift; fi
done
"$PY" -I tools/build_static.py ${args[@]+"${args[@]}"}  # bash 3.2 (macOS) with set -u
# build_static.py recreates dist/static/, so the Vercel link (.vercel/) is made again on every deploy
vercel=(npx -y vercel@64.5.0)
"${vercel[@]}" link --yes --project "$project" --cwd dist/static
"${vercel[@]}" deploy --prod --yes --cwd dist/static
