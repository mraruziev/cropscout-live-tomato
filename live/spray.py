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


def lesion_masks(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (green_mask, lesion_mask) as boolean arrays.

    HSV ranges (OpenCV scale: H 0-180, S and V 0-255), mirrored in vision/spray.js:
      green  : H 35-85, S > 60, V > 50          healthy leaf tissue
      lesion : H 5-35,  S > 60, V > 40          yellow / orange / brown spots
               or V < 60 and S > 30             dark necrotic tissue
    Grey, white and very dark background pixels are counted as neither.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = (h >= 35) & (h <= 85) & (s > 60) & (v > 50)
    brown = (h >= 5) & (h < 35) & (s > 60) & (v > 40)
    dark = (v < 60) & (s > 30)
    lesion = (brown | dark) & ~green
    return green, lesion


def estimate_severity(bgr: np.ndarray, rules: dict) -> Severity:
    cfg = rules["severity"]
    small = cv2.resize(bgr, (224, 224), interpolation=cv2.INTER_AREA) if bgr.shape[0] != 224 else bgr
    green, lesion = lesion_masks(small)
    n_green, n_lesion = int(green.sum()), int(lesion.sum())
    total = small.shape[0] * small.shape[1]
    leaf_cover = (n_green + n_lesion) / total
    if leaf_cover < cfg["min_leaf_cover"] or (n_green + n_lesion) == 0:
        return Severity(0.0, leaf_cover, "unknown")
    frac = n_lesion / (n_green + n_lesion)
    band = "low" if frac <= cfg["low_max"] else "high" if frac >= cfg["high_min"] else "medium"
    return Severity(frac, leaf_cover, band)


def lesion_overlay(bgr: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    """Tint lesion pixels red and healthy pixels green, for a debug view."""
    green, lesion = lesion_masks(bgr)
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
    mult = rules["severity"]["multipliers"].get(band, 1.0)
    dose = round(float(rule["dose_ml"]) * mult, 1)
    flow = float(rules["units"]["pump_ml_per_second"])
    seconds = round(dose / flow, 1) if flow > 0 else 0.0
    max_dose = float(rules["units"].get("max_dose_ml") or 0)
    percent = int(round(100 * dose / max_dose)) if max_dose > 0 else 0
    percent = max(0, min(100, percent))
    reason = rule.get("note") or f"{rule['product']} at the {band} severity rate."
    return SprayDecision("spray", label, rule["product"], dose, percent, seconds,
                         rule.get("interval_days"), band, frac, reason)
