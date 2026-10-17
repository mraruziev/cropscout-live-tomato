"""Evaluate the leaf/fruit detector the way the page uses it: the NMS-free one-to-one head at 320 px.

Ultralytics validates with the one-to-many head plus NMS unless nms=False, so the numbers printed
during training are not the exported model's. This reports mAP for one split, overall and per source.

Usage: python -I tools/detector/evaluate.py runs/detect/runs/detector/yolo26n-320/weights/best.pt data/processed/detector [test]
"""
import csv, json, os, sys, tempfile

from ultralytics import YOLO


def main(weights, dataset, split):
    model = YOLO(weights)
    dataset = os.path.abspath(dataset)
    rows = [r for r in csv.DictReader(open(os.path.join(dataset, "manifest.csv"))) if r["file"].startswith(split + "/")]
    groups = [("all", rows)] + [(s, [r for r in rows if r["source"] == s]) for s in sorted({r["source"] for r in rows})]
    tmp = tempfile.mkdtemp()
    report = {}
    for name, subset in groups:
        listing = os.path.join(tmp, f"{name}.txt")
        with open(listing, "w") as f:
            f.write("\n".join(os.path.join(dataset, "images", r["file"]) for r in subset) + "\n")
        data = os.path.join(tmp, f"{name}.yaml")
        with open(data, "w") as f:
            f.write(f"path: {dataset}\ntrain: {listing}\nval: {listing}\nnames:\n")
            f.writelines(f"  {i}: {n}\n" for i, n in model.names.items())
        m = model.val(data=data, imgsz=320, batch=16, nms=False, device="cpu", plots=False, verbose=False)
        report[name] = {
            "images": len(subset),
            "mAP50": round(float(m.box.map50), 3),
            "mAP50_95": round(float(m.box.map), 3),
            "precision": round(float(m.box.mp), 3),
            "recall": round(float(m.box.mr), 3),
            "mAP50_per_class": {model.names[int(c)]: round(float(m.box.ap50[i]), 3) for i, c in enumerate(m.box.ap_class_index)},
        }
    report["page_settings"] = page_settings(model, dataset, rows)
    print(json.dumps(report, indent=2))


def page_settings(model, dataset, rows, iou_match=0.5):
    """Precision and recall for the boxes the page actually uses.

    Like the page: centre square of each image, 320 px, boxes kept at score >= score_threshold and
    longer side >= min_box_side of the square. A predicted box is correct when it overlaps a
    ground-truth box of the same class by IoU >= 0.5. Recall counts ground-truth boxes of that size.
    """
    import cv2
    import numpy as np

    meta = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "vision", "private", "model-metadata.json")))
    live = meta.get("leaf_detector", {"score_threshold": 0.35, "min_box_side": 0.15})
    score_min, side_min = live["score_threshold"], live["min_box_side"]

    def iou(a, b):
        w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = w * h
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / union if union > 0 else 0.0

    totals = {}
    for r in rows:
        img = cv2.imread(os.path.join(dataset, "images", r["file"]))
        h, w = img.shape[:2]
        s = min(h, w)
        x0, y0 = (w - s) // 2, (h - s) // 2
        square = cv2.resize(img[y0:y0 + s, x0:x0 + s], (320, 320), interpolation=cv2.INTER_AREA)
        truth = []
        for line in open(os.path.join(dataset, "labels", r["file"].rsplit(".", 1)[0] + ".txt")):
            c, cx, cy, bw, bh = map(float, line.split())
            box = [(cx - bw / 2) * w - x0, (cy - bh / 2) * h - y0, (cx + bw / 2) * w - x0, (cy + bh / 2) * h - y0]
            clipped = [min(max(v, 0), s) for v in box]
            full = (box[2] - box[0]) * (box[3] - box[1])
            kept = (clipped[2] - clipped[0]) * (clipped[3] - clipped[1])
            if full > 0 and kept / full >= 0.5:
                truth.append((int(c), [v / s for v in clipped]))
        res = model.predict(square, imgsz=320, conf=score_min, nms=False, device="cpu", verbose=False)[0]
        preds = [(int(c), [v / 320 for v in b]) for b, c in zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist())]
        preds = [p for p in preds if max(p[1][2] - p[1][0], p[1][3] - p[1][1]) >= side_min]
        big_truth = [t for t in truth if max(t[1][2] - t[1][0], t[1][3] - t[1][1]) >= side_min]
        for key in ("all", r["source"]):
            t = totals.setdefault(key, {"pred": 0, "pred_ok": 0, "pred_ok_any_class": 0, "truth": 0, "truth_found": 0})
            t["pred"] += len(preds)
            t["pred_ok"] += sum(any(tc == pc and iou(pb, tb) >= iou_match for tc, tb in truth) for pc, pb in preds)
            t["pred_ok_any_class"] += sum(any(iou(pb, tb) >= iou_match for _, tb in truth) for _, pb in preds)
            t["truth"] += len(big_truth)
            t["truth_found"] += sum(any(tc == pc and iou(pb, tb) >= iou_match for pc, pb in preds) for tc, tb in big_truth)
    out = {"score_threshold": score_min, "min_box_side": side_min}
    for key, t in totals.items():
        out[key] = {
            "boxes_used": t["pred"],
            "precision": round(t["pred_ok"] / t["pred"], 3) if t["pred"] else None,
            "precision_any_class": round(t["pred_ok_any_class"] / t["pred"], 3) if t["pred"] else None,
            "large_truth_boxes": t["truth"],
            "recall_large": round(t["truth_found"] / t["truth"], 3) if t["truth"] else None,
        }
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/processed/detector", sys.argv[3] if len(sys.argv) > 3 else "test")
