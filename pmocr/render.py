"""PDF → 逐页 PNG。

复核要的是页面图（``p-01.png``），而输入往往是 PDF。这一步补上缺口，
命名与流水线一致：``p-%02d.png``，长边统一缩放，方便断点续跑。

只做渲染，不解析、不打分；PDF 库通过 ``opener`` 注入，便于单测。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .errors import DataError

DEFAULT_EDGE = 8157
MIN_BYTES = 1000  # 小于这个视为半截文件，重渲染

Opener = Callable[[Path], object]


@dataclass(frozen=True)
class RenderSummary:
    total: int
    written: int
    skipped: int


def page_name(number: int) -> str:
    return "p-%02d.png" % number


def render_pdf(
    pdf: str | Path,
    out_dir: str | Path,
    *,
    edge: int = DEFAULT_EDGE,
    overwrite: bool = False,
    opener: Opener | None = None,
    log: Callable[[str], None] | None = None,
) -> RenderSummary:
    """把 PDF 每页渲染成 PNG；已存在且不小于 1KB 的页默认跳过。"""
    pdf = Path(pdf)
    if not pdf.is_file():
        raise DataError("PDF 不存在: %s" % pdf)
    if edge <= 0:
        raise DataError("edge 必须为正，收到 %r" % edge)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    say = log or (lambda message: print(message, file=sys.stderr))

    doc = (opener or _open_pdf)(pdf)
    written = skipped = 0
    try:
        total = len(doc)  # type: ignore[arg-type]
        for index in range(total):
            target = out / page_name(index + 1)
            if not overwrite and target.is_file() and target.stat().st_size >= MIN_BYTES:
                skipped += 1
                continue
            _save_page(doc, index, target, edge)  # type: ignore[arg-type]
            written += 1
            say("[render] %s" % target.name)
    finally:
        doc.close()  # type: ignore[attr-defined]
    return RenderSummary(total=total, written=written, skipped=skipped)


def _open_pdf(path: Path):
    try:
        import pymupdf
    except ImportError:  # 旧版 PyMuPDF 只提供 fitz
        import fitz as pymupdf
    return pymupdf.open(str(path))


def _save_page(doc, index: int, target: Path, edge: int) -> None:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf

    page = doc[index]
    rect = page.rect
    longest = max(rect.width, rect.height)
    if longest <= 0:
        raise DataError("第 %d 页尺寸为 0" % (index + 1))
    zoom = edge / longest
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    pix.save(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise DataError("第 %d 页渲染失败: %s" % (index + 1, target))


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m pmocr.render`` 的入口（``python -m pmocr render`` 也可以）。"""
    from .cli import main as cli_main

    return cli_main(["render", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
