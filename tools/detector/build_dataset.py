"""Build the two-class tomato leaf/fruit box dataset for the live detector.

Reads the fetched sources under data/raw/ and writes resized copies (long side 640 px) plus YOLO
labels to data/processed/detector/. Classes: 0 tomato_leaf, 1 tomato_fruit.

Rules:
- Every split is made by source group (photo, plant or capture day), never by file, so augmented
  copies of one photo always land in the same split.
- Near-duplicate photos (64-bit DCT perceptual hash, Hamming distance <= PHASH_DISTANCE) are found
  across all sources. Duplicates from different sources are dropped (first source wins);
  duplicates inside one source merge their groups so they share a split.

Usage: python -I tools/detector/build_dataset.py data/raw data/processed/detector
"""
import collections, csv, glob, hashlib, json, os, re, shutil, sys
import xml.etree.ElementTree as ET

import cv2
import numpy as np

CLASSES = ("tomato_leaf", "tomato_fruit")
LONG_SIDE = 640
PHASH_DISTANCE = 6
MIN_BOX_PX = 4  # at LONG_SIDE; smaller boxes are annotation noise
SOURCE_ORDER = ("sichuan", "slif", "tfdd", "plantdoc")  # dedupe priority
# Sichuan photos carry their capture day (MMDD). Whole days go to one split.
SICHUAN_DAY_SPLIT = {"0509": "train", "1021": "train", "1112": "train", "0919": "val", "0617": "test"}


def hash_split(key, val=0.12, test=0.08):
    x = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if x < val else "test" if x < val + test else "train"


def read_yolo(path):
    vals = [float(v) for v in open(path).read().split()] if os.path.exists(path) else []
    return [tuple(vals[i:i + 5]) for i in range(0, len(vals) - 4, 5)]


def phash(img):
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (32, 32), interpolation=cv2.INTER_AREA)
    d = cv2.dct(g.astype(np.float32))[:8, :8].flatten()[1:]
    bits = d > np.median(d)
    return int("".join("1" if b else "0" for b in bits), 2)


# ---------------------------------------------------------------- sources
# Each yields dicts: path, source, group, split (or None), boxes [(cls, x1, y1, x2, y2) in source px]


def slif(root):
    d = os.path.join(root, "slif", "Detection_Dataset")
    for img in sorted(glob.glob(os.path.join(d, "images", "*.jpg"))):
        name = os.path.basename(img)
        m = re.match(r"(t\d{4})", name)
        h, w = cv2.imread(img, cv2.IMREAD_IGNORE_ORIENTATION | cv2.IMREAD_COLOR).shape[:2]
        boxes = []
        for _, cx, cy, bw, bh in read_yolo(os.path.join(d, "lables", os.path.splitext(name)[0] + ".txt")):
            boxes.append((0, (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
        yield dict(path=img, source="slif", group=f"slif:{m.group(1)}", split=None, boxes=boxes)


def sichuan(root):
    d = os.path.join(root, "sichuan")
    for xml in sorted(glob.glob(os.path.join(d, "annotations", "*", "*.xml"))):
        stem = os.path.splitext(os.path.basename(xml))[0]
        cls_dir = os.path.basename(os.path.dirname(xml))
        img = next(iter(glob.glob(os.path.join(d, "images", cls_dir, stem + ".*"))), None)
        if not img:
            continue
        day = re.search(r"_(\d{4})_", stem).group(1)
        boxes, zones = [], 0
        for obj in ET.parse(xml).getroot().iter("object"):
            name = obj.findtext("name").strip()
            part = name.split("_")[-1].lower()
            b = obj.find("bndbox")
            xy = [float(b.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax")]
            if part == "leaf":
                boxes.append((0, *xy))
            elif part == "fruit":
                boxes.append((1, *xy))
            else:
                zones += 1  # stem and plant-zone boxes: not a leaf or fruit
        size = ET.parse(xml).getroot().find("size")
        yield dict(path=img, source="sichuan", group=f"sichuan:{day}", split=SICHUAN_DAY_SPLIT[day],
                   boxes=boxes, xml_size=(int(size.findtext("width")), int(size.findtext("height"))),
                   zones=zones)


def plantdoc(root):
    d = os.path.join(root, "plantdoc")
    rows = collections.defaultdict(list)
    for split, name in (("TRAIN", "train_labels.csv"), ("TEST", "test_labels.csv")):
        for r in csv.DictReader(open(os.path.join(d, name), encoding="utf-8")):
            if r["class"].lower().startswith("tomato"):
                rows[(split, r["filename"])].append(r)
    seen = set()
    for (split, fn), rs in sorted(rows.items()):
        if fn in seen:  # the same file sits in both TRAIN and TEST
            continue
        seen.add(fn)
        img = os.path.join(d, split, fn)
        boxes = [(0, *(float(r[k]) for k in ("xmin", "ymin", "xmax", "ymax"))) for r in rs]
        yield dict(path=img, source="plantdoc", group=f"plantdoc:{fn}", split=None, boxes=boxes,
                   csv_size=(int(rs[0]["width"]), int(rs[0]["height"])))


def tfdd(root):
    d = os.path.join(root, "tfdd", "extracted", "TFDD")
    for img in sorted(glob.glob(os.path.join(d, "*", "images", "*.jpg"))):
        name = os.path.basename(img)
        base = re.match(r"(.+?)_(?:jpe?g|png)\.rf\.", name, re.I)
        h, w = cv2.imread(img, cv2.IMREAD_IGNORE_ORIENTATION | cv2.IMREAD_COLOR).shape[:2]
        lbl = os.path.join(os.path.dirname(os.path.dirname(img)), "labels", os.path.splitext(name)[0] + ".txt")
        boxes = [(1, (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h)
                 for _, cx, cy, bw, bh in read_yolo(lbl)]
        yield dict(path=img, source="tfdd", group=f"tfdd:{base.group(1) if base else name}", split=None, boxes=boxes)


# ---------------------------------------------------------------- build


def load(item):
    img = cv2.imread(item["path"], cv2.IMREAD_IGNORE_ORIENTATION | cv2.IMREAD_COLOR)
    if img is None:
        return None, "unreadable"
    h, w = img.shape[:2]
    ref = item.get("xml_size") or item.get("csv_size")
    sx = sy = 1.0
    if ref and ref != (w, h):
        if ref == (h, w):
            return None, "rotated-annotation"
        sx, sy = w / ref[0], h / ref[1]  # PlantDoc CSV sizes sometimes differ from the file
    scale = min(1.0, LONG_SIDE / max(w, h))
    out = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img
    oh, ow = out.shape[:2]
    boxes = []
    for c, x1, y1, x2, y2 in item["boxes"]:
        x1, x2 = sorted((max(0, x1 * sx * scale), min(ow, x2 * sx * scale)))
        y1, y2 = sorted((max(0, y1 * sy * scale), min(oh, y2 * sy * scale)))
        if x2 - x1 >= MIN_BOX_PX and y2 - y1 >= MIN_BOX_PX:
            boxes.append((c, x1, y1, x2, y2))
    return (out, boxes), None


def main(raw, out):
    items, skipped = [], collections.Counter()
    for fn in (sichuan, slif, tfdd, plantdoc):
        for it in fn(raw):
            if it.get("zones") and not it["boxes"]:
                skipped[f"{it['source']}:zone-boxes-only"] += 1
                continue
            items.append(it)
    print(f"{len(items)} candidate images")

    loaded = []
    for it in items:
        res, err = load(it)
        if err:
            skipped[f"{it['source']}:{err}"] += 1
            continue
        if not res[1]:
            skipped[f"{it['source']}:no-boxes"] += 1
            continue
        it["image"], it["boxes_px"] = res
        it["phash"] = phash(res[0])
        loaded.append(it)

    # Perceptual-hash dedupe.
    hashes = np.array([it["phash"] for it in loaded], dtype=np.uint64)
    parent = {it["group"]: it["group"] for it in loaded}

    def find(g):
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    drop, dup_pairs, fixed_pairs = set(), collections.Counter(), []
    rank = {s: i for i, s in enumerate(SOURCE_ORDER)}
    for i in range(len(loaded) - 1):
        dist = np.bitwise_count(np.bitwise_xor(hashes[i + 1:], hashes[i]))
        for j in np.nonzero(dist <= PHASH_DISTANCE)[0] + i + 1:
            a, b = loaded[i], loaded[j]
            if a["source"] != b["source"]:
                drop.add(id(b if rank[b["source"]] >= rank[a["source"]] else a))
                dup_pairs[f"{a['source']}~{b['source']}"] += 1
            elif a["group"] != b["group"]:
                if a["split"] or b["split"]:
                    fixed_pairs.append((a, b))  # split is fixed by capture day; resolved below
                else:
                    parent[find(a["group"])] = find(b["group"])
                dup_pairs[f"{a['source']}~{b['source']} (other group)"] += 1
    kept = [it for it in loaded if id(it) not in drop]
    skipped["cross-source near-duplicate"] += len(loaded) - len(kept)

    # Splits: a merged group takes the split of its root key; fixed splits (Sichuan days) win.
    for it in kept:
        it["split"] = it["split"] or hash_split(find(it["group"]))
    # A near-duplicate pair that still straddles two fixed splits keeps only its training copy.
    for a, b in fixed_pairs:
        if a["split"] != b["split"] and id(a) not in drop and id(b) not in drop:
            drop.add(id(b if a["split"] == "train" else a))
            skipped["near-duplicate across fixed splits"] += 1
    kept = [it for it in kept if id(it) not in drop]

    if os.path.exists(out):
        shutil.rmtree(out)
    stats = collections.defaultdict(lambda: collections.Counter())
    manifest = []
    for k, it in enumerate(kept):
        stem = f"{it['source']}_{k:05d}"
        img_dst = os.path.join(out, "images", it["split"], stem + ".jpg")
        lbl_dst = os.path.join(out, "labels", it["split"], stem + ".txt")
        os.makedirs(os.path.dirname(img_dst), exist_ok=True)
        os.makedirs(os.path.dirname(lbl_dst), exist_ok=True)
        cv2.imwrite(img_dst, it["image"], [cv2.IMWRITE_JPEG_QUALITY, 92])
        h, w = it["image"].shape[:2]
        with open(lbl_dst, "w") as f:
            for c, x1, y1, x2, y2 in it["boxes_px"]:
                f.write(f"{c} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}\n")
        s = stats[f"{it['split']}"]
        s["images"] += 1
        s[f"images:{it['source']}"] += 1
        for c, *_ in it["boxes_px"]:
            s[f"boxes:{CLASSES[c]}"] += 1
            s[f"boxes:{CLASSES[c]}:{it['source']}"] += 1
        manifest.append(dict(file=f"{it['split']}/{stem}.jpg", source=it["source"], group=find(it["group"]),
                             original=os.path.relpath(it["path"], raw), phash=f"{it['phash']:016x}",
                             boxes=len(it["boxes_px"])))

    with open(os.path.join(out, "data.yaml"), "w") as f:
        f.write(f"path: {os.path.abspath(out)}\ntrain: images/train\nval: images/val\ntest: images/test\n"
                f"names:\n  0: {CLASSES[0]}\n  1: {CLASSES[1]}\n")
    with open(os.path.join(out, "manifest.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0]))
        w.writeheader()
        w.writerows(manifest)
    groups = collections.defaultdict(set)
    for m in manifest:
        groups[m["group"]].add(m["file"].split("/")[0])
    leaks = [g for g, s in groups.items() if len(s) > 1]
    report = dict(stats={k: dict(v) for k, v in sorted(stats.items())}, skipped=dict(skipped),
                  near_duplicate_pairs=dict(dup_pairs), groups=len(groups), groups_in_two_splits=len(leaks))
    json.dump(report, open(os.path.join(out, "stats.json"), "w"), indent=2)
    print(json.dumps(report, indent=2))
    assert not leaks, f"groups split across splits: {leaks[:5]}"


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw", sys.argv[2] if len(sys.argv) > 2 else "data/processed/detector")
