"""块级 JSON 解析：标签过滤、序号、坐标与坏数据。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from pmocr.errors import DataError
from pmocr.ocr import FORMULA_LABELS, load_page
from pmocr.paths import PageRef
from tests.helpers import make_tmp


class OcrTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()

    def _ref(self, payload: dict | str) -> PageRef:
        path = self.tmp / "p-01.json"
        text = payload if isinstance(payload, str) else json.dumps(payload)
        path.write_text(text, encoding="utf-8")
        return PageRef("p-01", path, None)

    def test_extracts_only_formula_blocks(self) -> None:
        ref = self._ref(
            {
                "ocr": {
                    "image_width": 800,
                    "image_height": 1000,
                    "blocks": [
                        {"label": "text", "content": "正文", "bbox": [0, 0, 10, 10]},
                        {"label": "display_formula", "content": "$$x^2$$", "bbox": [10, 20, 30, 40]},
                        {"label": "isolate_formula", "content": "y", "bbox": [50, 60, 70, 80]},
                    ],
                }
            }
        )
        page = load_page(ref)
        self.assertEqual(page.image_size.width, 800)
        self.assertEqual([b.index for b in page.blocks], [1, 2])
        self.assertEqual(page.blocks[0].tex, "x^2")
        self.assertEqual(page.blocks[0].bbox, (10.0, 20.0, 30.0, 40.0))

    def test_drops_empty_content(self) -> None:
        ref = self._ref(
            {
                "ocr": {
                    "image_width": 10,
                    "image_height": 10,
                    "blocks": [{"label": "display_formula", "content": "  ", "bbox": [0, 0, 1, 1]}],
                }
            }
        )
        self.assertEqual(load_page(ref).blocks, ())

    def test_accepts_flat_payload(self) -> None:
        ref = self._ref(
            {"image_width": 10, "image_height": 10, "blocks": [{"label": "display_formula", "content": "z", "bbox": [0, 0, 1, 1]}]}
        )
        self.assertEqual(len(load_page(ref).blocks), 1)

    def test_missing_size_raises(self) -> None:
        ref = self._ref({"ocr": {"blocks": []}})
        with self.assertRaises(DataError):
            load_page(ref)

    def test_broken_bbox_raises(self) -> None:
        ref = self._ref(
            {"ocr": {"image_width": 10, "image_height": 10, "blocks": [{"label": "display_formula", "content": "x", "bbox": [1, 2]}]}}
        )
        with self.assertRaises(DataError):
            load_page(ref)

    def test_invalid_json_raises(self) -> None:
        with self.assertRaises(DataError):
            load_page(self._ref("{not json"))

    def test_formula_labels_contain_expected_names(self) -> None:
        self.assertIn("display_formula", FORMULA_LABELS)
        self.assertIn("interline_equation", FORMULA_LABELS)


if __name__ == "__main__":
    unittest.main()
