"""输入发现与输出布局。"""

from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

from pmocr.errors import DataError
from pmocr.paths import discover_pages, prepare_outputs
from tests.helpers import make_tmp


class PathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.pages = self.tmp / "pages_json"
        self.images = self.tmp / "images"
        self.pages.mkdir()
        self.images.mkdir()

    def _json(self, name: str) -> None:
        (self.pages / (name + ".json")).write_text("{}", encoding="utf-8")

    def _png(self, name: str) -> None:
        Image.new("RGB", (10, 10), "white").save(self.images / (name + ".png"))

    def test_discovers_sorted_pages(self) -> None:
        self._json("p-2")
        self._json("p-10")
        self._png("p-2")
        refs = discover_pages(self.pages, self.images)
        self.assertEqual([r.page_id for r in refs], ["p-10", "p-2"])

    def test_missing_image_marks_page_unusable(self) -> None:
        self._json("p-1")
        refs = discover_pages(self.pages, self.images)
        self.assertFalse(refs[0].usable)

    def test_present_image_is_usable(self) -> None:
        self._json("p-1")
        self._png("p-1")
        self.assertTrue(discover_pages(self.pages, self.images)[0].usable)

    def test_missing_pages_dir_raises(self) -> None:
        with self.assertRaises(DataError):
            discover_pages(self.tmp / "nope", self.images)

    def test_empty_pages_dir_raises(self) -> None:
        with self.assertRaises(DataError):
            discover_pages(self.pages, self.images)

    def test_output_layout_paths(self) -> None:
        layout = prepare_outputs(self.tmp / "out")
        self.assertTrue(layout.render_dir.is_dir())
        self.assertTrue(layout.csv_path.parent.is_dir())
        self.assertTrue(layout.markdown_path.parent.is_dir())
        self.assertEqual(layout.render_dir.name, "_render")

    def test_crop_and_render_names_are_distinct(self) -> None:
        layout = prepare_outputs(self.tmp / "out")
        self.assertNotEqual(layout.crop_path("p-1", 2), layout.render_png("p-1", 2))
        self.assertIn("p-1", layout.crop_path("p-1", 2).name)


if __name__ == "__main__":
    unittest.main()
