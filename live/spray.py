"""Spray estimate: how much to spray for a confirmed leaf or fruit condition.

Rules live in vision/spray-rules.json and are shared with the browser app
(vision/spray.js implements the same severity estimate and decision).

    decision = decide(rules, label, certain, severity)

- No spray when the verdict is not confirmed, the condition is healthy, the
  disorder is not an infection, or the condition is a virus (remove instead).
- Otherwise dose = rule.dose_ml x severity multiplier, where severity is the
  share of leaf pixels that look like lesions in the analysed square.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_RULES = HERE.parent / "vision" / "spray-rules.json"


def load_rules(path: Path | str = DEFAULT_RULES) -> dict:
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------------- severity
@dataclass
class Severity:
    lesion_fraction: float   # lesion pixels / (green + lesion pixels), 0..1
    leaf_cover: float        # (green + lesion pixels) / all pixels, 0..1
    band: str                # low | medium | high | unknown

    def known(self) -> bool:
        return self.band != "unknown"


DEFAULT_COLOUR = {"green_min_s": 40, "green_min_v": 50, "brown_min_s": 60, "dark_max_v": 85}
DEFAULT_ADJACENCY_RADIUS = 0.08   # lesions must lie within this share of the side of leaf tissue


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    kernel = np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)
    return cv2.dilate(mask.astype(np.uint8), kernel).astype(bool)


def lesion_masks(bgr: np.ndarray, rules: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return (green_mask, lesion_mask) as boolean arrays.

    Colour classes (OpenCV HSV scale: H 0-180, S and V 0-255), mirrored in vision/spray.js.
    Defaults were chosen on the labelled field leaves (live/eval_severity.py):
      green  : H 35-85, S > 40, V > 50             leaf tissue
      brown  : H 5-35 (yellow / orange / brown), S > 60, V > 30
               or 20 <= V < 85 with S > 30 and H < 35 or H > 150   dark necrotic, brown-black
    Everything else (grey, white, sky, deep shadow) is background.

    A brown pixel counts as a lesion only when it lies within the adjacency radius of
    leaf tissue, grown once: soil and bark away from any leaf no longer count, while
    spots on a leaf and brown patches next to green tissue still do.
    """
    cfg = (rules or {}).get("severity", {})
    col = {**DEFAULT_COLOUR, **cfg.get("colour", {})}
    radius_share = float(cfg.get("adjacency_radius", DEFAULT_ADJACENCY_RADIUS))
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(np.int16), hsv[..., 1].astype(np.int16), hsv[..., 2].astype(np.int16)
    green = (h >= 35) & (h <= 85) & (s > col["green_min_s"]) & (v > col["green_min_v"])
    brown = ((h >= 5) & (h < 35) & (s > col["brown_min_s"]) & (v > 30)) \
        | ((v < col["dark_max_v"]) & (v >= 20) & (s > 30) & ((h < 35) | (h > 150)))
    brown &= ~green
    radius = max(1, int(round(radius_share * bgr.shape[0])))
    lesion = brown & _dilate(green, radius)
    lesion = brown & _dilate(green | lesion, radius)
    return green, lesion


def estimate_severity(bgr: np.ndarray, rules: dict) -> Severity:
    cfg = rules["severity"]
    small = cv2.resize(bgr, (224, 224), interpolation=cv2.INTER_AREA) if bgr.shape[0] != 224 else bgr
    green, lesion = lesion_masks(small, rules)
    n_green, n_lesion = int(green.sum()), int(lesion.sum())
    total = small.shape[0] * small.shape[1]
    leaf_cover = (n_green + n_lesion) / total
    if leaf_cover < cfg["min_leaf_cover"] or (n_green + n_lesion) == 0:
        return Severity(0.0, leaf_cover, "unknown")
    frac = n_lesion / (n_green + n_lesion)
    return Severity(frac, leaf_cover, severity_band(frac, rules))


def severity_band(frac: float, rules: dict) -> str:
    cfg = rules["severity"]
    return "low" if frac <= cfg["low_max"] else "high" if frac >= cfg["high_min"] else "medium"


def severity_multiplier(severity, rules: dict) -> float:
    """Continuous dose factor: min at 0 % lesion area, max from full_at upwards."""
    m = rules["severity"].get("multiplier")
    if not m:  # legacy band table
        return rules["severity"]["multipliers"].get(severity.band if severity else "unknown", 1.0)
    if severity is None or not severity.known():
        return 1.0
    t = min(1.0, max(0.0, severity.lesion_fraction / float(m["full_at"])))
    return float(m["min"]) + (float(m["max"]) - float(m["min"])) * t


class SeveritySmoother:
    """EMA over frames for the live loop (same weight as the score smoothing)."""

    def __init__(self, rules: dict):
        self.alpha = float(rules["severity"].get("live_smoothing", 0.62))
        self.rules = rules
        self.frac: float | None = None
        self.cover: float | None = None

    def reset(self) -> None:
        self.frac = self.cover = None

    def push(self, raw: Severity) -> Severity:
        if raw.band == "unknown":          # no leaf: do not pull the average towards zero
            return Severity(self.frac or 0.0, raw.leaf_cover, "unknown") if self.frac is None else \
                Severity(self.frac, raw.leaf_cover, "unknown")
        if self.frac is None:
            self.frac, self.cover = raw.lesion_fraction, raw.leaf_cover
        else:
            self.frac = self.alpha * raw.lesion_fraction + (1 - self.alpha) * self.frac
            self.cover = self.alpha * raw.leaf_cover + (1 - self.alpha) * self.cover
        return Severity(self.frac, self.cover, severity_band(self.frac, self.rules))


def lesion_overlay(bgr: np.ndarray, alpha: float = 0.45, rules: dict | None = None) -> np.ndarray:
    """Tint lesion pixels red and healthy pixels green, for a debug view."""
    green, lesion = lesion_masks(bgr, rules)
    out = bgr.copy()
    out[green] = (out[green] * (1 - alpha) + np.array([0, 200, 0]) * alpha).astype(np.uint8)
    out[lesion] = (out[lesion] * (1 - alpha) + np.array([0, 0, 230]) * alpha).astype(np.uint8)
    return out


# --------------------------------------------------------------------------- decision
@dataclass
class SprayDecision:
    action: str            # none | spray | remove | wait
    label: str | None
    product: str | None
    dose_ml: float
    percent: int           # dose as % of units.max_dose_ml (0 when nothing is sprayed)
    spray_seconds: float
    interval_days: int | None
    severity_band: str
    lesion_fraction: float
    reason: str

    def summary(self) -> str:
        if self.action == "spray":
            sev = f", lesion area {self.lesion_fraction * 100:.0f}%" if self.severity_band != "unknown" else ""
            return f"SPRAY {self.percent}%  ({self.dose_ml:.0f} mL {self.product}, ~{self.spray_seconds:.1f} s pump{sev})"
        if self.action == "remove":
            return "SPRAY 0%  remove this plant (virus, spraying does not help)"
        if self.action == "wait":
            return "SPRAY 0%  condition not confirmed yet"
        return f"SPRAY 0%  {self.reason}"

    def to_dict(self) -> dict:
        return asdict(self)


def decide(rules: dict, label: str | None, certain: bool, severity: Severity | None) -> SprayDecision:
    band = severity.band if severity else "unknown"
    frac = severity.lesion_fraction if severity else 0.0
    if not certain or not label:
        return SprayDecision("wait", label, None, 0.0, 0, 0.0, None, band, frac,
                             "The condition did not pass every safeguard, so nothing is sprayed.")
    rule = rules["rules"].get(label, rules["default"])
    action = rule.get("action", "none")
    if action != "spray":
        return SprayDecision(action, label, None, 0.0, 0, 0.0, None, band, frac,
                             rule.get("reason", rules["actions"].get(action, "")))
    mult = severity_multiplier(severity, rules)
    dose = round(float(rule["dose_ml"]) * mult, 1)
    flow = float(rules["units"]["pump_ml_per_second"])
    seconds = round(dose / flow, 1) if flow > 0 else 0.0
    max_dose = float(rules["units"].get("max_dose_ml") or 0)
    percent = int(round(100 * dose / max_dose)) if max_dose > 0 else 0
    percent = max(0, min(100, percent))
    reason = rule.get("note") or f"{rule['product']} at the {band} severity rate."
    return SprayDecision("spray", label, rule["product"], dose, percent, seconds,
                         rule.get("interval_days"), band, frac, reason)
