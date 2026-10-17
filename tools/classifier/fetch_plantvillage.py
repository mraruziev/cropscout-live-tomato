"""Fetch a few hundred PlantVillage tomato leaves per class (spMohanty/PlantVillage-Dataset, CC BY-SA 3.0).

Used only to keep five tomato condition classes trained on correctly labelled close-ups
(early blight, late blight, bacterial spot, leaf mold, target spot). Images are grouped by the
repo's own leaf map (several photos of one leaf share a leaf ID), at most one image is taken per
leaf, and the split is a hash of the leaf ID, so no leaf is in both splits.

Usage: python -I tools/classifier/fetch_plantvillage.py data/raw/plantvillage
"""
import concurrent.futures as cf, hashlib, json, os, random, re, sys, urllib.parse, urllib.request

REPO = "https://raw.githubusercontent.com/spMohanty/PlantVillage-Dataset/master"
LIST = "https://api.github.com/repos/spMohanty/PlantVillage-Dataset/contents/raw/color/"
CLASSES = ("Tomato___Early_blight", "Tomato___Late_blight", "Tomato___Bacterial_spot",
           "Tomato___Leaf_Mold", "Tomato___Target_Spot")
PER_CLASS = {"train": 260, "val": 40}
UA = {"User-Agent": "Mozilla/5.0 (cropscout-live dataset fetch)"}


def get(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read()
        except OSError:
            if attempt == 3:
                raise


def leaf_key(path):
    name = os.path.basename(path).split("___")[-1].split("copy")[0]
    return re.sub(r"\.(jpe?g|png)$", "", name, flags=re.I).strip().lower()


def main(out):
    leaf_map = json.loads(get(f"{REPO}/leaf_grouping/leaf-map.json"))
    rng = random.Random(26)
    wanted = []
    for cls in CLASSES:
        files = sorted(f"raw/color/{cls}/{e['name']}" for e in json.loads(get(LIST + cls)) if e["type"] == "file")
        rng.shuffle(files)
        seen, picked = set(), {"train": [], "val": []}
        for f in files:
            leaf = next((s for s in leaf_map.get(leaf_key(f), []) if s.startswith(cls)), None) or leaf_key(f)
            if leaf in seen:
                continue
            seen.add(leaf)
            split = "val" if int(hashlib.sha1(leaf.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < 0.15 else "train"
            if len(picked[split]) < PER_CLASS[split]:
                picked[split].append(f)
        wanted += [(split, cls, f) for split, fs in picked.items() for f in fs]
    print(f"{len(wanted)} images")

    def fetch(item):
        split, cls, f = item
        dst = os.path.join(out, split, cls, os.path.basename(f))
        if not os.path.exists(dst):
            data = get(f"{REPO}/" + urllib.parse.quote(f))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(data)
        return dst

    with cf.ThreadPoolExecutor(8) as ex:
        done = list(ex.map(fetch, wanted))
    print(f"wrote {len(done)} files to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/plantvillage")
