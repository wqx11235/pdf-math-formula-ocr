"""LaTeX 清洗、装配与渲染的错误分流。"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from pmocr import latex
from pmocr.config import Config
from pmocr.latex import build_document, render, strip_delimiters, tex_available
from tests.helpers import make_tmp


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["xelatex"], returncode=returncode, stdout=stdout, stderr=stderr)


class StripTests(unittest.TestCase):
    def test_strips_bracket_delimiters(self) -> None:
        self.assertEqual(strip_delimiters("\\[ x^2 \\]"), "x^2")

    def test_strips_dollar_delimiters(self) -> None:
        self.assertEqual(strip_delimiters("$$ x^2 $$"), "x^2")

    def test_keeps_plain_math(self) -> None:
        self.assertEqual(strip_delimiters("  \\frac{1}{2}  "), "\\frac{1}{2}")

    def test_keeps_inner_dollars(self) -> None:
        self.assertEqual(strip_delimiters("$a$ + $b$"), "$a$ + $b$")

    def test_handles_empty(self) -> None:
        self.assertEqual(strip_delimiters(""), "")
        self.assertEqual(strip_delimiters(None), "")

    def test_document_has_standalone_and_amsmath(self) -> None:
        doc = build_document("x^2")
        self.assertIn("standalone", doc)
        self.assertIn("amsmath", doc)
        self.assertIn("$\\displaystyle x^2$", doc)


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.cfg = Config.load(None, environ={})

    def test_missing_pdf_is_reported_not_raised(self) -> None:
        result = render("x^2", self.tmp, "b1", self.cfg, runner=lambda *a, **k: _completed(1, "! Undefined control sequence"))
        self.assertFalse(result.ok)
        self.assertIn("Undefined control sequence", result.error)

    def test_stale_artifacts_are_removed(self) -> None:
        (self.tmp / "b1.pdf").write_bytes(b"%PDF-old")
        (self.tmp / "b1.png").write_bytes(b"old")
        result = render("x^2", self.tmp, "b1", self.cfg, runner=lambda *a, **k: _completed(1))
        self.assertFalse(result.ok)
        self.assertFalse((self.tmp / "b1.png").exists())

    def test_tex_source_is_kept_for_debugging(self) -> None:
        render("x^2", self.tmp, "b1", self.cfg, runner=lambda *a, **k: _completed(1))
        self.assertIn("x^2", (self.tmp / "b1.tex").read_text(encoding="utf-8"))

    def test_success_path_via_patched_pdf_to_png(self) -> None:
        def fake_convert(pdf, png, dpi):
            Path(png).write_bytes(b"png")

        def fake_runner(*args, **kwargs):
            (self.tmp / "b2.pdf").write_bytes(b"%PDF-1.4")
            return _completed(0)

        with mock.patch.object(latex, "_pdf_to_png", side_effect=fake_convert):
            result = render("x^2", self.tmp, "b2", self.cfg, runner=fake_runner)
        self.assertTrue(result.ok)
        self.assertTrue(result.png.exists())

    def test_missing_xelatex_becomes_render_error(self) -> None:
        def boom(*args, **kwargs):
            raise FileNotFoundError("xelatex")

        with self.assertRaises(latex.RenderError):
            render("x^2", self.tmp, "b3", self.cfg, runner=boom)

    def test_timeout_is_reported(self) -> None:
        def slow(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="xelatex", timeout=1)

        result = render("x^2", self.tmp, "b4", self.cfg, runner=slow)
        self.assertFalse(result.ok)
        self.assertIn("超时", result.error)

    def test_tex_bin_dir_is_prepended_to_path(self) -> None:
        seen = {}

        def capture(cmd, **kwargs):
            seen.update(kwargs)
            return _completed(1)

        cfg = Config.load(None, overrides={"tex_bin_dir": "C:/tex/bin"}, environ={})
        render("x^2", self.tmp, "b5", cfg, runner=capture)
        self.assertTrue(seen["env"]["PATH"].startswith("C:/tex/bin" + os.pathsep))

    @unittest.skipUnless(os.environ.get("PMOCR_TEST_TEX") and tex_available(), "需要真 TeX 环境（PMOCR_TEST_TEX=1）")
    def test_real_xelatex(self) -> None:
        cfg = Config.load(None, environ={})
        result = render("\\frac{1}{1-z}=1+z+\\cdots", self.tmp, "real", cfg)
        self.assertTrue(result.ok, result.error)


if __name__ == "__main__":
    unittest.main()
