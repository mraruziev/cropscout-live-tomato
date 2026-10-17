"""The page's screening pipeline in Python (onnxruntime), for checking models offline.

It follows vision/app.js for one frame: centre square, antialiased bilinear resize to 224 px,
crop/type gate, the condition route for that crop and plant part (tomato and most crops on the
general condition model, cucumber leaf on its specialist, lemon leaf on the guarded hybrid), and
the four condition safeguards. With the leaf finder it also cuts each leaf like the live page:
the square is shown to the camera at 1080 px, halved to 540 px, resized to 320 px for the
detector, and each box is cut from the 1080 px square with the page's padding.

Frame voting is not modelled: a still fixture gives the same scores every frame, so the live
verdict is the one-frame verdict. The browser run (tests/live-e2e.mjs) stays the reference.

    python -I tools/classifier/pipeline.py [--condition m.onnx] [--tomato-leaf m.onnx] [--detector] image ...
"""
import argparse, hashlib, json, os, sys

import numpy as np
import onnxruntime as ort
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRIVATE = os.path.join(ROOT, "vision", "private")
SIZE = 224
CAMERA_SIDE = 1080  # tests/make_fake_camera.py pastes the square at the frame height
LIVE_MIN_SAMPLE_SIDE = 2 * SIZE
LEMON_POLICY = "lemon_disease_only_preserve_base_healthy_v1"


def load_metadata(path=None):
    return json.load(open(path or os.path.join(PRIVATE, "model-metadata.json")))


def centre_square(img):
    w, h = img.size
    s = min(w, h)
    return img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))


def to_tensor(img, side):
    """Antialiased bilinear resize (PIL's BILINEAR scales its support like the page's filter)."""
    a = np.asarray(img.resize((side, side), Image.BILINEAR), dtype=np.float32)
    return (np.round(a) / 255.0).transpose(2, 0, 1)[None].astype(np.float32)


def photo_tensor(img):
    """Photo mode: shorter edge to 224, centre crop."""
    w, h = img.size
    if w <= h:
        nw, nh = SIZE, (SIZE * h) // w
    else:
        nw, nh = (SIZE * w) // h, SIZE
    a = np.asarray(img.resize((nw, nh), Image.BILINEAR), dtype=np.float32)
    x, y = round((nw - SIZE) / 2), round((nh - SIZE) / 2)
    a = a[y:y + SIZE, x:x + SIZE]
    return (np.round(a) / 255.0).transpose(2, 0, 1)[None].astype(np.float32)


def halve_to(img, min_side=LIVE_MIN_SAMPLE_SIDE):
    """The page's exact 2:1 browser steps, while the result stays at least min_side."""
    while img.size[0] / 2 >= min_side:
        img = img.reduce(2)
    return img


class Pipeline:
    def __init__(self, condition=None, crop_view=None, metadata=None, detector=False, tomato_leaf=None,
                 providers=("CPUExecutionProvider",)):
        self.meta = load_metadata(metadata)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        mk = lambda p: ort.InferenceSession(p, opts, providers=list(providers))
        self.crop_classes = self.meta["crop_view"]["classes"]
        self.crop = mk(crop_view or os.path.join(PRIVATE, "cropscout-crop-view.onnx"))
        self.base_classes = self.meta["disease"]["classes"]
        self.base = mk(condition or os.path.join(PRIVATE, "cropscout-disease.onnx"))
        self.spec = {}
        for s in self.meta.get("condition_specialists", []):
            p = os.path.join(PRIVATE, f"cropscout-{s['id']}.onnx")
            if os.path.exists(p):
                self.spec[s["families"][0]] = (s, mk(p))
        if tomato_leaf:  # a candidate tomato-leaf specialist (same 46-class output as the general model)
            entry = dict(id="tomato-leaf", families=["Tomato_leaf"], classes=self.base_classes)
            self.spec["Tomato_leaf"] = (entry, mk(tomato_leaf))
        self.detector = None
        if detector:
            d = self.meta["leaf_detector"]
            self.det_cfg = d
            self.detector = mk(os.path.join(PRIVATE, "cropscout-leaf-detector.onnx"))
        self.t = self.meta["thresholds"]

    @staticmethod
    def run(sess, x):
        return sess.run(None, {sess.get_inputs()[0].name: x})[0][0].astype(np.float64)

    # ------------------------------------------------------------ gates
    def crop_gate(self, x):
        p = self.run(self.crop, x)
        order = np.argsort(-p)
        top, second = order[0], order[1]
        label = self.crop_classes[top]
        conf, margin = p[top], p[top] - p[second]
        parts = label.split("_")
        ok = label != "Other" and conf >= self.t["crop_confidence"] and margin >= self.t["crop_margin"]
        return dict(label=label, conf=float(conf), margin=float(margin), ok=bool(ok),
                    crop=parts[0] if ok else None, organ=parts[1] if ok else None)

    def safeguards(self, probs, classes, crop, organ, min_conf=None):
        cands = sorted(((probs[i], c) for i, c in enumerate(classes)
                        if c["crop"].lower() == crop.lower() and c["organ"] == organ),
                       key=lambda pc: -pc[0])
        if not cands:
            return None
        mass = sum(p for p, _ in cands)
        top_p, top_c = cands[0]
        runner = cands[1][0] if len(cands) > 1 else 0.0
        opposite = next((p for p, c in cands if c["healthy"] != top_c["healthy"]), None)
        sep = top_p - opposite if opposite is not None else 1.0
        family = f"{crop}_{organ}"
        need = self.t.get("condition_confidence_by_family", {}).get(family, self.t["condition_confidence"])
        if min_conf is not None:
            need = max(need, min_conf)
        ok = (mass >= self.t["condition_mass"] and top_p >= need
              and top_p - runner >= self.t["condition_margin"] and sep >= self.t["healthy_margin"])
        return dict(label=top_c["label"], healthy=bool(top_c["healthy"]), conf=float(top_p), mass=float(mass),
                    margin=float(top_p - runner), sep=float(sep), ok=bool(ok),
                    top3=[(c["label"], round(float(p), 3)) for p, c in cands[:3]])

    def condition(self, x, crop, organ):
        family = f"{crop}_{organ}"
        spec = self.spec.get(family)
        if spec and spec[0].get("routing_policy_id") == LEMON_POLICY:
            base = self.safeguards(self.run(self.base, x), self.base_classes, crop, organ)
            s = self.safeguards(self.run(spec[1], x), spec[0]["classes"], crop, organ,
                                min_conf=spec[0]["specialist_min_confidence"])
            base_healthy = base and base["ok"] and base["healthy"]
            use_spec = s and not s["healthy"] and not base_healthy
            return dict(s if use_spec else base, route="lemon-hybrid:" + ("specialist" if use_spec else "base"))
        if spec:
            return dict(self.safeguards(self.run(spec[1], x), spec[0]["classes"], crop, organ), route=spec[0]["id"])
        return dict(self.safeguards(self.run(self.base, x), self.base_classes, crop, organ), route="base")

    def classify(self, x):
        g = self.crop_gate(x)
        out = dict(crop_gate=g)
        if not g["ok"]:
            out["verdict"] = "abstain (crop: %s %.0f%%)" % (g["label"], 100 * g["conf"])
            out["shown"] = None
            return out
        c = self.condition(x, g["crop"], g["organ"])
        out["condition"] = c
        if c is None:
            out["verdict"], out["shown"] = f"{g['label']} (no condition classes)", None
        elif c["ok"]:
            out["shown"] = c["label"]
            out["verdict"] = "%s %.0f%%%s" % (c["label"], 100 * c["conf"], "" if c["route"] == "base" else f" [{c['route']}]")
        else:
            out["shown"] = None
            out["verdict"] = "abstain (%s; closest %s %.0f%%)" % (g["label"], c["label"], 100 * c["conf"])
        return out

    # ------------------------------------------------------------ modes
    def photo(self, img):
        return self.classify(photo_tensor(img))

    def camera_square(self, img):
        sq = centre_square(img)
        s = sq.size[0]
        return sq.resize((CAMERA_SIDE, CAMERA_SIDE), Image.BICUBIC if s < CAMERA_SIDE else Image.BOX) if s != CAMERA_SIDE else sq

    def detect(self, square):
        """Boxes (normalised to the square) at or above the score threshold."""
        d = self.det_cfg
        x = to_tensor(halve_to(square), d["input_size"])
        rows = self.detector.run(None, {self.detector.get_inputs()[0].name: x})[0][0]
        n = d["input_size"]
        out = []
        for x1, y1, x2, y2, score, cls in rows:
            if score < d["score_threshold"]:
                continue
            b = [min(1, max(0, v / n)) for v in (x1, y1, x2, y2)]
            if b[2] > b[0] and b[3] > b[1]:
                out.append(dict(box=b, score=float(score), kind=d["classes"][int(round(cls))]))
        return out

    def leaf_boxes(self, dets, max_leaves=None):
        """The boxes the page would classify: big enough, best first, overlapping duplicates dropped."""
        d = self.det_cfg
        side = lambda b: max(b[2] - b[0], b[3] - b[1])
        keep = []
        for det in sorted((x for x in dets if side(x["box"]) >= d["min_box_side"]), key=lambda x: -x["score"]):
            if any(iou(det["box"], k["box"]) > 0.7 for k in keep):
                continue
            keep.append(det)
        return keep[:max_leaves or d["max_leaves"]]

    def leaf_crop(self, square, box):
        """The page's liveLeafTensor: a padded square around the box, cut from the full square."""
        S = square.size[0]
        x1, y1, x2, y2 = box
        wanted = max(1, min(1, max(x2 - x1, y2 - y1) * self.det_cfg["crop_padding"]) * S)
        unit = 1
        while wanted / (unit * 2) >= LIVE_MIN_SAMPLE_SIDE:
            unit *= 2
        side = max(unit, min(round(wanted / unit), S // unit) * unit)
        clamp = lambda v: min(max(round(v), 0), S - side)
        left = clamp((x1 + x2) / 2 * S - side / 2)
        top = clamp((y1 + y2) / 2 * S - side / 2)
        return square.crop((left, top, left + side, top + side))

    def live(self, img):
        """One live frame: whole square, or each leaf with the finder on."""
        square = self.camera_square(img)
        if not self.detector:
            return dict(mode="square", results=[self.classify(to_tensor(halve_to(square), SIZE))])
        dets = self.detect(square)
        largest = max((max(d["box"][2] - d["box"][0], d["box"][3] - d["box"][1]) for d in dets), default=0)
        if not dets or largest >= self.det_cfg["whole_square_side"]:
            return dict(mode="square", results=[self.classify(to_tensor(halve_to(square), SIZE))])
        res = []
        for det in self.leaf_boxes(dets):
            r = self.classify(to_tensor(halve_to(self.leaf_crop(square, det["box"])), SIZE))
            r["box"], r["score"], r["kind"] = det["box"], det["score"], det["kind"]
            res.append(r)
        return dict(mode="leaves", results=res)


def iou(a, b):
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / u if u > 0 else 0


def open_rgb(path):
    img = Image.open(path)
    img.load()
    return img.convert("RGB")


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--condition")
    ap.add_argument("--crop-view")
    ap.add_argument("--tomato-leaf")
    ap.add_argument("--detector", action="store_true")
    args = ap.parse_args()
    p = Pipeline(args.condition, args.crop_view, detector=args.detector, tomato_leaf=args.tomato_leaf)
    for path in args.images:
        img = open_rgb(path)
        ph = p.photo(img)
        lv = p.live(img)
        print(os.path.basename(path))
        print("  photo:", ph["verdict"])
        print(f"  live ({lv['mode']}):", " | ".join(r["verdict"] for r in lv["results"]))


if __name__ == "__main__":
    sys.exit(main())
