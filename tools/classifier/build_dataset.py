"""Build the field tomato-leaf classification set from the fetched sources under data/raw/.

Writes resized JPEG copies to data/processed/classifier/<split>/<class>/ plus manifest.csv.
Class names are the condition model's own (Tomato_leaf_*); the crop/type model uses the same
images as Tomato_leaf.

Each source photo gives:
- "square": its centre square, which is what photo mode and a whole-square live frame see;
- "leaf": every leaf the leaf finder cuts out at the page's settings (score, smallest box,
  padding from the leaf_detector metadata), from the centre square and, for oblong photos, from
  squares at both ends. Each photo is first shown at the camera's 1080 px like the live page,
  and leaves are cut from that, so a crop has the resolution the page would give it.

Rules:
- Labels come from each source's own class folders; classes with no matching condition are
  dropped (see SOURCES). Sichuan leaves count only where the finder's box matches one of the
  source's own Viral_Leaf boxes.
- Byte-identical files are kept once, and dropped entirely when their labels disagree.
- Near-duplicate photos (64-bit DCT perceptual hash within PHASH_DISTANCE bits) inside a source
  share a group; across sources the later one is dropped.
- Any photo that is a near-duplicate of a test fixture (tests/fixtures.local.json, including
  the whole-plant scenes) is dropped.
- Splits are by group, never by file: SLIF reuses the leaf finder's split of each base photo,
  Sichuan its capture-day split (test day 0617 holds the whole-plant fixtures), the others a
  hash of the group (about 80/12/8).

Usage: python -I tools/classifier/build_dataset.py data/raw data/processed/classifier
"""
import collections, csv, glob, hashlib, json, math, os, re, sys
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import ROOT, Pipeline, halve_to, iou

STORE_SIDE = 320
PHASH_DISTANCE = 6
MIN_LEAF_PX = 128  # leaf crops smaller than this at camera resolution are too blurry to label
MAX_LEAVES_PER_PHOTO = 6
SICHUAN_DAY_SPLIT = {"0509": "train", "1021": "train", "1112": "train", "0919": "val", "0617": "test"}

CCMT = {"healthy": "Tomato_leaf_healthy", "septoria leaf spot": "Tomato_leaf_septoria_leaf_spot"}
# leaf blight (early or late, unspecified), leaf curl (mixed symptoms) and verticillium wilt: no class
SLIF = {"Early_Blight": "Tomato_leaf_early_blight", "Mosaic": "Tomato_leaf_tomato_mosaic_virus",
        "Healthy": "Tomato_leaf_healthy", "Late_Blight": "Tomato_leaf_late_blight",
        "Bacterial_Spot": "Tomato_leaf_bacterial_spot", "Septoria": "Tomato_leaf_septoria_leaf_spot"}
# Powdery_Mildew and Wilt: no class
TAIWAN = {"Bacterial spot": "Tomato_leaf_bacterial_spot", "Late blight": "Tomato_leaf_late_blight",
          "health": "Tomato_leaf_healthy"}
# Black mold (Pseudocercospora, not leaf mold), Gray spot and powdery mildew: no class
SOURCE_ORDER = ("slif", "sichuan", "ccmt", "taiwan")


def hash_split(key, val=0.12, test=0.08):
    x = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if x < val else "test" if x < val + test else "train"


def phash(rgb):
    g = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (32, 32), interpolation=cv2.INTER_AREA)
    d = cv2.dct(g.astype(np.float32))[:8, :8].flatten()[1:]
    return int("".join("1" if b else "0" for b in d > np.median(d)), 2)


def hamming(a, b):
    return bin(a ^ b).count("1")


def read_rgb(path):
    """Raw pixel orientation (no EXIF rotation), as the box annotations and the detector set use."""
    try:
        img = Image.open(path)
        img.load()
    except Exception:
        return None
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


# ---------------------------------------------------------------- sources


def ccmt(raw):
    for folder, label in CCMT.items():
        for p in sorted(glob.glob(os.path.join(raw, "ccmt", folder, "*"))):
            yield dict(path=p, source="ccmt", label=label, group=None, split=None)


def slif(raw):
    det_split = {}
    manifest = os.path.join(ROOT, "data", "processed", "detector", "manifest.csv")
    for r in csv.DictReader(open(manifest)):
        if r["source"] == "slif":
            det_split[r["group"]] = r["file"].split("/")[0]
    by_id = collections.defaultdict(set)
    files = sorted(glob.glob(os.path.join(raw, "slif", "Raw_Dataset", "*", "*")))
    for p in files:
        by_id[re.match(r"(t\d{4})", os.path.basename(p)).group(1)].add(p.split(os.sep)[-2])
    for p in files:
        folder = p.split(os.sep)[-2]
        base = re.match(r"(t\d{4})", os.path.basename(p)).group(1)
        if folder not in SLIF or len(by_id[base]) > 1:  # t0014 sits in two class folders
            continue
        group = f"slif:{base}"
        yield dict(path=p, source="slif", label=SLIF[folder], group=group,
                   split=det_split.get(group) or hash_split(group))


def sichuan(raw):
    for xml in sorted(glob.glob(os.path.join(raw, "sichuan", "annotations", "Viral", "*.xml"))):
        root = ET.parse(xml).getroot()
        stem = os.path.splitext(os.path.basename(xml))[0]
        img = os.path.join(raw, "sichuan", "images", "Viral", root.findtext("filename"))
        boxes = []
        for obj in root.iter("object"):
            if obj.findtext("name").strip() == "Viral_Leaf":
                b = obj.find("bndbox")
                boxes.append([float(b.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax")])
        if not boxes or not os.path.exists(img):
            continue
        day = re.search(r"_(\d{4})_", stem).group(1)
        yield dict(path=img, source="sichuan", label="Tomato_leaf_tomato_mosaic_virus", group=f"sichuan:{day}",
                   split=SICHUAN_DAY_SPLIT[day], leaf_boxes=boxes)


def taiwan(raw):
    for folder, label in TAIWAN.items():
        for p in sorted(glob.glob(os.path.join(raw, "taiwan", "extracted", "taiwan", "Preprocessed data", "*", folder, "*"))):
            yield dict(path=p, source="taiwan", label=label, group=None, split=None)


# ---------------------------------------------------------------- helpers


def protected_hashes():
    """Perceptual hashes of every test fixture image, so no training photo can be one of them."""
    path = os.path.join(ROOT, "tests", "fixtures.local.json")
    if not os.path.exists(path):
        return []
    hashes = []
    for f in json.load(open(path))["fixtures"]:
        paths = [f["path"]] if f.get("path") else []
        if f.get("dir"):
            names = sorted(os.listdir(f["dir"]))
            paths = [os.path.join(f["dir"], n) for n in names[:1]]
        for p in paths:
            img = read_rgb(p)
            if img is not None:
                hashes.append(phash(np.asarray(img)))
        if f.get("path"):  # the user's own photos: protect the whole folder
            folder = os.path.dirname(f["path"])
            if "regression_inputs" in folder:
                for q in sorted(glob.glob(os.path.join(folder, "*"))):
                    img = read_rgb(q)
                    if img is not None:
                        hashes.append(phash(np.asarray(img)))
    return sorted(set(hashes))


def squares(w, h):
    """The centre square first, then squares at both ends of an oblong photo."""
    s = min(w, h)
    n = min(3, math.ceil(max(w, h) / s - 1e-6))
    centre = ((w - s) // 2, (h - s) // 2)
    out = [centre]
    if n > 1:
        ends = [(0, 0), (w - s, h - s)]
        out += [e for e in ends if e != centre]
    return s, out


def store(img, out_path):
    side = max(img.size)
    if side > STORE_SIDE:
        f = STORE_SIDE / side
        img = img.resize((max(1, round(img.size[0] * f)), max(1, round(img.size[1] * f))), Image.BILINEAR)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, "JPEG", quality=94)


class UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


# ---------------------------------------------------------------- build


def main(raw, out):
    pipe = Pipeline(detector=True)
    protected = protected_hashes()
    print(f"{len(protected)} protected fixture hashes")
    skipped = collections.Counter()

    items = []
    for fn in (slif, sichuan, ccmt, taiwan):
        for it in fn(raw):
            items.append(it)
    print(f"{len(items)} candidate photos")

    # exact duplicates
    by_sha = collections.defaultdict(list)
    for it in items:
        it["sha"] = hashlib.sha256(open(it["path"], "rb").read()).hexdigest()
        by_sha[it["sha"]].append(it)
    kept = []
    for sha, its in by_sha.items():
        if len({i["label"] for i in its}) > 1:
            skipped["exact duplicate with conflicting labels"] += len(its)
            continue
        kept.append(its[0])
        skipped["exact duplicate"] += len(its) - 1
    items = kept

    # decode, perceptual hash, protected fixtures
    loaded = []
    for it in items:
        img = read_rgb(it["path"])
        if img is None or min(img.size) < 64:
            skipped[f"{it['source']}:unreadable"] += 1
            continue
        it["phash"] = phash(np.asarray(img))
        if any(hamming(it["phash"], h) <= PHASH_DISTANCE for h in protected):
            skipped[f"{it['source']}:matches a test fixture"] += 1
            continue
        loaded.append(it)
    items = loaded

    # near duplicates: drop across sources, group within a source
    uf = UnionFind()
    order = sorted(range(len(items)), key=lambda i: SOURCE_ORDER.index(items[i]["source"]))
    rank = {i: r for r, i in enumerate(order)}
    hashes = np.array([it["phash"] for it in items], dtype=np.uint64)
    dropped = set()
    for a in order:
        A = items[a]
        if a in dropped:
            continue
        close = np.nonzero(np.bitwise_count(hashes ^ hashes[a]) <= PHASH_DISTANCE)[0]
        for b in sorted((int(b) for b in close if rank[int(b)] > rank[a]), key=rank.get):
            B = items[b]
            if b in dropped:
                continue
            if A["source"] != B["source"]:
                dropped.add(b)
                skipped["cross-source near-duplicate"] += 1
            elif A["label"] != B["label"]:
                dropped.update((a, b))
                skipped["near-duplicate with conflicting labels"] += 2
            else:
                uf.union(a, b)
    near_pairs = collections.Counter()
    for i, it in enumerate(items):
        if i in dropped:
            continue
        if it["group"] is None:
            it["group"] = f"{it['source']}:{uf.find(i)}"
    # every member of a merged group follows its first member's split
    group_of = {}
    for i in order:
        if i in dropped:
            continue
        root = uf.find(i)
        it = items[i]
        if root in group_of:
            it["split"] = group_of[root]["split"]
            it["group"] = group_of[root]["group"]
            near_pairs[it["source"]] += 1
        else:
            if it["split"] is None:
                it["split"] = hash_split(it["group"])
            group_of[root] = it
    items = [it for i, it in enumerate(items) if i not in dropped]
    print(f"{len(items)} photos after dedupe; merged near-duplicates: {dict(near_pairs)}")

    rows, counts = [], collections.Counter()
    for n, it in enumerate(items):
        img = read_rgb(it["path"])
        w, h = img.size
        stem = f"{it['source']}_{it['sha'][:16]}"
        side, origins = squares(w, h)
        leaves = []
        for k, (ox, oy) in enumerate(origins):
            sq = img.crop((ox, oy, ox + side, oy + side))
            cam = pipe.camera_square(sq)
            if k == 0:
                f = f"{it['split']}/{it['label']}/{stem}_sq.jpg"
                store(halve_to(cam), os.path.join(out, f))
                rows.append(dict(file=f, split=it["split"], label=it["label"], source=it["source"], group=it["group"],
                                 original=os.path.relpath(it["path"], raw), kind="square", box="", score=""))
                counts[(it["split"], it["label"], "square")] += 1
            for det in pipe.leaf_boxes(pipe.detect(cam), max_leaves=50):
                bx = [ox + det["box"][0] * side, oy + det["box"][1] * side, ox + det["box"][2] * side, oy + det["box"][3] * side]
                if any(iou(bx, l["bx"]) > 0.5 for l in leaves):
                    continue
                crop = pipe.leaf_crop(cam, det["box"])
                if crop.size[0] < MIN_LEAF_PX:
                    skipped["leaf too small"] += 1
                    continue
                if it.get("leaf_boxes"):  # Sichuan: only leaves the source boxed as viral
                    if not any(iou(bx, b) >= 0.3 or contained(bx, b) >= 0.6 for b in it["leaf_boxes"]):
                        skipped["sichuan: leaf not boxed as viral"] += 1
                        continue
                leaves.append(dict(bx=bx, score=det["score"], crop=crop))
        for j, leaf in enumerate(sorted(leaves, key=lambda l: -l["score"])[:MAX_LEAVES_PER_PHOTO]):
            f = f"{it['split']}/{it['label']}/{stem}_leaf{j}.jpg"
            store(halve_to(leaf["crop"]), os.path.join(out, f))
            rows.append(dict(file=f, split=it["split"], label=it["label"], source=it["source"], group=it["group"],
                             original=os.path.relpath(it["path"], raw), kind="leaf",
                             box=" ".join(f"{v:.0f}" for v in leaf["bx"]), score=f"{leaf['score']:.3f}"))
            counts[(it["split"], it["label"], "leaf")] += 1
        if (n + 1) % 500 == 0:
            print(f"  {n + 1}/{len(items)} photos, {len(rows)} images", flush=True)

    with open(os.path.join(out, "manifest.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    stats = collections.defaultdict(dict)
    for (split, label, kind), v in sorted(counts.items()):
        stats[split][f"{label}:{kind}"] = v
    by_source = collections.Counter((r["split"], r["source"], r["kind"]) for r in rows)
    json.dump(dict(stats=stats, by_source={"/".join(k): v for k, v in sorted(by_source.items())},
                   photos=collections.Counter(f"{it['split']}/{it['source']}" for it in items),
                   skipped=skipped), open(os.path.join(out, "stats.json"), "w"), indent=2)
    print(json.dumps(dict(skipped=skipped), indent=1))
    for k, v in sorted(by_source.items()):
        print(v, k)


def contained(a, b):
    """Share of box a that lies inside box b."""
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = (a[2] - a[0]) * (a[3] - a[1])
    return w * h / area if area > 0 else 0


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw", sys.argv[2] if len(sys.argv) > 2 else "data/processed/classifier")
