"""Download the public CropSCOUT v29 ONNX models and verify their SHA-256
against live/model-metadata.json.

Usage:
    .venv/bin/python live/fetch_models.py            # tomato models only
    .venv/bin/python live/fetch_models.py --all      # also the cucumber-leaf specialist
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_URL = "https://crop-scout.com/models/v29-demo/"


def expected_hashes(meta: dict) -> dict:
    out = {
        "cropscout-crop-view.onnx": meta["crop_view"]["onnx_sha256"],
        "cropscout-disease.onnx": meta["disease"]["onnx_sha256"],
    }
    for s in meta["condition_specialists"]:
        if s["id"] == "condition":
            out["cropscout-condition.onnx"] = s["onnx_sha256"]
        elif s["id"] == "cucumber-leaf":
            out["cropscout-cucumber-leaf.onnx"] = s["onnx_sha256"]
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str, dest: Path, want: str) -> None:
    if dest.exists() and sha256(dest) == want:
        print(f"ok       {name} (already present, hash matches)")
        return
    url = BASE_URL + name
    print(f"download {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "cropscout-live-tomato/0.1"})
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(req) as r, tmp.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r         {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    got = sha256(tmp)
    if got != want:
        tmp.unlink()
        sys.exit(f"HASH MISMATCH for {name}: got {got}, expected {want}")
    tmp.rename(dest)
    print(f"ok       {name} sha256={got[:16]}…")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="also fetch the general disease model and the 22 MB cucumber-leaf specialist (needed by the browser app)")
    ap.add_argument("--models", default=str(HERE / "models"))
    args = ap.parse_args()

    meta = json.loads((HERE / "model-metadata.json").read_text())
    hashes = expected_hashes(meta)
    names = ["cropscout-crop-view.onnx", "cropscout-condition.onnx"]
    if args.all:
        names += ["cropscout-disease.onnx", "cropscout-cucumber-leaf.onnx"]
    out = Path(args.models)
    out.mkdir(parents=True, exist_ok=True)
    for n in names:
        fetch(n, out / n, hashes[n])


if __name__ == "__main__":
    main()
