"""选择性验证门：校准、界、以及「拿不准就一块都不跳」。"""

from __future__ import annotations

import unittest

from pmocr import gate


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
        # 40 个高分块全没问题、40 个低分块有问题 → 应能跳一段
        scores = [10.0] * 40 + [0.0] * 40
        truths = [0] * 40 + [1] * 40
        g = gate.calibrate(scores, truths, epsilon=0.10, delta=0.05)
        self.assertGreater(g.skip_fraction, 0.0)
        self.assertLessEqual(g.bound, 0.10)
        self.assertGreaterEqual(g.cutoff, 10.0)

    def test_dirty_calibration_skips_nothing(self) -> None:
        # 最高分那一块就是问题块 → 一块都不能跳
        scores = [10.0, 9.0, 8.0]
        truths = [1, 0, 0]
        g = gate.calibrate(scores, truths, epsilon=0.01, delta=0.05)
        self.assertEqual(g.skip_fraction, 0.0)
        self.assertEqual(g.cutoff, float("inf"))

    def test_mismatched_lengths_rejected(self) -> None:
        with self.assertRaises(Exception):
            gate.calibrate([1.0], [], epsilon=0.05)

    def test_skips_uses_cutoff(self) -> None:
        g = gate.Gate(cutoff=50.0, skip_fraction=0.2, epsilon=0.05, delta=0.05,
                      n_calibration=100, bound=0.03)
        long_tex = "x" * 60
        self.assertTrue(g.skips(long_tex))
        self.assertFalse(g.skips("x"))

    def test_roundtrip_json(self) -> None:
        from tests.helpers import make_tmp

        g = gate.Gate(cutoff=42.0, skip_fraction=0.15, epsilon=0.05, delta=0.05,
                      n_calibration=80, bound=0.04)
        tmp = make_tmp()
        path = gate.save(g, tmp / "gate.json")
        self.assertEqual(gate.load(path), g)

    def test_coverage_risk_counts(self) -> None:
        skipped, missed = gate.coverage_risk([10.0, 10.0, 0.0], [0, 1, 1], cutoff=5.0)
        self.assertEqual((skipped, missed), (2, 1))


if __name__ == "__main__":
    unittest.main()


