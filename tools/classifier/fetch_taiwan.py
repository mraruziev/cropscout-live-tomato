"""Fetch the Taiwan tomato leaf set (Huang & Chang, Mendeley ngdgg79rzb v1, CC BY 4.0).

taiwan.7z (48 MB) is checked against the SHA-256 that Mendeley publishes and unpacked into
data/raw/taiwan/. The record's other half is a PlantVillage copy and is not fetched.

Usage: python -I tools/classifier/fetch_taiwan.py data/raw/taiwan   (needs py7zr)
"""
import hashlib, json, os, sys, urllib.request

import py7zr

API = "https://data.mendeley.com/public-api/datasets/ngdgg79rzb"
UA = {"User-Agent": "Mozilla/5.0 (cropscout-live dataset fetch)"}


def main(out):
    with urllib.request.urlopen(urllib.request.Request(f"{API}/files?folder_id=root&version=1", headers=UA), timeout=60) as r:
        f = next(x for x in json.load(r) if x["filename"] == "taiwan.7z")
    os.makedirs(out, exist_ok=True)
    archive = os.path.join(out, "taiwan.7z")
    want = f["content_details"]["sha256_hash"]
    if not (os.path.exists(archive) and hashlib.sha256(open(archive, "rb").read()).hexdigest() == want):
        with urllib.request.urlopen(urllib.request.Request(f["content_details"]["download_url"], headers=UA), timeout=600) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != want:
            raise RuntimeError("sha256 mismatch: taiwan.7z")
        open(archive, "wb").write(data)
    with py7zr.SevenZipFile(archive) as z:
        names = z.getnames()
        assert all(not os.path.isabs(n) and ".." not in n.split("/") for n in names)
        z.extractall(os.path.join(out, "extracted"))
    print(f"unpacked {len(names)} entries")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/taiwan")
