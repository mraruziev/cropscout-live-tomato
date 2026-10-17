"""Fetch the Sichuan greenhouse tomato set (Liu et al. 2025, Mendeley c2x8rynybg v1, CC BY 4.0).

1,026 iPhone photos with Pascal VOC boxes on leaf, fruit and stem. Every file is checked against
the SHA-256 that Mendeley publishes.

Usage: python -I tools/detector/fetch_sichuan.py data/raw/sichuan
"""
import concurrent.futures as cf, hashlib, json, os, sys, urllib.request

API = "https://data.mendeley.com/public-api/datasets/c2x8rynybg"
UA = {"User-Agent": "Mozilla/5.0 (cropscout-live dataset fetch)"}  # Mendeley rejects the default urllib agent


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def fetch(item, out):
    rel, f = item
    dst = os.path.join(out, rel)
    want = f["content_details"]["sha256_hash"]
    if os.path.exists(dst) and hashlib.sha256(open(dst, "rb").read()).hexdigest() == want:
        return rel, "cached"
    with urllib.request.urlopen(urllib.request.Request(f["content_details"]["download_url"], headers=UA), timeout=300) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != want:
        raise RuntimeError(f"sha256 mismatch: {rel}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(data)
    return rel, "ok"


def main(out):
    folders = {f["id"]: f for f in get_json(f"{API}/folders/1")}

    def path_of(fid):
        parts = []
        while fid:
            parts.append(folders[fid]["name"])
            fid = folders[fid].get("parent_id")
        return os.path.join(*reversed(parts))

    items = []
    for fid in folders:
        for f in get_json(f"{API}/files?folder_id={fid}&version=1"):
            name = os.path.basename(f["filename"])
            assert name and not name.startswith(".")
            items.append((os.path.join(path_of(fid), name), f))
    print(f"{len(items)} files, {sum(f['size'] for _, f in items)/1e9:.2f} GB")
    os.makedirs(out, exist_ok=True)
    done = 0
    with cf.ThreadPoolExecutor(8) as ex:
        for rel, state in ex.map(lambda it: fetch(it, out), items):
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(items)}", flush=True)
    json.dump({rel: f["content_details"]["sha256_hash"] for rel, f in items},
              open(os.path.join(out, "manifest.json"), "w"), indent=0)
    print("done")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/sichuan")
