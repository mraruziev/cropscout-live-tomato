#!/usr/bin/env bash
# Fetch the ONNX models from the repo's "models" branch and install them into vision/private/.
# The branch is an orphan that holds only the six .onnx files (they are gitignored on the code
# branches). macOS/Linux twin of scripts/fetch-models.ps1.
# Usage: scripts/fetch-models.sh [branch]   (default: models)
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="${1:-models}"
git fetch origin "$BRANCH"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive --format=tar "origin/$BRANCH" | tar -x -C "$TMP"
META=vision/private/model-metadata.json
for n in crop-view disease cucumber-leaf lemon-leaf tomato-leaf; do
  test -f "$TMP/cropscout-$n.onnx" || { echo "origin/$BRANCH lacks cropscout-$n.onnx" >&2; exit 1; }
done
fail=0
for f in "$TMP"/*.onnx; do
  name="$(basename "$f" .onnx)"
  want="$(python3 - "$META" "$name" <<'PY'
import json, sys
m = json.load(open(sys.argv[1])); name = sys.argv[2]
keys = {"cropscout-crop-view": m["crop_view"], "cropscout-disease": m["disease"], "cropscout-leaf-detector": m.get("leaf_detector", {})}
for s in m.get("condition_specialists", []): keys[f"cropscout-{s['id']}"] = s
print(keys.get(name, {}).get("onnx_sha256", ""))
PY
)"
  have="$(shasum -a 256 "$f" | cut -d' ' -f1)"
  if [ -n "$want" ] && [ "$want" != "$have" ]; then
    echo "MISMATCH $name.onnx: sha256 $have does not match $META ($want)" >&2; fail=1
  fi
  rm -f "vision/private/$name.onnx"
  cp "$f" "vision/private/$name.onnx"
  echo "installed $name.onnx ($(du -h "$f" | cut -f1))"
done
[ "$fail" = 0 ] || { echo "Some models do not match the metadata; the page will refuse them." >&2; exit 1; }
echo "Done. Start the site with scripts/serve.sh and open http://localhost:8080/vision/"
