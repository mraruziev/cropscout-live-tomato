"""Run the full pipeline on one image and print the spray estimate.

    .venv/bin/python live/spray_cli.py photo.jpg [--json] [--show]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_detect import Pipeline  # noqa: E402
from spray import decide, estimate_severity, lesion_overlay, load_rules  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--models", default=str(HERE / "models"))
    ap.add_argument("--meta", default=str(HERE / "model-metadata.json"))
    ap.add_argument("--rules", default=str(HERE.parent / "vision" / "spray-rules.json"))
    ap.add_argument("--json", action="store_true", help="print machine-readable output")
    ap.add_argument("--show", action="store_true", help="open a window with the lesion mask")
    args = ap.parse_args()

    bgr = cv2.imread(args.image)
    if bgr is None:
        raise SystemExit(f"could not read {args.image}")
    pipe = Pipeline(Path(args.models), Path(args.meta), threads=1)
    rules = load_rules(args.rules)

    square = pipe.square(bgr)
    x = pipe.to_tensor(square)
    crop_p = pipe.run_crop(x)
    fam, crop_conf, crop_margin = pipe.crop_verdict(crop_p)
    severity = estimate_severity(square, rules)

    verdict = None
    if fam in pipe.cond_families:
        verdict = pipe.condition_verdict(fam, pipe.run_cond(x))
    label = verdict["label"] if verdict else None
    certain = bool(verdict and verdict["certain"])
    decision = decide(rules, label, certain, severity)

    if args.json:
        print(json.dumps({
            "crop": {"family": fam, "top": pipe.crop_classes[int(np.argmax(crop_p))],
                     "confidence": crop_conf, "margin": crop_margin},
            "condition": verdict and {k: verdict[k] for k in ("label", "diagnosis", "conf", "margin", "mass", "separation", "certain")},
            "severity": severity.__dict__,
            "spray": decision.to_dict(),
        }, indent=2))
    else:
        print(f"crop     : {pipe.crop_classes[int(np.argmax(crop_p))]} {crop_conf * 100:.0f}% (margin {crop_margin:.2f}) -> {fam or 'abstain'}")
        if verdict:
            print(f"condition: {verdict['diagnosis']} {verdict['conf'] * 100:.0f}%  certain={verdict['certain']}")
            for lbl, p in verdict["top5"]:
                print(f"           {lbl:40s} {p:.3f}")
        print(f"severity : lesion {severity.lesion_fraction * 100:.0f}% of leaf pixels, leaf cover {severity.leaf_cover * 100:.0f}% -> {severity.band}")
        print(f"spray    : {decision.summary()}")
        if decision.action == "spray" and decision.interval_days:
            print(f"           repeat every {decision.interval_days} days; {decision.reason}")

    if args.show:
        cv2.imshow("lesion mask (red) / healthy (green)", lesion_overlay(square))
        cv2.waitKey(0)


if __name__ == "__main__":
    main()
