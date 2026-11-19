"""测试共用夹具：造页面图、块级 JSON、假渲染器、临时目录。"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from PIL import Image

from pmocr.latex import RenderResult


def _pick_root() -> Path:
    """测试临时目录：系统 temp 优先，不可写就退回仓库内；PMOCR_TEST_TMP 可覆盖。

    不用 tempfile.mkdtemp：它建 0700 目录，受限令牌下后续写入会被拒。
    gettempdir() 在某些受限环境会返回空串，必须用绝对路径兜底，否则会在仓库里造目录。
    """
    override = os.environ.get("PMOCR_TEST_TMP")
    if override:
        return Path(override)
    base = tempfile.gettempdir()
    if base and Path(base).is_absolute():
        candidate = Path(base).resolve() / "pmocr-tests"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            pass
    return Path(".testtmp")


TEST_TMP_ROOT = _pick_root()


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
