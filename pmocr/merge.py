"""逐页 Markdown → 一本成稿。

产物格式与旧 merge_book.py 保持一致（标题 / 副标题 / 说明 / 每页分页注释），
所以已经在下游读成稿的工具不用改。

只做拼接，不改正文、不修公式；排版问题回复核报告里解决。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .errors import DataError

_PAGE_NUMBER = re.compile(r"(\d+)")


@dataclass(frozen=True)
class MergeSummary:
    kept: int
    path: Path
    size: int

    @property
    def skipped(self) -> int:
        return 0


def page_number(filename: str) -> int:
    """从 ``p-07.md`` 里取 7；取不到算 0。"""
    match = _PAGE_NUMBER.search(Path(filename).stem)
    return int(match.group(1)) if match else 0


def merge_pages(
    pages_dir: str | Path,
    out: str | Path,
    *,
    title: str,
    subtitle: str = "",
    note: str = "",
    skip: Iterable[int] = (),
) -> MergeSummary:
    """按页码排序拼接所有 ``*.md``，空页丢弃。"""
    pages = Path(pages_dir)
    if not pages.is_dir():
        raise DataError("页目录不存在: %s" % pages)
    if not title.strip():
        raise DataError("title 不能为空")

    skipped = {int(item) for item in skip}
    files = sorted((p for p in pages.iterdir() if p.suffix.lower() == ".md"), key=lambda p: page_number(p.name))
    if not files:
        raise DataError("页目录里没有 *.md: %s" % pages)

    parts: list[str] = ["# " + title.strip() + "\n"]
    if subtitle:
        parts.append("> " + subtitle.strip() + "\n")
    parts.append("\n---\n")
    if note:
        parts.append("\n" + note.strip() + "\n")

    kept = 0
    for path in files:
        number = page_number(path.name)
        if number in skipped:
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        parts.append("\n<!-- ===== PDF 第 %d 页 (p-%02d) ===== -->\n\n" % (number, number))
        parts.append(text + "\n")
        kept += 1

    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(parts), encoding="utf-8")
    return MergeSummary(kept=kept, path=target, size=target.stat().st_size)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m pmocr.merge`` 的入口（``python -m pmocr merge`` 也可以）。"""
    from .cli import main as cli_main

    return cli_main(["merge", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
