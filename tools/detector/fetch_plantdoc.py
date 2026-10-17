"""Fetch the tomato part of PlantDoc object detection (CC BY 4.0) into data/raw/plantdoc/.

Downloads the two box CSVs and only the images whose boxes are tomato classes, plus the
licence file. Images keep their TRAIN/ or TEST/ folder.

Usage: python -I tools/detector/fetch_plantdoc.py data/raw/plantdoc
"""
import concurrent.futures as cf, csv, io, os, sys, urllib.parse, urllib.request

RAW = "https://raw.githubusercontent.com/pratikkayal/PlantDoc-Object-Detection-Dataset/master/"
UA = {"User-Agent": "cropscout-live dataset fetch"}


def get(path):
    url = RAW + urllib.parse.quote(path)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def main(out):
    os.makedirs(out, exist_ok=True)
    wanted = set()
    for split, name in (("TRAIN", "train_labels.csv"), ("TEST", "test_labels.csv")):
        data = get(name)
        open(os.path.join(out, name), "wb").write(data)
        for row in csv.DictReader(io.StringIO(data.decode("utf-8"))):
            if row["class"].lower().startswith("tomato"):
                wanted.add((split, row["filename"]))
    open(os.path.join(out, "LICENSE.txt"), "wb").write(get("LICENSE.txt"))
    print(f"{len(wanted)} tomato images")

    def fetch(item):
        split, fn = item
        assert "/" not in fn and not fn.startswith(".")
        dst = os.path.join(out, split, fn)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            return "cached"
        try:
            data = get(f"{split}/{fn}")
        except urllib.error.HTTPError as e:
            return f"missing {split}/{fn}: {e.code}"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(data)
        return "ok"

    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(fetch, sorted(wanted)))
    for r in res:
        if r.startswith("missing"):
            print(r)
    print(f"done: {sum(r != 'cached' and not r.startswith('missing') for r in res)} new, "
          f"{sum(r.startswith('missing') for r in res)} missing")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/plantdoc")
