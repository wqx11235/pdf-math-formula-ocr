"""读 SDK 的块级数据，抽出待复核的公式块。

不碰图像、不打分、不写报告；输入一个 JSON，输出结构化对象。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .errors import DataError
from .geometry import Size
from .latex import strip_delimiters
from .paths import PageRef

FORMULA_LABELS = frozenset({"display_formula", "isolate_formula", "interline_equation"})

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class FormulaBlock:
    """一个公式块：页、页内序号（1 起）、bbox、候选 LaTeX。"""

    page_id: str
    index: int
    bbox: BBox
    tex: str


@dataclass(frozen=True)
class PageDoc:
    page_id: str
    image_size: Size
    blocks: tuple[FormulaBlock, ...]


def load_page(
    ref: PageRef,
    strip: Callable[[str], str] = strip_delimiters,
) -> PageDoc:
    """解析一页的块级 JSON。空 LaTeX 的块直接丢弃（无从复核）。"""
    try:
        raw = json.loads(ref.json_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataError("块级数据不存在: %s" % ref.json_path) from exc
    except json.JSONDecodeError as exc:
        raise DataError("块级数据不是合法 JSON: %s" % ref.json_path) from exc

    ocr = _ocr_section(raw, ref.json_path)
    size = _image_size(ocr)
    blocks: list[FormulaBlock] = []
    for block in _raw_blocks(ocr):
        if block.get("label") not in FORMULA_LABELS:
            continue
        tex = strip(block.get("content") or "")
        if not tex:
            continue
        blocks.append(
            FormulaBlock(
                page_id=ref.page_id,
                index=len(blocks) + 1,
                bbox=_bbox(block.get("bbox"), ref.json_path),
                tex=tex,
            )
        )
    return PageDoc(page_id=ref.page_id, image_size=size, blocks=tuple(blocks))


def _ocr_section(raw: dict[str, Any], path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DataError("块级数据顶层不是对象: %s" % path)
    section = raw.get("ocr") or raw
    if not isinstance(section, dict):
        raise DataError("块级数据缺少 ocr 段: %s" % path)
    return section


def _image_size(ocr: dict[str, Any]) -> Size:
    width = ocr.get("image_width")
    height = ocr.get("image_height")
    try:
        return Size(int(width), int(height))
    except (TypeError, ValueError) as exc:
        raise DataError("ocr 段缺少有效的 image_width/image_height: %r/%r" % (width, height)) from exc


def _raw_blocks(ocr: dict[str, Any]) -> Iterable[dict[str, Any]]:
    blocks = ocr.get("blocks") or []
    if not isinstance(blocks, list):
        raise DataError("ocr.blocks 不是数组")
    return blocks


def _bbox(value: Any, path) -> BBox:
    try:
        x0, y0, x1, y1 = (float(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise DataError("块 bbox 不是 4 个数: %r (%s)" % (value, path)) from exc
    return (x0, y0, x1, y1)
