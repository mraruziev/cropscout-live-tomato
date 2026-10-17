"""Build a PHP-free copy of the vision page: dist/static/.

Everything the models do is unchanged; only how files reach the browser differs.

- vision/index.php becomes index.html: the PHP header is dropped, the two cache-busting
  hashes are computed here, and <html> gets data-mode="static" so app.js reads the models
  from models/ instead of model.php and hides the field-note panel (no backend to post to).
- app.js, styles.css and vendor/ are copied as they are.
- vision/private/model-metadata.json and the .onnx models are copied to models/.
  Missing models are reported; the page then shows "could not be loaded" for them.

Serve the folder with any static server. For the camera the page must be on https:// or
localhost; tools/serve_static.py does that locally with the right content types.

    python -I tools/build_static.py [--out dist/static] [--models <folder with .onnx>]
"""
import argparse
import hashlib
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VISION = os.path.join(ROOT, "vision")
PRIVATE = os.path.join(VISION, "private")
MODELS = ["cropscout-crop-view", "cropscout-disease", "cropscout-cucumber-leaf", "cropscout-lemon-leaf",
          "cropscout-tomato-leaf"]
OPTIONAL_MODELS = ["cropscout-leaf-detector"]


def sha12(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]


def render_index(src, style_hash, script_hash):
    html = open(src, encoding="utf-8").read()
    # Drop the leading PHP block (headers, hashes) and the opening tag it is glued to.
    html, n = re.subn(r"\A<\?php.*?\?>(?=<!doctype html>)", "", html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("index.php: expected one leading <?php ... ?> block before <!doctype html>")
    html = html.replace('styles.css?v=<?= rawurlencode($styleVersion) ?>', f"styles.css?v={style_hash}")
    html = html.replace('app.js?v=<?= rawurlencode($scriptVersion) ?>', f"app.js?v={script_hash}")
    if "<?" in html:
        rest = html[html.index("<?"):html.index("<?") + 80]
        raise SystemExit(f"index.php still has PHP the static build does not know: {rest!r}")
    html = html.replace('<html lang="en">', '<html lang="en" data-mode="static">', 1)
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "static"))
    ap.add_argument("--models", default=PRIVATE, help="folder holding the .onnx files (default vision/private)")
    args = ap.parse_args()
    out = os.path.abspath(args.out)

    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "models"))

    style, script = os.path.join(VISION, "styles.css"), os.path.join(VISION, "app.js")
    shutil.copyfile(style, os.path.join(out, "styles.css"))
    shutil.copyfile(script, os.path.join(out, "app.js"))
    shutil.copytree(os.path.join(VISION, "vendor"), os.path.join(out, "vendor"))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(render_index(os.path.join(VISION, "index.php"), sha12(style), sha12(script)))
    shutil.copyfile(os.path.join(VISION, "MODEL-NOTICE.md"), os.path.join(out, "MODEL-NOTICE.md"))

    shutil.copyfile(os.path.join(PRIVATE, "model-metadata.json"), os.path.join(out, "models", "model-metadata.json"))
    missing = []
    for name in MODELS + OPTIONAL_MODELS:
        src = os.path.join(args.models, f"{name}.onnx")
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(out, "models", f"{name}.onnx"))
            print(f"  model  {name}.onnx ({os.path.getsize(src) / 1e6:.1f} MB)")
        elif name in OPTIONAL_MODELS:
            print(f"  skip   {name}.onnx (optional leaf finder, not in {args.models})")
        else:
            missing.append(name)
    print(f"built {out}")
    if missing:
        print("MISSING models (the page will load but report them as unavailable): " + ", ".join(missing),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
