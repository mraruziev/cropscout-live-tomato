"""
CropSCOUT-in-the-loop: the robot's per-plant decision comes from the team's real tomato models
(crop-view identity gate -> condition classifier -> spray-rules dose), not from the sim's labels.

It imports the CropSCOUT repo's own code (live/live_detect.py Pipeline, live/spray.py rules), so the
sim and the webcam demo run the *same* preprocessing, thresholds and dose logic.

What the model looks at when the robot stops at a plant (--source):
  photos  (default)  a real leaf photo assigned to each sim plant: diseased plants get one from the
                     PlantVillage disease folders in the repo, healthy plants from Tomato___healthy
                     (fetch that class too, or healthy plants fall back to the sim frame).
  sim                the MuJoCo nozzle-camera render itself. Expect the identity gate to abstain —
                     flat synthetic leaves look nothing like training photos. Honest domain-gap check.
  webcam             a live frame from camera 0 each time the robot stops: hold a leaf up to it.

Setup (once):  pip install onnxruntime opencv-python
               python <cropscout-live-tomato>/live/fetch_models.py      # downloads the two ONNX models
The repo is found automatically: this folder is its sim/ (or it sits next to this folder, or in
Documents\\cropscout-live-tomato);
otherwise pass --cropscout-dir or set CROPSCOUT_DIR.
"""
import os
import random
import sys
from pathlib import Path

import numpy as np

MODEL_FILES = ("cropscout-crop-view.onnx", "cropscout-condition.onnx")


def find_repo(explicit=None):
    here = Path(__file__).resolve().parent
    for c in (explicit, os.environ.get("CROPSCOUT_DIR"), here.parent, here.parent / "cropscout-live-tomato",
              Path.home() / "Documents" / "cropscout-live-tomato"):
        if c and (Path(c) / "live" / "live_detect.py").exists():
            return Path(c)
    raise FileNotFoundError("CropSCOUT repo not found. Pass --cropscout-dir <path to cropscout-live-tomato> "
                            "or set the CROPSCOUT_DIR environment variable.")


class CropScout:
    """Thin wrapper over the repo's Pipeline + spray rules: one BGR frame -> assessment."""

    def __init__(self, repo=None, threads=2):
        self.repo = find_repo(repo)
        live = self.repo / "live"
        if str(live) not in sys.path:
            sys.path.insert(0, str(live))
        import live_detect                                     # noqa: E402  (their code)
        import spray                                           # noqa: E402
        self.ld, self.spray = live_detect, spray
        models = live / "models"
        missing = [n for n in MODEL_FILES if not (models / n).exists()]
        if missing:
            raise FileNotFoundError(f"models missing in {models}: {missing}. Run:  python {live / 'fetch_models.py'}")
        self.pipe = live_detect.Pipeline(models, live / "model-metadata.json", threads)
        self.rules = spray.load_rules(self.repo / "vision" / "spray-rules.json")

    def assess(self, bgr):
        """Single-frame version of the live loop (no EMA / consensus: one look per plant)."""
        square = self.pipe.square(bgr)
        x = self.pipe.to_tensor(square)
        crop_p = self.pipe.run_crop(x)
        fam, crop_conf, crop_margin = self.pipe.crop_verdict(crop_p)
        crop_top = self.pipe.crop_classes[int(np.argmax(crop_p))]
        verdict = None
        if fam in self.pipe.cond_families:
            verdict = self.pipe.condition_verdict(fam, self.pipe.run_cond(x))
        severity = self.spray.estimate_severity(square, self.rules)
        certain = verdict is not None and verdict["certain"]
        decision = self.spray.decide(self.rules, verdict["label"] if verdict else None, certain, severity)
        return dict(family=fam, crop_top=crop_top, crop_conf=crop_conf, crop_margin=crop_margin,
                    verdict=verdict, severity=severity, decision=decision)


# ----------------------------------------------------------------------------- image sources
class SimSource:
    name = "sim-frame"

    def frame(self, plant, cam):
        return np.ascontiguousarray(cam.rgb()[..., ::-1])       # RGB -> BGR for OpenCV-style code


class PhotoSource:
    """Each sim plant gets a fixed real leaf photo (seeded, so runs are repeatable)."""

    def __init__(self, repo, plants, seed=0, val_dir=None):
        import cv2
        self.cv2 = cv2
        here = Path(__file__).resolve().parent
        cands = [Path(val_dir)] if val_dir else [here / "leaf_photos", repo / "data" / "raw" / "plantvillage" / "val",
                                                 repo / "data" / "raw" / "plantvillage" / "train"]
        disease_dirs, healthy_dir = [], None
        for val in cands:
            if not val.exists():
                continue
            disease_dirs += sorted(d for d in val.glob("Tomato___*") if d.is_dir() and "healthy" not in d.name.lower())
            healthy_dir = healthy_dir or next((d for d in val.glob("Tomato___*") if "healthy" in d.name.lower()), None)
        if not disease_dirs:
            raise FileNotFoundError(f"no PlantVillage tomato folders in {[str(c) for c in cands]} "
                                    f"(double-click 5_FETCH_LEAF_PHOTOS.bat, or run tools/classifier/fetch_plantvillage.py)")
        by_cls = {}
        for d in disease_dirs:
            by_cls.setdefault(d.name, d)
        rng = random.Random(seed)
        self.assign = {}
        for p in plants:
            # a plant whose sim leaves carry a known PlantVillage class gets a photo of that same class
            cls = p[4] if len(p) > 4 else None
            d = (by_cls.get(cls) or rng.choice(disease_dirs)) if p[3] else healthy_dir
            files = sorted(f for f in d.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png")) if d else []
            self.assign[p[0]] = rng.choice(files) if files else None
        n_photo = sum(v is not None for v in self.assign.values())
        print(f"[cropscout] photos: {len(disease_dirs)} disease folders, "
              f"healthy folder {'found' if healthy_dir else 'MISSING (healthy plants use the sim frame)'}, "
              f"{n_photo}/{len(plants)} plants assigned a photo")
        self.last = None

    def frame(self, plant, cam):
        path = self.assign.get(plant[0])
        self.last = str(path) if path else "sim-frame"
        if path is None:
            return SimSource().frame(plant, cam)
        img = self.cv2.imread(str(path))
        if img is None:
            raise RuntimeError(f"could not read {path}")
        return img

    @property
    def name(self):
        return self.last or "photo"


class WebcamSource:
    name = "webcam"

    def __init__(self, index=0):
        import cv2
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"could not open camera {index}")

    def frame(self, plant, cam):
        for _ in range(5):                                       # flush stale frames
            ok, img = self.cap.read()
        if not ok:
            raise RuntimeError("camera read failed")
        return img


# ----------------------------------------------------------------------------- the policy
class CropScoutPolicy:
    """policy(plant, detections, mission) -> dict for Mission: the CropSCOUT verdict decides."""

    def __init__(self, cs: CropScout, source):
        self.cs, self.source = cs, source

    def __call__(self, plant, detections, mission):
        bgr = self.source.frame(plant, mission.cam)
        r = self.cs.assess(bgr)
        v, dec = r["verdict"], r["decision"]
        label = v["label"] if (v and v["certain"]) else (
            "abstain:other" if r["family"] is None and r["crop_top"] == "Other" else
            "abstain:uncertain" if v is None else f"uncertain:{v['label']}")
        # which heads: the ones at the heights where the sim's own labels see blight (if any), else all three
        from mission import heads_for_heights
        zs = [d.xyz[2] for d in detections if d.label == "leaf_blight" and d.xyz is not None]
        heads = heads_for_heights(zs) if dec.action == "spray" else ()
        return dict(spray=dec.action == "spray", dose_ml=float(dec.dose_ml), heads=heads, label=label,
                    action=dec.action, diagnosis=v["diagnosis"] if v else None,
                    confidence=round(v["conf"], 3) if v else round(r["crop_conf"], 3),
                    certain=bool(v and v["certain"]), family=r["family"] or r["crop_top"],
                    severity=dec.severity_band, lesion_fraction=round(dec.lesion_fraction, 3),
                    product=dec.product, interval_days=dec.interval_days, reason=dec.reason,
                    image=getattr(self.source, "name", "?"),
                    frame=bgr, hud=self.hud_state(r, heads))

    def hud_state(self, r, heads):
        """The `state` dict that the repo's live_detect.draw() overlays on a frame - same HUD as the webcam app."""
        v, dec, fam = r["verdict"], r["decision"], r["family"]
        gates = self.cs.pipe.gates
        if fam is None:
            if r["crop_top"] == "Other" and r["crop_conf"] >= gates.crop_confidence:
                st = dict(status="other", line1="Not a tomato or cucumber", line2=f"Other {r['crop_conf'] * 100:.0f}%",
                          line3="Point at a tomato leaf or fruit", spray="SPRAY 0%  not a tomato or cucumber")
            else:
                st = dict(status="uncertain", line1="Looking...",
                          line2=f"best guess {r['crop_top'].replace('_', ' ')} {r['crop_conf'] * 100:.0f}%  margin {r['crop_margin']:.2f}",
                          line3=f"need >= {gates.crop_confidence:.2f} conf and >= {gates.crop_margin:.2f} margin",
                          spray="SPRAY 0%  no plant confirmed in the square")
        elif v is None:
            st = dict(status="uncertain", line1=f"{fam.replace('_', ' ')} {r['crop_conf'] * 100:.0f}%",
                      line2="specialist not loaded", line3="", spray="SPRAY 0%  condition not confirmed yet")
        elif v["certain"]:
            st = dict(status="identified", urgency=v["urgency"], line1=f"{v['diagnosis']}  {v['conf'] * 100:.0f}%",
                      line2=f"{fam.replace('_', ' ')}  {r['crop_conf'] * 100:.0f}%   urgency: {v['urgency']}",
                      line3=f"margin {v['margin']:.2f}  mass {v['mass']:.2f}  healthy/disease sep {v['separation']:.2f}",
                      spray=dec.summary() + (f"  heads {heads}" if heads else ""))
        else:
            st = dict(status="uncertain", line1=f"{fam.replace('_', ' ')} {r['crop_conf'] * 100:.0f}%  (uncertain)",
                      line2=f"leaning {v['diagnosis']} {v['conf'] * 100:.0f}%",
                      line3=f"margin {v['margin']:.2f}  mass {v['mass']:.2f}  sep {v['separation']:.2f}",
                      spray=dec.summary())
        st["ms"] = 0.0
        return st


def make_policy(gh, source="photos", repo=None, seed=0, threads=2):
    cs = CropScout(repo, threads)
    src = {"photos": lambda: PhotoSource(cs.repo, getattr(gh, "mission_plants", gh.plants), seed),
           "sim": SimSource, "webcam": WebcamSource}[source]()
    print(f"[cropscout] repo {cs.repo}  source={source}")
    return CropScoutPolicy(cs, src)
