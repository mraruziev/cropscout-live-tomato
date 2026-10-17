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
    img = np.zeros((224, 224, 3), np.uint8)
    img[:] = GREY
    n = int(224 * cover)
    img[:n, :] = GREEN
    k = int(224 * lesion_fraction)
    img[:n, :k] = BROWN
    return img


class SeverityTests(unittest.TestCase):
    rules = load_rules()

    def test_pure_green_is_low(self):
        s = estimate_severity(leaf(0.0), self.rules)
        self.assertEqual(s.band, "low")
        self.assertLess(s.lesion_fraction, 0.01)

    def test_brown_patches_raise_severity(self):
        s = estimate_severity(leaf(0.4), self.rules)
        self.assertEqual(s.band, "high")
        self.assertAlmostEqual(s.lesion_fraction, 0.4, delta=0.03)

    def test_medium_band(self):
        s = estimate_severity(leaf(0.2), self.rules)
        self.assertEqual(s.band, "medium")

    def test_no_leaf_is_unknown(self):
        s = estimate_severity(leaf(0.0, cover=0.05), self.rules)
        self.assertEqual(s.band, "unknown")


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
        self.assertEqual(hi.percent, 75)   # 42 mL of a 56 mL maximum
        self.assertEqual(lo.percent, 32)   # 18 mL of 56
        self.assertTrue(hi.summary().startswith("SPRAY 75%"))

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
