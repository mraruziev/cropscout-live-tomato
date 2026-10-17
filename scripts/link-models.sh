#!/usr/bin/env bash
# Link the four ONNX models into vision/private/ (they are too big for git).
# Usage: scripts/link-models.sh /path/to/folder/with/onnx/models
set -euo pipefail
SRC="${1:?Usage: scripts/link-models.sh /path/to/folder/with/onnx/models}"
DEST="$(cd "$(dirname "$0")/.." && pwd)/vision/private"
for name in cropscout-crop-view cropscout-disease cropscout-cucumber-leaf cropscout-lemon-leaf; do
  test -f "$SRC/$name.onnx" || { echo "missing $SRC/$name.onnx" >&2; exit 1; }
  ln -sf "$SRC/$name.onnx" "$DEST/$name.onnx"
  echo "linked $name.onnx"
done
