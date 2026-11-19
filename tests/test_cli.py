"""入口脚本：只验参数解析、装配顺序、退出码与产物落盘（不碰真 TeX / 真 Jev）。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from pmocr import qc
from pmocr.cli import main
from tests.helpers import formula_block, make_page_json, make_page_png, make_tmp


def _summary(*verdicts: str) -> qc.RunSummary:
    results = tuple(
        qc.BlockResult("p-01", index + 1, (0.0, 0.0, 10.0, 10.0), "x^2", verdict, 0.9, "")
        for index, verdict in enumerate(verdicts)
    )
    return qc.RunSummary(results=results, skipped_pages=())


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.pages = self.tmp / "pages_json"
        self.images = self.tmp / "images"
        self.out = self.tmp / "out"

    def _run(self, *extra: str) -> int:
        return main(["--pages", str(self.pages), "--images", str(self.images), "--out", str(self.out), *extra])

    def test_writes_reports_and_returns_zero(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        make_page_png(self.images / "p-01.png")
        with mock.patch.object(qc, "run", return_value=_summary(qc.VERDICT_CHECK)):
            code = self._run()
        self.assertEqual(code, 0)
        csv_text = (self.out / "formula_qc.csv").read_text(encoding="utf-8-sig")
        self.assertIn("CHECK", csv_text)
        self.assertTrue((self.out / "待复核.md").is_file())

    def test_skipped_pages_are_reported(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])  # 无页面图
        code = self._run()
        self.assertEqual(code, 0)
        text = (self.out / "待复核.md").read_text(encoding="utf-8")
        self.assertIn("共 0 个公式块", text)

    def test_bad_threshold_returns_config_error(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        self.assertEqual(self._run("--threshold", "1.5"), 2)

    def test_missing_pages_dir_returns_error(self) -> None:
        code = main(["--pages", str(self.tmp / "nope"), "--images", str(self.images), "--out", str(self.out)])
        self.assertEqual(code, 2)

    def test_cli_overrides_reach_config(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        make_page_png(self.images / "p-01.png")
        seen: dict = {}

        def spy(pages, layout, cfg, **_kwargs):
            seen["threshold"] = cfg.threshold
            seen["jev_url"] = cfg.jev_url
            return _summary()

        with mock.patch.object(qc, "run", side_effect=spy):
            code = self._run("--threshold", "0.42", "--jev-url", "http://127.0.0.1:19999")
        self.assertEqual(code, 0)
        self.assertAlmostEqual(seen["threshold"], 0.42)
        self.assertEqual(seen["jev_url"], "http://127.0.0.1:19999")


if __name__ == "__main__":
    unittest.main()
