"""Assemble a fine-tuning folder (symlinks) from a model's original training set plus the field set.

    condition: the condition model's 46-class train/val folders, with
      - the tomato box crops from the Bangladesh leaf set removed except black spot: their class IDs
        were mapped by guesswork, and by eye the "late blight" crops are whole healthy-looking leaves
        and the "healthy" crops are lesion close-ups;
      - PlantVillage close-ups added for the five tomato classes that relied on those crops;
      - the field set (data/processed/classifier) added, at most FIELD_CAP images per class in
        train, rare classes repeated so they are not drowned out.
    crop-view: the crop/type model's 9-class train/val folders plus field images as Tomato_leaf, with
      the other crops' field leaves listed twice (CROP_VIEW_REPEAT_*).

Leaf crops whose box is under MIN_SOURCE_PX source pixels are left out (low-resolution sources
blow up into blur at camera size). The field set's test split is never used here.

Usage:
    python -I tools/classifier/assemble.py condition <original condition set> data/processed/condition-ft
    python -I tools/classifier/assemble.py crop-view <original crop/type set> data/processed/crop-view-ft
"""
import collections, csv, json, os, random, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIELD = os.path.join(ROOT, "data", "processed", "classifier")
PLANTVILLAGE = os.path.join(ROOT, "data", "raw", "plantvillage")
MIN_SOURCE_PX = 128
FIELD_CAP = 1000
RARE_REPEAT = 2  # field classes with fewer than RARE_BELOW train images are listed twice
RARE_BELOW = 400
CROP_VIEW_FIELD = {"train": 800, "val": 240}
# Field leaves of the other crops (and of other plants, as Other) are listed twice in the crop/type
# set, so that "leaf on a plant, soil behind" stays evidence for every crop, not only for tomato.
CROP_VIEW_REPEAT_SOURCES = {"cucumber_orchard", "lemon_field", "abcgmp_field_reviewed", "plantdoc"}
CROP_VIEW_REPEAT_CLASSES = {"Apple_leaf", "Cucumber_leaf", "Lemon_leaf", "Other"}
PV_CLASSES = {"Tomato___Early_blight": "Tomato_leaf_early_blight", "Tomato___Late_blight": "Tomato_leaf_late_blight",
              "Tomato___Bacterial_spot": "Tomato_leaf_bacterial_spot", "Tomato___Leaf_Mold": "Tomato_leaf_leaf_mold",
              "Tomato___Target_Spot": "Tomato_leaf_target_spot"}
DROPPED_SOURCE = "tomato_leaf"
KEPT_FROM_DROPPED = {"Tomato_leaf_black_spot"}


def field_rows():
    rows = []
    for r in csv.DictReader(open(os.path.join(FIELD, "manifest.csv"))):
        if r["split"] == "test":
            continue
        if r["kind"] == "leaf":
            x1, y1, x2, y2 = map(float, r["box"].split())
            if max(x2 - x1, y2 - y1) * 1.15 < MIN_SOURCE_PX:
                continue
        rows.append(r)
    return rows


def balanced_sample(rows, cap, rng):
    """Up to cap rows, spread over source photos (round robin) so no photo dominates."""
    by_photo = collections.defaultdict(list)
    for r in rows:
        by_photo[r["original"]].append(r)
    photos = list(by_photo.values())
    rng.shuffle(photos)
    for p in photos:
        rng.shuffle(p)
    out = []
    while len(out) < cap and photos:
        nxt = []
        for p in photos:
            if len(out) >= cap:
                break
            out.append(p.pop())
            if p:
                nxt.append(p)
        photos = nxt
    return out


def link(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.lexists(dst):
        os.symlink(os.path.abspath(src), dst)


def main(task, original, out):
    rng = random.Random(26)
    if os.path.exists(out):
        shutil.rmtree(out)
    classes = sorted(d for d in os.listdir(os.path.join(original, "train")) if not d.startswith("."))
    counts = collections.Counter()
    manifest = []

    # original set
    meta = os.path.join(original, "_cropscout_meta", "manifest.jsonl")
    source_of = {}
    if os.path.exists(meta):
        for line in open(meta):
            r = json.loads(line)
            source_of[os.path.normpath(r["local_path"])] = r["source"]
    for split in ("train", "val"):
        for cls in classes:
            for name in sorted(os.listdir(os.path.join(original, split, cls))):
                rel = os.path.join(split, cls, name)
                if task == "condition" and source_of.get(rel) == DROPPED_SOURCE and cls not in KEPT_FROM_DROPPED:
                    counts[f"{split}:dropped original box crop"] += 1
                    continue
                link(os.path.join(original, rel), os.path.join(out, rel))
                counts[f"{split}:original"] += 1
                if (task == "crop-view" and split == "train" and cls in CROP_VIEW_REPEAT_CLASSES
                        and source_of.get(rel) in CROP_VIEW_REPEAT_SOURCES):
                    link(os.path.join(original, rel), os.path.join(out, split, cls, f"r1_{name}"))
                    counts[f"{split}:repeated field leaf ({cls})"] += 1

    if task == "condition":
        for split in ("train", "val"):
            for folder, cls in PV_CLASSES.items():
                d = os.path.join(PLANTVILLAGE, split, folder)
                for name in sorted(os.listdir(d)):
                    link(os.path.join(d, name), os.path.join(out, split, cls, f"plantvillage_{name.replace(' ', '_')}"))
                    counts[f"{split}:plantvillage"] += 1
        rows = field_rows()
        for split in ("train", "val"):
            by_cls = collections.defaultdict(list)
            for r in rows:
                if r["split"] == split:
                    by_cls[r["label"]].append(r)
            for cls, rs in sorted(by_cls.items()):
                picked = balanced_sample(rs, FIELD_CAP, rng) if split == "train" else rs
                repeat = RARE_REPEAT if split == "train" and len(picked) < RARE_BELOW else 1
                for k in range(repeat):
                    for r in picked:
                        name = os.path.basename(r["file"])
                        name = name if k == 0 else f"r{k}_{name}"
                        link(os.path.join(FIELD, r["file"]), os.path.join(out, split, cls, f"field_{name}"))
                        manifest.append(dict(file=os.path.join(split, cls, f"field_{name}"), source=r["source"], kind=r["kind"]))
                        counts[f"{split}:field:{cls}"] += 1
    else:
        rows = field_rows()
        for split in ("train", "val"):
            rs = [r for r in rows if r["split"] == split]
            by_source = collections.defaultdict(list)
            for r in rs:
                by_source[r["source"]].append(r)
            # an even share per source, so the big CCMT set does not decide what a field leaf looks like
            share = CROP_VIEW_FIELD[split] // len(by_source)
            picked = []
            for src, srs in sorted(by_source.items()):
                picked += balanced_sample(srs, share, rng)
            for r in picked:
                name = os.path.basename(r["file"])
                link(os.path.join(FIELD, r["file"]), os.path.join(out, split, "Tomato_leaf", f"field_{name}"))
                manifest.append(dict(file=os.path.join(split, "Tomato_leaf", f"field_{name}"), source=r["source"], kind=r["kind"]))
                counts[f"{split}:field:{r['source']}:{r['kind']}"] += 1

    for split in ("train", "val"):
        for cls in classes:
            os.makedirs(os.path.join(out, split, cls), exist_ok=True)
    with open(os.path.join(out, "field-manifest.csv"), "w", newline="") as f:
        if manifest:
            w = csv.DictWriter(f, fieldnames=list(manifest[0]))
            w.writeheader()
            w.writerows(manifest)
    per_class = {split: {c: len(os.listdir(os.path.join(out, split, c))) for c in classes} for split in ("train", "val")}
    json.dump(dict(counts=counts, per_class=per_class), open(os.path.join(out, "summary.json"), "w"), indent=1)
    for k, v in sorted(counts.items()):
        print(v, k)
    print({c: per_class["train"][c] for c in classes if c.startswith("Tomato")})


if __name__ == "__main__":
    main(*sys.argv[1:4])
