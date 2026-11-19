"""文件系统：发现输入、准备输出目录、给裁图命名。

把「路径从哪来、放哪去」集中在这里，其余模块只接收 Path / 字符串 ID。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import DataError


@dataclass(frozen=True)
class PageRef:
    """一页的输入：块级 JSON 必有的页面图可选（缺图则该页跳过）。"""

    page_id: str
    json_path: Path
    image_path: Path | None

    @property
    def usable(self) -> bool:
        return self.image_path is not None


@dataclass(frozen=True)
class OutputLayout:
    """复核产物的固定布局，路径只在构造函数里拼一次。"""

    root: Path
    render_dir: Path
    csv_path: Path
    markdown_path: Path

    def crop_path(self, page_id: str, index: int) -> Path:
        return self.render_dir / ("%s_b%d_region.png" % (page_id, index))

    def render_png(self, page_id: str, index: int) -> Path:
        return self.render_dir / ("%s_b%d_candidate.png" % (page_id, index))


def discover_pages(pages_dir: str | Path, images_dir: str | Path) -> list[PageRef]:
    """列出 pages_json 下所有页，按页名自然排序。

    缺页面图不报错，只把 image_path 置空——由上层决定跳过并提示，
    这样「整套 29 页缺 1 页图」不会中断整批复核。
    """
    pages_dir = Path(pages_dir)
    images_dir = Path(images_dir)
    if not pages_dir.is_dir():
        raise DataError("pages 目录不存在: %s" % pages_dir)

    refs: list[PageRef] = []
    for json_path in sorted(pages_dir.glob("*.json")):
        page_id = json_path.stem
        image = images_dir / (page_id + ".png")
        refs.append(PageRef(page_id, json_path, image if image.is_file() else None))
    if not refs:
        raise DataError("pages 目录里没有 *.json: %s" % pages_dir)
    return refs


def prepare_outputs(out_dir: str | Path) -> OutputLayout:
    """建好输出目录，返回产物路径。重复调用是幂等的。"""
    root = Path(out_dir)
    render_dir = root / "_render"
    render_dir.mkdir(parents=True, exist_ok=True)
    return OutputLayout(
        root=root,
        render_dir=render_dir,
        csv_path=root / "formula_qc.csv",
        markdown_path=root / "待复核.md",
    )
