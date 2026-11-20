"""一键流程：编排顺序、断点产物、失败分流（解析与复核用假实现，渲页与合并用真的）。"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from pmocr import pipeline, qc
from pmocr.config import Config
from pmocr.errors import DataError, PmocrError
from tests.helpers import make_tmp


def _summary(blocks: int = 3, review: int = 1) -> qc.RunSummary:
    verdicts = [qc.VERDICT_OK] * (blocks - review) + [qc.VERDICT_CHECK] * review
    results = tuple(
        qc.BlockResult("p-01", index + 1, (0.0, 0.0, 10.0, 10.0), "x^2", verdict, 0.9, "")
        for index, verdict in enumerate(verdicts)
    )
    return qc.RunSummary(results=results, skipped_pages=())


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.root = self.tmp / "minicpm"
        (self.root / "runs").mkdir(parents=True)
        self.cfg = Config.load(None, overrides={"minicpm_root": str(self.root)}, environ={})
        self.pdf = self._make_pdf(self.tmp / "book.pdf", pages=2)

    def _make_pdf(self, path: Path, pages: int) -> Path:
        import pymupdf

        doc = pymupdf.open()
        try:
            for _ in range(pages):
                page = doc.new_page(width=300, height=400)
                page.insert_text((40, 60), "x^2 + y^2")
            doc.save(str(path))
        finally:
            doc.close()
        return path

    def _fake_parse(self, cmd, cwd, log_path):
        """模仿 SDK：建一个全新的 runs/<tag>/pages_json，并在 md 目录写逐页 md。"""
        md_dir = Path(cmd[cmd.index("-Out") + 1])
        md_dir.mkdir(parents=True, exist_ok=True)
        for number in (1, 2):
            (md_dir / ("p-%02d.md" % number)).write_text("第 %d 页正文" % number, encoding="utf-8")
        run_dir = self.root / "runs" / ("fake_%d" % int(time.time() * 1000))
        (run_dir / "pages_json").mkdir(parents=True)
        (run_dir / "pages_json" / "p-01.json").write_text("{}", encoding="utf-8")
        return 0

    def test_runs_all_four_steps(self) -> None:
        result = pipeline.run_book(
            pdf=self.pdf, title="测试书", workdir=self.tmp / "work", cfg=self.cfg,
            repo_root=Path("D:/fake/repo"), parse_runner=self._fake_parse,
            qc_service=lambda *a, **k: _summary(3, 1), log=lambda _m: None,
        )
        self.assertEqual(result.pages, 2)
        self.assertEqual((result.blocks, result.review), (3, 1))
        self.assertTrue(result.book.is_file())
        self.assertIn("第 2 页正文", result.book.read_text(encoding="utf-8"))
        self.assertTrue((result.qc_dir / "formula_qc.csv").is_file())

    def test_pages_are_removed_unless_kept(self) -> None:
        pipeline.run_book(
            pdf=self.pdf, title="书", workdir=self.tmp / "w1", cfg=self.cfg,
            repo_root=Path("D:/fake/repo"), parse_runner=self._fake_parse,
            qc_service=lambda *a, **k: _summary(), log=lambda _m: None,
        )
        self.assertFalse((self.tmp / "w1" / pipeline.PAGES_DIR).exists())

        pipeline.run_book(
            pdf=self.pdf, title="书", workdir=self.tmp / "w2", cfg=self.cfg,
            repo_root=Path("D:/fake/repo"), parse_runner=self._fake_parse,
            qc_service=lambda *a, **k: _summary(), keep_pages=True, log=lambda _m: None,
        )
        self.assertTrue((self.tmp / "w2" / pipeline.PAGES_DIR).exists())

    def test_parse_failure_raises(self) -> None:
        with self.assertRaises(PmocrError):
            pipeline.run_book(
                pdf=self.pdf, title="书", workdir=self.tmp / "w3", cfg=self.cfg,
                repo_root=Path("D:/fake/repo"), parse_runner=lambda *a: 1,
                qc_service=lambda *a, **k: _summary(), log=lambda _m: None,
            )

    def test_missing_minicpm_root_is_reported(self) -> None:
        cfg = Config.load(None, environ={})
        with self.assertRaises(DataError):
            pipeline.run_book(
                pdf=self.pdf, title="书", workdir=self.tmp / "w4", cfg=cfg,
                repo_root=Path("D:/fake/repo"), parse_runner=self._fake_parse,
                qc_service=lambda *a, **k: _summary(), log=lambda _m: None,
            )

    def test_no_pages_json_after_parse_is_reported(self) -> None:
        def parse_without_output(cmd, cwd, log_path):
            md_dir = Path(cmd[cmd.index("-Out") + 1])
            md_dir.mkdir(parents=True, exist_ok=True)
            (md_dir / "p-01.md").write_text("x", encoding="utf-8")
            return 0

        with self.assertRaises(PmocrError):
            pipeline.run_book(
                pdf=self.pdf, title="书", workdir=self.tmp / "w5", cfg=self.cfg,
                repo_root=Path("D:/fake/repo"), parse_runner=parse_without_output,
                qc_service=lambda *a, **k: _summary(), log=lambda _m: None,
            )


class FindPagesJsonTests(unittest.TestCase):
    def test_returns_latest_fresh_run(self) -> None:
        tmp = make_tmp()
        runs = tmp / "runs"
        old = runs / "old" / "pages_json"
        new = runs / "new" / "pages_json"
        old.mkdir(parents=True)
        new.mkdir(parents=True)
        now = time.time()
        import os

        os.utime(old, (now - 600, now - 600))
        os.utime(new, (now, now))
        found = pipeline.find_latest_pages_json(runs, since=now - 60)
        self.assertEqual(found, new)

    def test_stale_runs_are_ignored(self) -> None:
        tmp = make_tmp()
        runs = tmp / "runs"
        (runs / "old" / "pages_json").mkdir(parents=True)
        import os

        now = time.time()
        os.utime(runs / "old", (now - 600, now - 600))
        self.assertIsNone(pipeline.find_latest_pages_json(runs, since=now - 60))

    def test_missing_runs_dir_is_reported(self) -> None:
        tmp = make_tmp()
        with self.assertRaises(DataError):
            pipeline.find_latest_pages_json(tmp / "nope", since=0)


if __name__ == "__main__":
    unittest.main()
