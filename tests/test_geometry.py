"""坐标系：缩放、留白、越界裁剪、非法输入。"""

from __future__ import annotations

import unittest

from pmocr.geometry import Size, fit_max_side, scale_bbox


class GeometryTests(unittest.TestCase):
    def test_fit_max_side_keeps_small_image(self) -> None:
        size = Size(800, 600)
        self.assertEqual(fit_max_side(size, 1600), size)

    def test_fit_max_side_scales_longest_edge(self) -> None:
        result = fit_max_side(Size(3200, 800), 1600)
        self.assertEqual(result, Size(1600, 400))

    def test_fit_max_side_never_returns_zero(self) -> None:
        result = fit_max_side(Size(10000, 50), 100)
        self.assertGreaterEqual(result.height, 1)

    def test_scale_bbox_identity_when_sizes_match(self) -> None:
        box = scale_bbox((10, 20, 30, 40), Size(400, 600), Size(400, 600))
        self.assertEqual(box, (10, 20, 30, 40))

    def test_scale_bbox_scales_both_axes(self) -> None:
        box = scale_bbox((100, 100, 200, 200), Size(1000, 1000), Size(500, 2000))
        self.assertEqual(box, (50, 200, 100, 400))

    def test_scale_bbox_applies_padding(self) -> None:
        box = scale_bbox((10, 10, 20, 20), Size(100, 100), Size(100, 100), pad=5)
        self.assertEqual(box, (5, 5, 25, 25))

    def test_scale_bbox_clamps_at_edges(self) -> None:
        box = scale_bbox((0, 0, 100, 100), Size(100, 100), Size(100, 100), pad=10)
        self.assertEqual(box, (0, 0, 100, 100))

    def test_scale_bbox_rejects_inverted_box(self) -> None:
        with self.assertRaises(ValueError):
            scale_bbox((50, 50, 10, 10), Size(100, 100), Size(100, 100))

    def test_scale_bbox_rejects_wrong_length(self) -> None:
        with self.assertRaises(ValueError):
            scale_bbox((1, 2, 3), Size(100, 100), Size(100, 100))

    def test_size_rejects_zero(self) -> None:
        with self.assertRaises(ValueError):
            Size(0, 10)


if __name__ == "__main__":
    unittest.main()
