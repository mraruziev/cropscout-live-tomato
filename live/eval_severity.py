"""Measure the lesion-area (severity) estimate against labelled leaf photos.

    .venv/bin/python live/eval_severity.py [--split val] [--per-class 150] [--seed 0]

For each class folder in data/processed/classifier/<split>/ it prints quantiles of the
estimated lesion fraction, then how well the estimate separates healthy from diseased
leaves (AUC: 1.0 = perfect, 0.5 = chance) and how many healthy leaves would land in each
severity band. Use it before and after changing live/spray.py.
"""
import argparse
import glob
import os
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spray import estimate_severity, load_rules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def auc(pos, neg):
    """Probability that a random diseased leaf scores higher than a random healthy one."""
    pos, neg = np.asarray(pos), np.asarray(neg)
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.concatenate([pos, neg]).argsort().argsort() + 1  # ranks
    r_pos = order[: len(pos)].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="val")
    ap.add_argument("--per-class", type=int, default=150)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rules", default=str(ROOT / "vision" / "spray-rules.json"))
    args = ap.parse_args()
    rules = load_rules(args.rules)
    random.seed(args.seed)
    base = ROOT / "data" / "processed" / "classifier" / args.split
    classes = sorted(p.name for p in base.iterdir() if p.is_dir())
    results = {}
    for c in classes:
        files = sorted(glob.glob(str(base / c / "*")))
        random.shuffle(files)
        fr, cover, bands = [], [], {}
        for f in files[: args.per_class]:
            img = cv2.imread(f)
            if img is None:
                continue
            s = estimate_severity(img, rules)
            fr.append(s.lesion_fraction)
            cover.append(s.leaf_cover)
            bands[s.band] = bands.get(s.band, 0) + 1
        results[c] = (np.array(fr), np.array(cover), bands)
    print(f"{'class':36s} {'n':>4s} {'p10':>5s} {'p25':>5s} {'p50':>5s} {'p75':>5s} {'p90':>5s}  {'cover':>5s}  bands")
    for c, (fr, cover, bands) in results.items():
        q = np.percentile(fr, [10, 25, 50, 75, 90]) * 100
        print(f"{c:36s} {len(fr):4d} " + " ".join(f"{v:5.1f}" for v in q)
              + f"  {np.median(cover) * 100:5.1f}  {dict(sorted(bands.items()))}")
    healthy = [c for c in classes if c.endswith("_healthy")]
    pos = np.concatenate([results[c][0] for c in classes if c not in healthy])
    neg = np.concatenate([results[c][0] for c in healthy])
    print(f"\nhealthy vs diseased AUC: {auc(pos, neg):.3f}   (healthy n={len(neg)}, diseased n={len(pos)})")
    cfg = rules["severity"]
    print(f"healthy leaves above low_max ({cfg['low_max']:.2f}): {np.mean(neg > cfg['low_max']) * 100:.1f}%"
          f"   diseased leaves at/below low_max: {np.mean(pos <= cfg['low_max']) * 100:.1f}%")
    for c in classes:
        if c in healthy:
            continue
        print(f"  AUC {c:36s} {auc(results[c][0], neg):.3f}")


if __name__ == "__main__":
    main()
