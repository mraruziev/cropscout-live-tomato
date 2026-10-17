"""Sanity tests for the spray estimate.  Run:  .venv/bin/python -m unittest live/test_spray.py"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spray import Severity, decide, estimate_severity, load_rules  # noqa: E402

GREEN = (40, 150, 40)     # BGR healthy leaf
BROWN = (20, 60, 120)     # BGR brown lesion
GREY = (128, 128, 128)    # background


def leaf(lesion_fraction: float, cover: float = 1.0) -> np.ndarray:
    """A leaf of `cover` of the square with brown stripes (8 px wide, every 32 px as a base
    unit) covering `lesion_fraction` of it, so lesions always touch leaf tissue."""
    img = np.zeros((224, 224, 3), np.uint8)
    img[:] = GREY
    n = int(224 * cover)
    img[:n, :] = GREEN
    stripe = 8
    period = 32
    stripes_per_period = lesion_fraction * period / stripe  # 0..4
    for start in range(0, 224, period):
        k = int(round(stripes_per_period))
        for j in range(k):
            x0 = start + j * stripe
            img[:n, x0:x0 + stripe] = BROWN
    return img


class SeverityTests(unittest.TestCase):
    rules = load_rules()

    def test_pure_green_is_low(self):
        s = estimate_severity(leaf(0.0), self.rules)
        self.assertEqual(s.band, "low")
        self.assertLess(s.lesion_fraction, 0.01)

    def test_brown_stripes_raise_severity(self):
        s = estimate_severity(leaf(0.5), self.rules)
        self.assertEqual(s.band, "high")
        self.assertAlmostEqual(s.lesion_fraction, 0.5, delta=0.03)

    def test_medium_band(self):
        s = estimate_severity(leaf(0.25), self.rules)
        self.assertEqual(s.band, "medium")

    def test_no_leaf_is_unknown(self):
        s = estimate_severity(leaf(0.0, cover=0.05), self.rules)
        self.assertEqual(s.band, "unknown")

    def test_brown_far_from_any_leaf_is_not_a_lesion(self):
        img = leaf(0.0, cover=0.5)              # top half leaf, bottom half grey
        img[160:, :] = BROWN                     # "soil" 48 px below the leaf, past the 18 px radius
        s = estimate_severity(img, self.rules)
        self.assertLess(s.lesion_fraction, 0.01)

    def test_shaded_green_is_leaf_not_lesion(self):
        img = leaf(0.0)
        img[:, :112] = (20, 70, 20)              # dark green shadow, BGR
        s = estimate_severity(img, self.rules)
        self.assertLess(s.lesion_fraction, 0.01)
        self.assertGreater(s.leaf_cover, 0.9)

    def test_live_smoothing_follows_frames(self):
        from spray import SeveritySmoother
        sm = SeveritySmoother(self.rules)
        a = sm.push(Severity(0.0, 0.9, "low"))
        b = sm.push(Severity(0.5, 0.9, "high"))
        self.assertAlmostEqual(a.lesion_fraction, 0.0)
        self.assertAlmostEqual(b.lesion_fraction, 0.62 * 0.5, places=6)
        c = sm.push(Severity(0.0, 0.0, "unknown"))     # losing the leaf keeps the last value
        self.assertAlmostEqual(c.lesion_fraction, b.lesion_fraction)
        self.assertEqual(c.band, "unknown")


class DecisionTests(unittest.TestCase):
    rules = load_rules()
    low, high = Severity(0.05, 0.9, "low"), Severity(0.5, 0.9, "high")

    def test_healthy_means_no_spray(self):
        d = decide(self.rules, "Tomato_leaf_healthy", True, self.high)
        self.assertEqual(d.action, "none")
        self.assertEqual(d.dose_ml, 0)

    def test_unconfirmed_means_wait(self):
        d = decide(self.rules, "Tomato_leaf_late_blight", False, self.high)
        self.assertEqual(d.action, "wait")
        self.assertEqual(d.dose_ml, 0)

    def test_disease_sprays_and_scales_with_severity(self):
        lo = decide(self.rules, "Tomato_leaf_early_blight", True, self.low)
        hi = decide(self.rules, "Tomato_leaf_early_blight", True, self.high)
        self.assertEqual(lo.action, "spray")
        self.assertGreater(hi.dose_ml, lo.dose_ml)
        self.assertGreater(lo.dose_ml, 0)
        self.assertAlmostEqual(hi.spray_seconds, hi.dose_ml / self.rules["units"]["pump_ml_per_second"], places=1)
        self.assertEqual(lo.dose_ml, 18.8)  # 30 x (0.5 + 0.05/0.40)
        self.assertEqual(hi.dose_ml, 45.0)  # 30 x 1.5 (0.5 lesion area is past full_at)
        self.assertEqual(lo.percent, 31)    # 18.8 of a 60 mL maximum
        self.assertEqual(hi.percent, 75)    # 45 of 60
        self.assertTrue(hi.summary().startswith("SPRAY 75%"))

    def test_dose_is_continuous_in_lesion_area(self):
        doses = [decide(self.rules, "Tomato_leaf_early_blight", True, Severity(f, 0.9, "medium")).dose_ml
                 for f in (0.10, 0.15, 0.20, 0.25)]
        self.assertEqual(doses, sorted(doses))
        self.assertEqual(len(set(doses)), 4)

    def test_unknown_severity_uses_base_dose(self):
        d = decide(self.rules, "Tomato_leaf_early_blight", True, Severity(0.0, 0.02, "unknown"))
        self.assertEqual(d.dose_ml, 30.0)

    def test_largest_rule_is_100_percent(self):
        hi = Severity(0.5, 0.9, "high")
        d = decide(self.rules, "Tomato_leaf_late_blight", True, hi)
        self.assertEqual(d.percent, 100)

    def test_no_spray_is_zero_percent(self):
        for label in ("Tomato_leaf_healthy", "Tomato_leaf_yellow_leaf_curl_virus"):
            d = decide(self.rules, label, True, self.high)
            self.assertEqual(d.percent, 0)
            self.assertTrue(d.summary().startswith("SPRAY 0%"))

    def test_virus_means_remove_not_spray(self):
        d = decide(self.rules, "Tomato_leaf_yellow_leaf_curl_virus", True, self.high)
        self.assertEqual(d.action, "remove")
        self.assertEqual(d.dose_ml, 0)

    def test_physiological_disorder_no_spray(self):
        d = decide(self.rules, "Tomato_fruit_blossom_end_rot", True, self.high)
        self.assertEqual(d.action, "none")

    def test_unknown_label_falls_back_to_default(self):
        d = decide(self.rules, "Tomato_leaf_something_new", True, self.low)
        self.assertEqual(d.action, "none")

    def test_every_rule_is_well_formed(self):
        for label, rule in self.rules["rules"].items():
            self.assertIn(rule["action"], ("none", "spray", "remove"), label)
            if rule["action"] == "spray":
                self.assertGreater(rule["dose_ml"], 0, label)
                self.assertTrue(rule.get("product"), label)
            else:
                self.assertTrue(rule.get("reason"), label)


if __name__ == "__main__":
    unittest.main()
