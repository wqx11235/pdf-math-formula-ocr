"""对照组实验：三臂规模、标签指标、阈值扫描。"""

from __future__ import annotations

import unittest
from pathlib import Path

from pmocr.errors import DataError
from pmocr.experiment import (
    TRUTH_OK,
    TRUTH_WRONG,
    arms,
    label_metrics,
    load_labels,
    sweep,
)
from pmocr.qc import (
    BlockResult,
    VERDICT_CHECK,
    VERDICT_OK,
    VERDICT_RENDER_FAIL,
    VERDICT_SCORE_ERR,
)
from tests.helpers import make_tmp


def _r(page: str, index: int, verdict: str, score: float | None = None) -> BlockResult:
    return BlockResult(page, index, (0, 0, 1, 1), "x", verdict, score)


class ArmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.results = [
            _r("p", 1, VERDICT_OK, 0.9),
            _r("p", 2, VERDICT_OK, 0.8),
            _r("p", 3, VERDICT_CHECK, 0.2),
            _r("p", 4, VERDICT_RENDER_FAIL),
            _r("p", 5, VERDICT_SCORE_ERR),
        ]

    def test_arm_a_reviews_nothing(self) -> None:
        arm = arms(self.results)[0]
        self.assertEqual(arm.review, 0)
        self.assertEqual(arm.auto_pass, 5)
        self.assertFalse(arm.catches_invalid_latex)

    def test_arm_b_only_catches_render_failures(self) -> None:
        arm = arms(self.results)[1]
        self.assertEqual(arm.review, 1)
        self.assertEqual(arm.auto_pass, 4)
        self.assertTrue(arm.catches_invalid_latex)
        self.assertFalse(arm.can_flag_low_confidence)

    def test_arm_c_reviews_everything_not_ok(self) -> None:
        arm = arms(self.results)[2]
        self.assertEqual(arm.review, 3)
        self.assertEqual(arm.auto_pass, 2)
        self.assertAlmostEqual(arm.review_share, 0.6)
        self.assertTrue(arm.can_flag_low_confidence)


class LabelMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.results = [
            _r("p", 1, VERDICT_CHECK, 0.2),      # 真错 → 拦下
            _r("p", 2, VERDICT_OK, 0.9),         # 真错 → 漏检
            _r("p", 3, VERDICT_RENDER_FAIL),     # 真对 → 误标
            _r("p", 4, VERDICT_OK, 0.95),        # 真对 → 放行
        ]
        self.labels = {
            ("p", 1): TRUTH_WRONG,
            ("p", 2): TRUTH_WRONG,
            ("p", 3): TRUTH_OK,
            ("p", 4): TRUTH_OK,
        }

    def test_counts_and_rates(self) -> None:
        m = label_metrics(self.results, self.labels)
        self.assertEqual((m.labeled, m.labeled_ok, m.labeled_wrong), (4, 2, 2))
        self.assertEqual((m.caught, m.missed), (1, 1))
        self.assertEqual((m.false_check, m.unscored_ok), (0, 1))
        self.assertAlmostEqual(m.recall, 0.5)
        self.assertAlmostEqual(m.precision, 1.0)

    def test_unlabeled_blocks_are_ignored(self) -> None:
        m = label_metrics(self.results, {("p", 1): TRUTH_WRONG})
        self.assertEqual(m.labeled, 1)
        self.assertEqual(m.caught, 1)
        self.assertEqual(m.false_check, 0)
        self.assertAlmostEqual(m.precision, 1.0)

    def test_no_labels_means_no_rates(self) -> None:
        m = label_metrics(self.results, {})
        self.assertEqual(m.labeled, 0)
        self.assertIsNone(m.recall)
        self.assertIsNone(m.precision)

    def test_threshold_overrides_stored_verdict(self) -> None:
        results = [_r("p", 1, VERDICT_CHECK, 0.55)]
        m = label_metrics(results, {("p", 1): TRUTH_WRONG}, threshold=0.5)
        self.assertEqual(m.missed, 1)  # 0.55 ≥ 0.5 → 放行

    def test_unscored_always_needs_review(self) -> None:
        results = [_r("p", 1, VERDICT_SCORE_ERR)]
        m = label_metrics(results, {("p", 1): TRUTH_OK}, threshold=0.1)
        self.assertEqual(m.unscored_ok, 1)
        self.assertEqual(m.false_check, 0)

    def test_duplicate_label_match_is_rejected(self) -> None:
        results = [
            _r("p", 1, VERDICT_OK, 0.9),
            _r("p", 1, VERDICT_OK, 0.95),
        ]
        with self.assertRaises(DataError) as ctx:
            label_metrics(results, {("p", 1): TRUTH_OK})
        self.assertIn("命中多行", str(ctx.exception))


class SweepTests(unittest.TestCase):
    def test_review_share_is_monotonic(self) -> None:
        results = [_r("p", i, VERDICT_OK, score) for i, score in enumerate([0.1, 0.4, 0.7, 0.95])]
        rows = sweep(results, {}, [0.3, 0.5, 0.8, 0.99])
        shares = [row.review_share for row in rows]
        self.assertEqual(shares, sorted(shares))
        self.assertTrue(all(0.0 <= share <= 1.0 for share in shares))

    def test_unscored_constant_across_thresholds(self) -> None:
        results = [_r("p", 1, VERDICT_SCORE_ERR), _r("p", 2, VERDICT_RENDER_FAIL)]
        rows = sweep(results, {}, [0.3, 0.9])
        self.assertEqual([row.review for row in rows], [2, 2])


class LabelFileTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        tmp = make_tmp()
        path = tmp / "labels.csv"
        path.write_text("page,block,truth\np-01,1,ok\np-01,2,wrong\n", encoding="utf-8")
        labels = load_labels(path)
        self.assertEqual(labels[("p-01", 1)], TRUTH_OK)
        self.assertEqual(labels[("p-01", 2)], TRUTH_WRONG)

    def test_bad_truth_is_rejected(self) -> None:
        tmp = make_tmp()
        path = tmp / "labels.csv"
        path.write_text("page,block,truth\np-01,1,maybe\n", encoding="utf-8")
        with self.assertRaises(DataError):
            load_labels(path)

    def test_missing_columns_rejected(self) -> None:
        tmp = make_tmp()
        path = tmp / "labels.csv"
        path.write_text("page,block\np-01,1\n", encoding="utf-8")
        with self.assertRaises(DataError):
            load_labels(path)


if __name__ == "__main__":
    unittest.main()
