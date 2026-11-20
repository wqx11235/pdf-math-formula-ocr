"""逐页 Markdown → 成稿：排序、跳过、空页、抬头。"""

from __future__ import annotations

import unittest

from pmocr.errors import DataError
from pmocr.merge import merge_pages, page_number
from tests.helpers import make_tmp


class MergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.pages = self.tmp / "pages"
        self.pages.mkdir()
        self.out = self.tmp / "book.md"

    def _page(self, name: str, text: str) -> None:
        (self.pages / name).write_text(text, encoding="utf-8")

    def test_sorts_by_page_number_not_lexicographically(self) -> None:
        self._page("p-10.md", "第十页")
        self._page("p-2.md", "第二页")
        summary = merge_pages(self.pages, self.out, title="书")
        text = self.out.read_text(encoding="utf-8")
        self.assertLess(text.index("第二页"), text.index("第十页"))
        self.assertEqual(summary.kept, 2)

    def test_header_subtitle_and_note(self) -> None:
        self._page("p-01.md", "正文")
        merge_pages(self.pages, self.out, title="解析数论", subtitle="GTM177", note="自动成稿")
        text = self.out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 解析数论"))
        self.assertIn("> GTM177", text)
        self.assertIn("自动成稿", text)

    def test_page_marker_kept(self) -> None:
        self._page("p-07.md", "正文")
        merge_pages(self.pages, self.out, title="书")
        self.assertIn("PDF 第 7 页 (p-07)", self.out.read_text(encoding="utf-8"))

    def test_skip_pages(self) -> None:
        self._page("p-01.md", "封面")
        self._page("p-02.md", "正文")
        summary = merge_pages(self.pages, self.out, title="书", skip=(1,))
        text = self.out.read_text(encoding="utf-8")
        self.assertNotIn("封面", text)
        self.assertEqual(summary.kept, 1)

    def test_empty_pages_are_dropped(self) -> None:
        self._page("p-01.md", "   ")
        self._page("p-02.md", "正文")
        summary = merge_pages(self.pages, self.out, title="书")
        self.assertEqual(summary.kept, 1)

    def test_missing_directory_is_reported(self) -> None:
        with self.assertRaises(DataError):
            merge_pages(self.tmp / "nope", self.out, title="书")

    def test_empty_directory_is_reported(self) -> None:
        with self.assertRaises(DataError):
            merge_pages(self.pages, self.out, title="书")

    def test_empty_title_is_rejected(self) -> None:
        self._page("p-01.md", "正文")
        with self.assertRaises(DataError):
            merge_pages(self.pages, self.out, title="  ")

    def test_output_size_is_reported(self) -> None:
        self._page("p-01.md", "正文" * 100)
        summary = merge_pages(self.pages, self.out, title="书")
        self.assertEqual(summary.size, self.out.stat().st_size)

    def test_page_number_parsing(self) -> None:
        self.assertEqual(page_number("p-07.md"), 7)
        self.assertEqual(page_number("p-123.md"), 123)
        self.assertEqual(page_number("random.md"), 0)


if __name__ == "__main__":
    unittest.main()
