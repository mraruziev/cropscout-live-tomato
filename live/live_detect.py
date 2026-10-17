"""CropSCOUT live tomato detection on a laptop webcam (OpenCV + ONNX Runtime).

A local port of the v26 `runLiveRecognition` loop against the public v29 models:

  camera frame -> center square -> 224x224 -> crop-view model -> identity gate
               -> condition model (Tomato_leaf / Tomato_fruit / Cucumber_fruit)
               -> condition gates -> EMA smoothing -> 2-frame consensus -> overlay

Preprocessing and thresholds follow live/model-metadata.json exactly:
RGB, CHW, /255, no mean/std, model output is already softmax.

Keys:  q / Esc  quit      space  freeze (print full top-5 to the terminal)
       s        save a snapshot of the analysed square to live/snapshots/
       m        toggle the lesion mask view (red = lesion-like, green = healthy)

A spray estimate (vision/spray-rules.json) is shown under the verdict: dose scales
with the share of lesion-coloured leaf pixels, and healthy leaves get no spray.

Usage:
    .venv/bin/python live/live_detect.py                 # default camera
    .venv/bin/python live/live_detect.py --camera 1      # another camera
    .venv/bin/python live/live_detect.py --interval-ms 250
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spray import SeveritySmoother, decide, estimate_severity, lesion_overlay, load_rules  # noqa: E402

HERE = Path(__file__).resolve().parent
IMAGE_SIZE = 224
EMA_NEW = 0.62  # v26: 0.62*new + 0.38*old
CONSENSUS_FRAMES = 2
OTHER = "Other"


# --------------------------------------------------------------------------- models
@dataclass
class Gates:
    crop_confidence: float
    crop_margin: float
    condition_confidence: float
    condition_margin: float
    condition_mass: float
    healthy_margin: float
    by_family: dict


class Pipeline:
    def __init__(self, model_dir: Path, meta_path: Path, threads: int):
        meta = json.loads(meta_path.read_text())
        t = meta["thresholds"]
        self.gates = Gates(
            t["crop_confidence"], t["crop_margin"], t["condition_confidence"],
            t["condition_margin"], t["condition_mass"], t["healthy_margin"],
            t.get("condition_confidence_by_family", {}),
        )
        self.crop_classes: list[str] = meta["crop_view"]["classes"]
        spec = next(s for s in meta["condition_specialists"] if s["id"] == "condition")
        self.cond_families: set[str] = set(spec["families"])
        self.cond_classes: list[dict] = spec["classes"]
        self.cond_labels = [c["label"] for c in self.cond_classes]

        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = ["CPUExecutionProvider"]
        self.crop_sess = ort.InferenceSession(str(model_dir / "cropscout-crop-view.onnx"), so, providers=providers)
        self.cond_sess = ort.InferenceSession(str(model_dir / "cropscout-condition.onnx"), so, providers=providers)
        self.crop_in = self.crop_sess.get_inputs()[0].name
        self.cond_in = self.cond_sess.get_inputs()[0].name

        n_crop = self.crop_sess.get_outputs()[0].shape[-1]
        n_cond = self.cond_sess.get_outputs()[0].shape[-1]
        assert n_crop == len(self.crop_classes), (n_crop, len(self.crop_classes))
        assert n_cond == len(self.cond_labels), (n_cond, len(self.cond_labels))

    # ---- preprocessing: mirrors v29 photo path (center crop, antialiased resize, RGB/255)
    @staticmethod
    def square(frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        s = min(h, w)
        y0, x0 = (h - s) // 2, (w - s) // 2
        return frame[y0:y0 + s, x0:x0 + s]

    @staticmethod
    def to_tensor(square_bgr: np.ndarray) -> np.ndarray:
        img = cv2.resize(square_bgr, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_AREA)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        return np.ascontiguousarray(img.transpose(2, 0, 1)[None])  # [1,3,224,224]

    def run_crop(self, x: np.ndarray) -> np.ndarray:
        return self.crop_sess.run(None, {self.crop_in: x})[0][0]

    def run_cond(self, x: np.ndarray) -> np.ndarray:
        return self.cond_sess.run(None, {self.cond_in: x})[0][0]

    # ---- gates (evaluated on smoothed probabilities, never renormalised)
    def crop_verdict(self, p: np.ndarray) -> tuple[str | None, float, float]:
        order = np.argsort(p)[::-1]
        top, second = p[order[0]], p[order[1]]
        fam = self.crop_classes[order[0]]
        margin = float(top - second)
        ok = top >= self.gates.crop_confidence and margin >= self.gates.crop_margin and fam != OTHER
        return (fam if ok else None), float(top), margin

    def condition_verdict(self, fam: str, p: np.ndarray) -> dict:
        idx = [i for i, c in enumerate(self.cond_classes) if c["label"].startswith(fam + "_")]
        fam_p = p[idx]
        mass = float(fam_p.sum())
        order = np.argsort(fam_p)[::-1]
        best_i = idx[order[0]]
        best = self.cond_classes[best_i]
        conf = float(fam_p[order[0]])
        # margin against the runner-up over the whole output (raw global probabilities)
        global_sorted = np.sort(p)[::-1]
        margin = float(global_sorted[0] - global_sorted[1]) if p[best_i] == global_sorted[0] else 0.0
        healthy_i = [i for i in idx if self.cond_classes[i]["healthy"]]
        p_healthy = float(p[healthy_i[0]]) if healthy_i else 0.0
        p_disease = float(max((p[i] for i in idx if not self.cond_classes[i]["healthy"]), default=0.0))
        separation = abs(p_healthy - p_disease)
        need_conf = self.gates.by_family.get(fam, self.gates.condition_confidence)
        certain = (
            conf >= need_conf
            and margin >= self.gates.condition_margin
            and mass >= self.gates.condition_mass
            and separation >= self.gates.healthy_margin
        )
        top5 = [(self.cond_classes[idx[j]]["label"], float(fam_p[j])) for j in order[:5]]
        return dict(label=best["label"], diagnosis=best["diagnosis"], urgency=best["urgency"],
                    healthy=best["healthy"], conf=conf, margin=margin, mass=mass,
                    separation=separation, certain=certain, top5=top5)


# --------------------------------------------------------------------------- smoothing
class Ema:
    def __init__(self):
        self.v: np.ndarray | None = None

    def push(self, p: np.ndarray) -> np.ndarray:
        self.v = p.copy() if self.v is None else EMA_NEW * p + (1 - EMA_NEW) * self.v
        return self.v

    def reset(self):
        self.v = None


# --------------------------------------------------------------------------- drawing
COL = {"none": (80, 200, 80), "routine": (0, 190, 255), "urgent": (0, 0, 230),
       "uncertain": (160, 160, 160), "other": (120, 120, 120)}


def put(img, text, org, scale=0.6, color=(255, 255, 255), thick=2):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def draw(frame, state: dict, fps: float):
    h, w = frame.shape[:2]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    status = state.get("status", "loading")
    color = COL["uncertain"]
    if status == "identified":
        color = COL.get(state["urgency"], COL["routine"])
    elif status == "other":
        color = COL["other"]
    cv2.rectangle(frame, (x0, y0), (x0 + s - 1, y0 + s - 1), color, 3)

    # dim outside the square so what you see is what gets analysed
    if x0 > 0:
        frame[:, :x0] = (frame[:, :x0] * 0.35).astype(np.uint8)
        frame[:, x0 + s:] = (frame[:, x0 + s:] * 0.35).astype(np.uint8)
    if y0 > 0:
        frame[:y0] = (frame[:y0] * 0.35).astype(np.uint8)
        frame[y0 + s:] = (frame[y0 + s:] * 0.35).astype(np.uint8)

    put(frame, state.get("line1", "Starting..."), (16, 34), 0.8, color)
    put(frame, state.get("line2", ""), (16, 64), 0.6)
    put(frame, state.get("line3", ""), (16, 90), 0.55, (200, 200, 200))
    spray = state.get("spray") or "SPRAY 0%  point the square at a tomato leaf"
    spray_color = (0, 170, 255) if not spray.startswith("SPRAY 0%") else (200, 200, 200)
    put(frame, spray, (16, h - 52), 0.8, spray_color)
    put(frame, f"{fps:4.1f} fps  infer {state.get('ms', 0):5.1f} ms  "
               f"q quit  space freeze  s snapshot  m mask", (16, h - 16), 0.5, (220, 220, 220), 1)


# --------------------------------------------------------------------------- main loop
def ensure_camera_permission(timeout_s: float = 120.0) -> None:
    """Ask macOS for camera access and wait for the answer, so the first run
    does not fail before the user has seen the prompt. Needs pyobjc; without it
    OpenCV asks on its own and the first run may have to be repeated."""
    try:
        import AVFoundation as AV  # type: ignore
        from Foundation import NSDate, NSRunLoop  # type: ignore
    except ImportError:
        return
    status = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
    if status == 3:  # authorized
        return
    if status in (1, 2):  # restricted / denied
        raise SystemExit("Camera access is denied for this app. Enable it in System Settings > "
                         "Privacy & Security > Camera (look for 'CropSCOUT Live' or your terminal), then rerun.")
    print("Camera permission: waiting for you to click Allow in the macOS dialog...", flush=True)
    result = {}
    AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AV.AVMediaTypeVideo, lambda granted: result.__setitem__("granted", bool(granted)))
    deadline = NSDate.dateWithTimeIntervalSinceNow_(timeout_s)
    while "granted" not in result and NSDate.date().compare_(deadline) < 0:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
    if not result.get("granted"):
        raise SystemExit("Camera access was not granted. If no dialog appeared, this process has no camera usage "
                         "description: start the demo with live/run.sh instead.")


def open_camera(index: int, width: int, height: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--interval-ms", type=int, default=300, help="minimum gap between inference runs")
    ap.add_argument("--threads", type=int, default=1, help="ORT intra-op threads (1 mimics the phone)")
    ap.add_argument("--models", default=str(HERE / "models"))
    ap.add_argument("--meta", default=str(HERE / "model-metadata.json"))
    ap.add_argument("--rules", default=str(HERE.parent / "vision" / "spray-rules.json"), help="spray rules JSON")
    ap.add_argument("--headless", action="store_true", help="no window; print verdicts to the terminal")
    ap.add_argument("--max-seconds", type=float, default=0, help="stop after N seconds (for testing)")
    args = ap.parse_args()

    model_dir = Path(args.models)
    missing = [n for n in ("cropscout-crop-view.onnx", "cropscout-condition.onnx") if not (model_dir / n).exists()]
    if missing:
        raise SystemExit(f"Missing {missing} in {model_dir}. Run: .venv/bin/python live/fetch_models.py")

    pipe = Pipeline(model_dir, Path(args.meta), args.threads)
    rules = load_rules(args.rules)
    severity_ema = SeveritySmoother(rules)
    show_mask = False
    ensure_camera_permission()
    cap = open_camera(args.camera, args.width, args.height)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera {args.camera}. On macOS allow camera access for your terminal "
                         f"in System Settings > Privacy & Security > Camera.")

    crop_ema, cond_ema = Ema(), Ema()
    last_family: str | None = None
    agree_key, agree_n = None, 0
    state: dict = {"status": "loading", "line1": "Loading..."}
    last_run = 0.0
    fps_hist: deque[float] = deque(maxlen=30)
    t_prev = time.perf_counter()
    t_start = t_prev
    last_printed = None
    snap_dir = HERE / "snapshots"
    last_square = None

    while True:
        ok, frame = cap.read()
        if not ok:
            print("camera read failed")
            break
        now = time.perf_counter()
        fps_hist.append(1.0 / max(now - t_prev, 1e-6))
        t_prev = now
        last_square = pipe.square(frame)

        if (now - last_run) * 1000 >= args.interval_ms:
            last_run = now
            t0 = time.perf_counter()
            x = pipe.to_tensor(last_square)
            crop_p = crop_ema.push(pipe.run_crop(x))
            fam, crop_conf, crop_margin = pipe.crop_verdict(crop_p)
            crop_top = pipe.crop_classes[int(np.argmax(crop_p))]

            if fam != last_family:
                cond_ema.reset()
                severity_ema.reset()
                agree_key, agree_n = None, 0
                last_family = fam

            if fam is None:
                key = f"uncertain|{crop_top}"
                verdict = None
                status = "other" if crop_top == OTHER and crop_conf >= pipe.gates.crop_confidence else "uncertain"
            elif fam in pipe.cond_families:
                cond_p = cond_ema.push(pipe.run_cond(x))
                verdict = pipe.condition_verdict(fam, cond_p)
                status = "identified" if verdict["certain"] else "uncertain"
                key = f"{fam}|{status}|{verdict['label'] if verdict['certain'] else '-'}"
            else:  # Cucumber_leaf: specialist not loaded in this demo
                verdict = None
                status = "uncertain"
                key = f"{fam}|nospecialist"
            severity = severity_ema.push(estimate_severity(last_square, rules))
            ms = (time.perf_counter() - t0) * 1000

            # 2-frame consensus before showing a verdict (an uncertain result resets it)
            if key == agree_key:
                agree_n += 1
            else:
                agree_key, agree_n = key, 1
            if status == "identified" and agree_n < CONSENSUS_FRAMES:
                status = "uncertain"

            if status == "identified":
                state = dict(status=status, urgency=verdict["urgency"],
                             line1=f"{verdict['diagnosis']}  {verdict['conf'] * 100:.0f}%",
                             line2=f"{fam.replace('_', ' ')}  {crop_conf * 100:.0f}%   urgency: {verdict['urgency']}",
                             line3=f"margin {verdict['margin']:.2f}  mass {verdict['mass']:.2f}  "
                                   f"healthy/disease sep {verdict['separation']:.2f}", ms=ms)
            elif status == "other":
                state = dict(status=status, line1="Not a tomato or cucumber",
                             line2=f"Other {crop_conf * 100:.0f}%", line3="Point at a tomato leaf or fruit", ms=ms)
            elif fam is None:
                state = dict(status="uncertain", line1="Looking...",
                             line2=f"best guess {crop_top.replace('_', ' ')} {crop_conf * 100:.0f}%  margin {crop_margin:.2f}",
                             line3=f"need >= {pipe.gates.crop_confidence:.2f} conf and >= {pipe.gates.crop_margin:.2f} margin", ms=ms)
            elif verdict is None:
                state = dict(status="uncertain", line1=f"{fam.replace('_', ' ')} {crop_conf * 100:.0f}%",
                             line2="Cucumber leaf specialist not loaded", line3="fetch_models.py --all", ms=ms)
            else:
                state = dict(status="uncertain", line1=f"{fam.replace('_', ' ')} {crop_conf * 100:.0f}%  (uncertain)",
                             line2=f"leaning {verdict['diagnosis']} {verdict['conf'] * 100:.0f}%",
                             line3=f"margin {verdict['margin']:.2f}  mass {verdict['mass']:.2f}  "
                                   f"sep {verdict['separation']:.2f}  agree {agree_n}/{CONSENSUS_FRAMES}", ms=ms)

            confirmed = status == "identified" and verdict is not None
            decision = decide(rules, verdict["label"] if verdict else None, confirmed, severity)
            if status == "other":
                state["spray"] = "SPRAY 0%  not a tomato or cucumber"
            elif fam is None:
                state["spray"] = "SPRAY 0%  no plant confirmed in the square"
            else:
                state["spray"] = decision.summary()

            if args.headless and state["line1"] != last_printed:
                print(f"[{now - t_start:6.1f}s] {state['line1']} | {state.get('line2', '')} | {state.get('spray', '')} | {ms:.1f} ms")
                last_printed = state["line1"]

        if args.max_seconds and now - t_start >= args.max_seconds:
            break

        if args.headless:
            continue

        shown = frame.copy()
        if show_mask and last_square is not None:
            h0, w0 = frame.shape[:2]
            s0 = min(h0, w0)
            y0, x0 = (h0 - s0) // 2, (w0 - s0) // 2
            shown[y0:y0 + s0, x0:x0 + s0] = lesion_overlay(last_square, rules=rules)
        draw(shown, state, float(np.mean(fps_hist)))
        cv2.imshow("CropSCOUT live (local)", shown)
        k = cv2.waitKey(1) & 0xFF
        if k in (ord("q"), 27):
            break
        if k == ord(" ") and last_square is not None:
            x = pipe.to_tensor(last_square)
            cp = pipe.run_crop(x)
            print("\n=== FREEZE ===")
            for i in np.argsort(cp)[::-1]:
                print(f"  crop-view  {pipe.crop_classes[i]:16s} {cp[i]:.3f}")
            fam_now = pipe.crop_classes[int(np.argmax(cp))]
            if fam_now in pipe.cond_families:
                v = pipe.condition_verdict(fam_now, pipe.run_cond(x))
                for lbl, p in v["top5"]:
                    print(f"  condition  {lbl:40s} {p:.3f}")
                print(f"  -> {v['diagnosis']}  certain={v['certain']}")
        if k == ord("m"):
            show_mask = not show_mask
        if k == ord("s") and last_square is not None:
            snap_dir.mkdir(exist_ok=True)
            path = snap_dir / time.strftime("square-%Y%m%d-%H%M%S.jpg")
            cv2.imwrite(str(path), last_square)
            print(f"saved {path}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
