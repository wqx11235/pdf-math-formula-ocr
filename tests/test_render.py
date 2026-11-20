"""PDF → 页图：命名、跳过已渲染、覆盖、异常输入。"""

from __future__ import annotations

import types
import unittest
from pathlib import Path

from pmocr.errors import DataError
from pmocr.render import DEFAULT_EDGE, page_name, render_pdf
from tests.helpers import make_tmp


class _FakePix:
    def __init__(self, size: int = 2048) -> None:
        self._size = size

    def save(self, path: str) -> None:
        Path(path).write_bytes(b"x" * self._size)


class _FakePage:
    def __init__(self, width: float, height: float) -> None:
        self.rect = types.SimpleNamespace(width=width, height=height)
        self.zooms: list[float] = []

    def get_pixmap(self, matrix) -> _FakePix:  # noqa: ANN001 - 只关心是否被调用
        return _FakePix()


class _FakeDoc:
    def __init__(self, pages: int) -> None:
        self._pages = [_FakePage(1200, 1800) for _ in range(pages)]
        self.closed = False

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, index: int) -> _FakePage:
        return self._pages[index]

    def close(self) -> None:
        self.closed = True


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.pdf = self.tmp / "book.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 fake")
        self.out = self.tmp / "pages"

    def _doc(self, pages: int = 3) -> _FakeDoc:
        return _FakeDoc(pages)

    def test_renders_every_page_with_pipeline_names(self) -> None:
        summary = render_pdf(self.pdf, self.out, opener=lambda _p: self._doc(3), log=lambda _m: None)
        self.assertEqual((summary.total, summary.written, summary.skipped), (3, 3, 0))
        self.assertEqual(sorted(p.name for p in self.out.glob("*.png")), ["p-01.png", "p-02.png", "p-03.png"])

    def test_skips_existing_pages(self) -> None:
        self.out.mkdir()
        (self.out / "p-01.png").write_bytes(b"x" * 2048)
        summary = render_pdf(self.pdf, self.out, opener=lambda _p: self._doc(3), log=lambda _m: None)
        self.assertEqual((summary.written, summary.skipped), (2, 1))

    def test_overwrite_rerenders(self) -> None:
        self.out.mkdir()
        (self.out / "p-01.png").write_bytes(b"x" * 2048)
        summary = render_pdf(self.pdf, self.out, overwrite=True, opener=lambda _p: self._doc(2), log=lambda _m: None)
        self.assertEqual((summary.written, summary.skipped), (2, 0))

    def test_tiny_existing_file_is_rebuilt(self) -> None:
        self.out.mkdir()
        (self.out / "p-01.png").write_bytes(b"x")
        summary = render_pdf(self.pdf, self.out, opener=lambda _p: self._doc(1), log=lambda _m: None)
        self.assertEqual(summary.written, 1)

    def test_doc_is_closed(self) -> None:
        doc = self._doc(1)
        render_pdf(self.pdf, self.out, opener=lambda _p: doc, log=lambda _m: None)
        self.assertTrue(doc.closed)

    def test_missing_pdf_is_reported(self) -> None:
        with self.assertRaises(DataError):
            render_pdf(self.tmp / "nope.pdf", self.out, opener=lambda _p: self._doc(1))

    def test_bad_edge_is_rejected(self) -> None:
        with self.assertRaises(DataError):
            render_pdf(self.pdf, self.out, edge=0, opener=lambda _p: self._doc(1))

    def test_page_name_pads_two_digits(self) -> None:
        self.assertEqual(page_name(7), "p-07.png")
        self.assertEqual(page_name(123), "p-123.png")

    def test_default_edge_matches_pipeline(self) -> None:
        self.assertEqual(DEFAULT_EDGE, 8157)


if __name__ == "__main__":
    unittest.main()
