"""Fetch TFDD tomato fruit boxes (Mendeley ktfnhjspjn v3, CC BY 4.0) into data/raw/tfdd/.

Only the boxed release (TFDD.zip, about 44 MB) and its metadata CSV are fetched; the 377 MB
raw-photo zip has no boxes. Files are checked against Mendeley's SHA-256.

Usage: python -I tools/detector/fetch_tfdd.py data/raw/tfdd
"""
import hashlib, json, os, sys, urllib.request, zipfile

API = "https://data.mendeley.com/public-api/datasets/ktfnhjspjn"
UA = {"User-Agent": "Mozilla/5.0 (cropscout-live dataset fetch)"}
WANT = ("TFDD.zip", "TFDD_MetaData.csv")


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
        return r.read()


def main(out):
    os.makedirs(out, exist_ok=True)
    files = json.loads(get(f"{API}/files?folder_id=root&version=3"))
    for f in files:
        if f["filename"] not in WANT:
            continue
        data = get(f["content_details"]["download_url"])
        if hashlib.sha256(data).hexdigest() != f["content_details"]["sha256_hash"]:
            raise RuntimeError(f"sha256 mismatch: {f['filename']}")
        open(os.path.join(out, f["filename"]), "wb").write(data)
        print(f"{f['filename']}: {len(data)/1e6:.1f} MB")
    with zipfile.ZipFile(os.path.join(out, "TFDD.zip")) as z:
        for info in z.infolist():
            rel = os.path.normpath(info.filename)
            if rel.startswith("..") or os.path.isabs(rel) or info.is_dir():
                continue
            dst = os.path.join(out, "extracted", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(info) as src, open(dst, "wb") as fh:
                fh.write(src.read())
    print("extracted")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/tfdd")
