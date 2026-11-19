"""复核服务：判定分流、单块失败不中断、缺图跳过。"""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

from pmocr import qc
from pmocr.config import Config
from pmocr.errors import JevError
from pmocr.latex import RenderResult
from pmocr.ocr import FormulaBlock
from pmocr.paths import discover_pages, prepare_outputs

from tests.helpers import fake_renderer, formula_block, make_page_json, make_page_png, make_tmp


class FakeClient:
    def __init__(self, score: float = 0.9, error: Exception | None = None) -> None:
        self.score_value = score
        self.error = error
        self.calls: list[tuple] = []

    def score(self, region, tex, candidate):
        self.calls.append((region, tex, candidate))
        if self.error:
            raise self.error
        return self.score_value


class EvaluateBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.layout = prepare_outputs(self.tmp / "out")
        self.cfg = Config.load(None, environ={})
        self.image = Image.new("RGB", (400, 600), "white")
        self.block = FormulaBlock("p-01", 1, (10, 20, 100, 60), "x^2")

    def test_scores_above_threshold_are_ok(self) -> None:
        result = qc.evaluate_block(
            block=self.block, page_image=self.image, page_size=qc.Size(400, 600),
            source_size=qc.Size(400, 600), layout=self.layout, cfg=self.cfg,
            client=FakeClient(0.9), renderer=fake_renderer(self.tmp / "r.png"),
        )
        self.assertEqual(result.verdict, qc.VERDICT_OK)
        self.assertAlmostEqual(result.score, 0.9)

    def test_scores_below_threshold_are_check(self) -> None:
        result = qc.evaluate_block(
            block=self.block, page_image=self.image, page_size=qc.Size(400, 600),
            source_size=qc.Size(400, 600), layout=self.layout, cfg=self.cfg,
            client=FakeClient(0.27), renderer=fake_renderer(self.tmp / "r.png"),
        )
        self.assertEqual(result.verdict, qc.VERDICT_CHECK)

    def test_verdict_uses_stored_score(self) -> None:
        # 0.59996 落盘为 0.6，判定必须与落盘值一致，否则 CSV 自相矛盾
        result = qc.evaluate_block(
            block=self.block, page_image=self.image, page_size=qc.Size(400, 600),
            source_size=qc.Size(400, 600), layout=self.layout, cfg=self.cfg,
            client=FakeClient(0.59996), renderer=fake_renderer(self.tmp / "r.png"),
        )
        self.assertEqual(result.score, 0.6)
        self.assertEqual(result.verdict, qc.VERDICT_OK)

    def test_render_failure_is_render_fail(self) -> None:
        result = qc.evaluate_block(
            block=self.block, page_image=self.image, page_size=qc.Size(400, 600),
            source_size=qc.Size(400, 600), layout=self.layout, cfg=self.cfg,
            client=FakeClient(0.9), renderer=fake_renderer(None, error="! Missing $ inserted"),
        )
        self.assertEqual(result.verdict, qc.VERDICT_RENDER_FAIL)
        self.assertIn("Missing", result.note)

    def test_jev_error_is_score_err(self) -> None:
        result = qc.evaluate_block(
            block=self.block, page_image=self.image, page_size=qc.Size(400, 600),
            source_size=qc.Size(400, 600), layout=self.layout, cfg=self.cfg,
            client=FakeClient(error=JevError("HTTP 500")),
            renderer=fake_renderer(self.tmp / "r.png"),
        )
        self.assertEqual(result.verdict, qc.VERDICT_SCORE_ERR)
        self.assertIn("500", result.note)

    def test_crop_is_written(self) -> None:
        qc.evaluate_block(
            block=self.block, page_image=self.image, page_size=qc.Size(400, 600),
            source_size=qc.Size(400, 600), layout=self.layout, cfg=self.cfg,
            client=FakeClient(0.9), renderer=fake_renderer(self.tmp / "r.png"),
        )
        self.assertTrue(self.layout.crop_path("p-01", 1).is_file())

    def test_empty_crop_does_not_raise(self) -> None:
        # bbox 完全落在页面外 → 裁剪后宽 0，必须转成判定而不是抛异常
        result = qc.evaluate_block(
            block=FormulaBlock("p-01", 1, (500, 500, 600, 600), "x"),
            page_image=self.image, page_size=qc.Size(400, 600),
            source_size=qc.Size(400, 600), layout=self.layout, cfg=self.cfg,
            client=FakeClient(0.9), renderer=fake_renderer(self.tmp / "r.png"),
        )
        self.assertEqual(result.verdict, qc.VERDICT_RENDER_FAIL)


class RunTests(unittest.TestCase):
    def test_runs_all_pages_and_skips_missing_images(self) -> None:
        tmp = make_tmp()
        pages = tmp / "pages_json"
        images = tmp / "images"
        make_page_json(pages / "p-01.json", [formula_block(), formula_block(content="y")])
        make_page_png(images / "p-01.png")
        make_page_json(pages / "p-02.json", [formula_block()])  # 无图

        layout = prepare_outputs(tmp / "out")
        cfg = Config.load(None, environ={})
        summary = qc.run(
            discover_pages(pages, images), layout, cfg,
            client=FakeClient(0.8), renderer=fake_renderer(tmp / "r.png"), log=lambda _m: None,
        )
        self.assertEqual(len(summary.results), 2)
        self.assertEqual(summary.skipped_pages, ("p-02",))
        self.assertEqual(summary.count(qc.VERDICT_OK), 2)

    def test_malformed_page_is_skipped_not_fatal(self) -> None:
        tmp = make_tmp()
        pages = tmp / "pages_json"
        images = tmp / "images"
        (pages).mkdir(parents=True)
        (pages / "p-01.json").write_text("{broken", encoding="utf-8")
        make_page_png(images / "p-01.png")
        layout = prepare_outputs(tmp / "out")
        summary = qc.run(
            discover_pages(pages, images), layout, Config.load(None, environ={}),
            client=FakeClient(0.8), renderer=fake_renderer(tmp / "r.png"), log=lambda _m: None,
        )
        self.assertEqual(summary.results, ())
        self.assertEqual(summary.skipped_pages, ("p-01",))


if __name__ == "__main__":
    unittest.main()
