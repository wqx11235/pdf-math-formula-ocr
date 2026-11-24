"""选择性验证门：校准、界、以及「拿不准就一块都不跳」。"""

from __future__ import annotations

import unittest

from pmocr import gate
from tests.helpers import make_tmp


class BoundTests(unittest.TestCase):
    def test_zero_misses_needs_many_samples_for_tight_bound(self) -> None:
        self.assertGreater(gate.clopper_pearson_upper(0, 20, 0.05), 0.10)
        self.assertLess(gate.clopper_pearson_upper(0, 120, 0.05), 0.03)

    def test_bound_increases_with_misses(self) -> None:
        self.assertLess(gate.clopper_pearson_upper(1, 30, 0.05),
                        gate.clopper_pearson_upper(5, 30, 0.05))

    def test_binom_cdf_edges(self) -> None:
        self.assertEqual(gate.binom_cdf(-1, 10, 0.5), 0.0)
        self.assertEqual(gate.binom_cdf(10, 10, 0.5), 1.0)


class CalibrateTests(unittest.TestCase):
    def test_clean_calibration_allows_some_skips(self) -> None:
        # 40 个长公式（全对）+ 40 个短公式（全错）→ 长端应能安全跳一段
        texs = ["x" * 200] * 40 + ["x"] * 40
        truths = [0] * 40 + [1] * 40
        g = gate.calibrate(texs, truths, epsilon=0.10, delta=0.05)
        self.assertGreater(g.skip_fraction, 0.0)
        self.assertLessEqual(g.bound, 0.10)

    def test_dirty_calibration_skips_nothing(self) -> None:
        texs = ["x" * 200, "x" * 100, "x" * 50]
        truths = [1, 0, 0]
        g = gate.calibrate(texs, truths, epsilon=0.01, delta=0.05)
        self.assertEqual(g.skip_fraction, 0.0)
        self.assertEqual(g.cutoff, float("inf"))

    def test_mismatched_lengths_rejected(self) -> None:
        with self.assertRaises(Exception):
            gate.calibrate(["x"], [], epsilon=0.05)

    def test_skips_uses_cutoff(self) -> None:
        g = gate.Gate(cutoff=5.0, mean={"len": 100.0, "cmd": 10.0}, std={"len": 50.0, "cmd": 5.0},
                      skip_fraction=0.2, epsilon=0.05, delta=0.05, n_calibration=100, bound=0.03)
        self.assertTrue(g.skips("x" * 400))
        self.assertFalse(g.skips("x" * 100))

    def test_roundtrip_json(self) -> None:
        g = gate.Gate(cutoff=5.0, mean={"len": 100.0, "cmd": 10.0}, std={"len": 50.0, "cmd": 5.0},
                      skip_fraction=0.15, epsilon=0.05, delta=0.05, n_calibration=80, bound=0.04)
        path = gate.save(g, make_tmp() / "gate.json")
        self.assertEqual(gate.load(path), g)

    def test_coverage_risk_counts(self) -> None:
        g = gate.Gate(cutoff=20.0, mean={"len": 0.0, "cmd": 0.0}, std={"len": 1.0, "cmd": 1.0},
                      skip_fraction=0.5, epsilon=0.05, delta=0.05, n_calibration=10, bound=0.03)
        skipped, missed = gate.coverage_risk(["x" * 50, "x" * 40, "x"], [0, 1, 1], g)
        self.assertEqual((skipped, missed), (2, 1))


class ShadowTests(unittest.TestCase):
    def test_shadow_reports_zero_when_top_is_positive(self) -> None:
        rows = [{"book": "B", "verdict": "CHECK", "tex": "x" * 500},
                {"book": "B", "verdict": "OK", "tex": "x"},
                {"book": "B", "verdict": "OK", "tex": "xx"}]
        report = gate.shadow_report(rows, epsilon=0.10)
        self.assertEqual(report["groups"][0]["skip"], 0)

    def test_shadow_skips_with_clean_prefix(self) -> None:
        rows = [{"book": "B", "verdict": "OK", "tex": "x" * 200} for _ in range(70)]
        rows += [{"book": "B", "verdict": "CHECK", "tex": "x"} for _ in range(30)]
        report = gate.shadow_report(rows, epsilon=0.10)
        self.assertGreater(report["groups"][0]["skip"], 0)
        self.assertEqual(report["groups"][0]["missed"], 0)


if __name__ == "__main__":
    unittest.main()

