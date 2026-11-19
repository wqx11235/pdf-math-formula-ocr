"""报告写出与读回；低分与未打分必须分节。"""

from __future__ import annotations

import unittest
from pathlib import Path

from pmocr.qc import (
    BlockResult,
    VERDICT_CHECK,
    VERDICT_OK,
    VERDICT_RENDER_FAIL,
    VERDICT_SCORE_ERR,
)
from pmocr.report import load_results, summarize, write_csv, write_markdown
from tests.helpers import make_tmp


def _result(page: str, index: int, verdict: str, score: float | None = None, note: str = "") -> BlockResult:
    return BlockResult(page, index, (1.0, 2.0, 3.0, 4.0), "x^2", verdict, score, note)


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.results = [
            _result("p-01", 1, VERDICT_OK, 0.91),
            _result("p-01", 2, VERDICT_CHECK, 0.27),
            _result("p-02", 1, VERDICT_RENDER_FAIL),
            _result("p-02", 2, VERDICT_SCORE_ERR, note="HTTP 500"),
        ]

    def test_summarize_counts(self) -> None:
        counts = summarize(self.results)
        self.assertEqual((counts.total, counts.ok, counts.check), (4, 1, 1))
        self.assertEqual(counts.unscored, 2)
        self.assertEqual(counts.review, 3)
        self.assertAlmostEqual(counts.review_share, 0.75)

    def test_csv_roundtrip(self) -> None:
        path = write_csv(self.results, self.tmp / "qc.csv")
        loaded = load_results(path)
        self.assertEqual(len(loaded), 4)
        self.assertEqual(loaded[1].verdict, VERDICT_CHECK)
        self.assertAlmostEqual(loaded[1].score, 0.27)
        self.assertIsNone(loaded[2].score)
        self.assertEqual(loaded[0].bbox, (1.0, 2.0, 3.0, 4.0))
        self.assertEqual(loaded[3].note, "HTTP 500")

    def test_markdown_separates_check_from_unscored(self) -> None:
        path = write_markdown(self.results, self.tmp / "待复核.md", 0.6)
        text = path.read_text(encoding="utf-8")
        self.assertIn("低分 · 可能错", text)
        self.assertIn("未打分 · 需核对", text)
        self.assertIn("score=0.2700", text)
        # 低分节在前，未打分节在后
        self.assertLess(text.index("低分 · 可能错"), text.index("未打分 · 需核对"))
        # OK 块不进报告正文
        self.assertNotIn("p-01 block 1", text)

    def test_markdown_counts_in_header(self) -> None:
        path = write_markdown(self.results, self.tmp / "m.md", 0.6)
        self.assertIn("自动通过 1", path.read_text(encoding="utf-8"))

    def test_empty_report_is_valid(self) -> None:
        path = write_markdown([], self.tmp / "empty.md", 0.6)
        self.assertIn("共 0 个公式块", path.read_text(encoding="utf-8"))

    def test_load_rejects_missing_file(self) -> None:
        from pmocr.errors import DataError

        with self.assertRaises(DataError):
            load_results(self.tmp / "nope.csv")


if __name__ == "__main__":
    unittest.main()
