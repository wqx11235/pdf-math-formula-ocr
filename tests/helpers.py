"""测试共用夹具：造页面图、块级 JSON、假渲染器、临时目录。"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from PIL import Image

from pmocr.latex import RenderResult

# 沙箱下系统 temp 目录不可写，测试临时目录固定在仓库内（.gitignore 已排除）。
# 注意不能用 tempfile.mkdtemp：它创建 0700 目录，受限令牌下后续写入会被拒。
TEST_TMP_ROOT = Path(os.environ.get("PMOCR_TEST_TMP", ".testtmp"))


def make_tmp() -> Path:
    path = TEST_TMP_ROOT / ("t" + uuid.uuid4().hex[:10])
    path.mkdir(parents=True)
    return path


def make_page_png(path: Path, size: tuple[int, int] = (400, 600)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)
    return path


def make_page_json(
    path: Path,
    blocks: list[dict],
    image_size: tuple[int, int] = (400, 600),
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ocr": {
            "image_width": image_size[0],
            "image_height": image_size[1],
            "blocks": blocks,
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def formula_block(label: str = "display_formula", content: str = "x^2", bbox=(10, 20, 100, 60)) -> dict:
    return {"label": label, "bbox": list(bbox), "content": content}


def fake_renderer(path: Path | None = None, error: str = ""):
    """返回一个 renderer：成功时写出 PNG，失败时返回 RenderResult(None, error)。"""

    def _render(tex, workdir, name, cfg, **_kwargs):
        if path is None:
            return RenderResult(None, error or "xelatex 失败")
        target = Path(workdir) / (name + ".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (120, 40), "white").save(target)
        return RenderResult(target)

    return _render
