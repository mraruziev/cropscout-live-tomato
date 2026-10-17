#!/usr/bin/env bash
# Download the training data, the training runs and the model weights from the repo's
# GitHub release and unpack them into data/ and runs/ (both gitignored: about 7.5 GB).
# Needs the GitHub CLI (gh auth login) with access to the repo.
# Usage: scripts/fetch-datasets.sh [asset-name-pattern]   e.g. scripts/fetch-datasets.sh 'raw-ccmt*'
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${CROPSCOUT_DATA_TAG:-datasets-2026-10-17}"
PATTERN="${1:-*.zip}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
gh release download "$TAG" --pattern "$PATTERN" --dir "$TMP"
for z in "$TMP"/*.zip; do
  echo "unpacking $(basename "$z")"
  unzip -q -o "$z" -d .
done
echo "done: data/raw, data/processed, runs/ (see data/README.md)"
