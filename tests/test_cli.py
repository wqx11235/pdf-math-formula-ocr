"""入口：三个子命令的装配、退出码、产物落盘（不碰真 TeX / 真 Jev）。"""

from __future__ import annotations

import unittest
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


class QcCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.pages = self.tmp / "pages_json"
        self.images = self.tmp / "images"
        self.out = self.tmp / "out"

    def _run(self, *extra: str) -> int:
        return main(["qc", "--pages", str(self.pages), "--images", str(self.images), "--out", str(self.out), *extra])

    def test_writes_reports_and_returns_zero(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        make_page_png(self.images / "p-01.png")
        with mock.patch.object(qc, "run", return_value=_summary(qc.VERDICT_CHECK)):
            code = self._run()
        self.assertEqual(code, 0)
        self.assertIn("CHECK", (self.out / "formula_qc.csv").read_text(encoding="utf-8-sig"))
        self.assertTrue((self.out / "待复核.md").is_file())

    def test_skipped_pages_are_reported(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        self.assertEqual(self._run(), 0)
        self.assertIn("共 0 个公式块", (self.out / "待复核.md").read_text(encoding="utf-8"))

    def test_bad_threshold_returns_config_error(self) -> None:
        make_page_json(self.pages / "p-01.json", [formula_block()])
        self.assertEqual(self._run("--threshold", "1.5"), 2)

    def test_missing_pages_dir_returns_error(self) -> None:
        code = main(["qc", "--pages", str(self.tmp / "nope"), "--images", str(self.images), "--out", str(self.out)])
        self.assertEqual(code, 2)

    def test_overrides_reach_config(self) -> None:
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


class RenderCommandTests(unittest.TestCase):
    def test_renders_real_pdf_pages(self) -> None:
        import pymupdf

        tmp = make_tmp()
        pdf = tmp / "book.pdf"
        doc = pymupdf.open()
        try:
            for _ in range(2):
                page = doc.new_page(width=300, height=400)
                page.insert_text((40, 60), "x^2 + y^2")
            doc.save(str(pdf))
        finally:
            doc.close()

        out = tmp / "pages"
        self.assertEqual(main(["render", "--pdf", str(pdf), "--out", str(out), "--edge", "600"]), 0)
        self.assertEqual(sorted(p.name for p in out.glob("*.png")), ["p-01.png", "p-02.png"])
        self.assertGreater((out / "p-01.png").stat().st_size, 1000)

    def test_missing_pdf_returns_error(self) -> None:
        tmp = make_tmp()
        self.assertEqual(main(["render", "--pdf", str(tmp / "nope.pdf"), "--out", str(tmp / "p")]), 2)


class MergeCommandTests(unittest.TestCase):
    def test_merges_pages_into_book(self) -> None:
        tmp = make_tmp()
        pages = tmp / "pages"
        pages.mkdir()
        (pages / "p-01.md").write_text("第一页", encoding="utf-8")
        (pages / "p-02.md").write_text("第二页", encoding="utf-8")
        out = tmp / "book.md"
        self.assertEqual(main(["merge", "--pages", str(pages), "--out", str(out), "--title", "试跑"]), 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# 试跑", text)
        self.assertIn("第二页", text)

    def test_missing_pages_dir_returns_error(self) -> None:
        tmp = make_tmp()
        self.assertEqual(main(["merge", "--pages", str(tmp / "nope"), "--out", str(tmp / "b.md"), "--title", "x"]), 2)


class ParserTests(unittest.TestCase):
    def test_requires_a_subcommand(self) -> None:
        with self.assertRaises(SystemExit):
            main([])

    def test_unknown_subcommand_exits(self) -> None:
        with self.assertRaises(SystemExit):
            main(["nope"])


if __name__ == "__main__":
    unittest.main()
