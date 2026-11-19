"""坐标系换算：把 OCR 返回的 bbox 映射到页面图，并约束图像尺寸。

只做纯计算，不开图、不写文件，因此可以单独单测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Size:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("尺寸必须为正: %r" % (self,))

    @property
    def longest(self) -> int:
        return max(self.width, self.height)


def fit_max_side(size: Size, max_side: int) -> Size:
    """等比缩放到最长边不超过 max_side；本来就不超就原样返回。"""
    if max_side <= 0:
        raise ValueError("max_side 必须为正")
    if size.longest <= max_side:
        return size
    ratio = max_side / size.longest
    return Size(max(1, int(size.width * ratio)), max(1, int(size.height * ratio)))


def scale_bbox(
    bbox: Sequence[float],
    source: Size,
    target: Size,
    pad: int = 0,
) -> Box:
    """把 source 坐标系下的 bbox 映射到 target 坐标系，加 pad 并裁到图内。

    OCR 的 bbox 常来自「处理后图像」，尺寸与页面图不同，必须先换算再用，
    否则裁出来的块会整体偏移（历史 bug）。
    """
    if len(bbox) != 4:
        raise ValueError("bbox 需要 4 个数，收到 %r" % (bbox,))
    if pad < 0:
        raise ValueError("pad 不能为负")
    x0, y0, x1, y1 = (float(v) for v in bbox)
    if x1 < x0 or y1 < y0:
        raise ValueError("bbox 上界小于下界: %r" % (bbox,))
    sx = target.width / source.width
    sy = target.height / source.height
    return (
        _clamp(int(round(x0 * sx)) - pad, 0, target.width),
        _clamp(int(round(y0 * sy)) - pad, 0, target.height),
        _clamp(int(round(x1 * sx)) + pad, 0, target.width),
        _clamp(int(round(y1 * sy)) + pad, 0, target.height),
    )


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
