"""入口脚本：正常收尾、配置错误退出码、产物落盘。"""

from __future__ import annotations

import unittest
from pathlib import Path

from pmocr.cli import main
from tests.helpers import formula_block, make_page_json, make_page_png, make_tmp


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.pages = self.tmp / "pages_json"
        self.images = self.tmp / "images"
        self.out = self.tmp / "out"

    def test_writes_reports_and_returns_zero(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        make_page_png(self.images / "p-01.png")
        code = main(["--pages", str(self.pages), "--images", str(self.images), "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "formula_qc.csv").is_file())
        self.assertTrue((self.out / "待复核.md").is_file())

    def test_missing_page_image_is_skipped(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        code = main(["--pages", str(self.pages), "--images", str(self.images), "--out", str(self.out)])
        self.assertEqual(code, 0)
        text = (self.out / "待复核.md").read_text(encoding="utf-8")
        self.assertIn("共 0 个公式块", text)

    def test_bad_threshold_returns_config_error(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        code = main(["--pages", str(self.pages), "--images", str(self.images), "--out", str(self.out), "--threshold", "1.5"])
        self.assertEqual(code, 2)

    def test_missing_pages_dir_returns_error(self) -> None:
        code = main(["--pages", str(self.tmp / "nope"), "--images", str(self.images), "--out", str(self.out)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
