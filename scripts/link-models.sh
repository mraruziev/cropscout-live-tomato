#!/usr/bin/env bash
# Link the five ONNX models into vision/private/ (they are too big for git).
# The optional leaf finder (cropscout-leaf-detector.onnx) is linked too when the folder has it.
# Usage: scripts/link-models.sh /path/to/folder/with/onnx/models
set -euo pipefail
SRC="${1:?Usage: scripts/link-models.sh /path/to/folder/with/onnx/models}"
DEST="$(cd "$(dirname "$0")/.." && pwd)/vision/private"
for name in cropscout-crop-view cropscout-disease cropscout-cucumber-leaf cropscout-lemon-leaf cropscout-tomato-leaf; do
  test -f "$SRC/$name.onnx" || { echo "missing $SRC/$name.onnx" >&2; exit 1; }
  ln -sf "$SRC/$name.onnx" "$DEST/$name.onnx"
  echo "linked $name.onnx"
done
if test -f "$SRC/cropscout-leaf-detector.onnx"; then
  ln -sf "$SRC/cropscout-leaf-detector.onnx" "$DEST/cropscout-leaf-detector.onnx"
  echo "linked cropscout-leaf-detector.onnx (open the page with ?detector=1 to use it)"
fi
