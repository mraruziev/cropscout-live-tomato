"""
Download a few PlantVillage tomato leaf photos per class (spMohanty/PlantVillage-Dataset, CC BY-SA 3.0)
into  leaf_photos/<class>/  next to this file. The greenhouse uses them as leaf textures, and
--cropscout photo mode shows them to the models. Healthy leaves are the important addition: the
CropSCOUT repo only fetched the five disease classes.

    python fetch_leaf_photos.py            # 24 per class
    python fetch_leaf_photos.py 40
"""
import concurrent.futures as cf
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "https://raw.githubusercontent.com/spMohanty/PlantVillage-Dataset/master"
LIST = "https://api.github.com/repos/spMohanty/PlantVillage-Dataset/contents/raw/color/"
CLASSES = ("Tomato___healthy", "Tomato___Early_blight", "Tomato___Late_blight", "Tomato___Bacterial_spot",
           "Tomato___Leaf_Mold", "Tomato___Target_Spot", "Tomato___Septoria_leaf_spot")
UA = {"User-Agent": "Mozilla/5.0 (greenhouse_sim leaf photo fetch)"}
OUT = Path(__file__).resolve().parent / "leaf_photos"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def main(per_class=24):
    jobs = []
    for cls in CLASSES:
        d = OUT / cls
        d.mkdir(parents=True, exist_ok=True)
        have = [f for f in d.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png")]
        if len(have) >= per_class:
            print(f"{cls}: {len(have)} already here")
            continue
        try:
            names = [e["name"] for e in json.loads(get(LIST + cls)) if e["type"] == "file"]
        except Exception as e:
            print(f"{cls}: listing failed ({e})")
            continue
        names = sorted(names)[::max(1, len(names) // per_class)][:per_class]
        jobs += [(cls, n) for n in names if not (d / n).exists()]
    print(f"{len(jobs)} photos to download")

    def fetch(job):
        cls, n = job
        data = get(f"{REPO}/raw/color/{cls}/" + urllib.parse.quote(n))
        (OUT / cls / n).write_bytes(data)
        return n

    with cf.ThreadPoolExecutor(8) as ex:
        done = list(ex.map(fetch, jobs))
    print(f"downloaded {len(done)} into {OUT}")
    print("delete the assets/ folder (or just re-run) so the leaf textures are rebuilt with the new photos")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 24)
