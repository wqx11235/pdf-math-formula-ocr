"""候选 LaTeX 的清洗、装配与渲染（xelatex → PDF → PNG）。

只负责「把一段 LaTeX 变成一张 PNG」，不认识页、不认识 Jev。
渲染器可按需替换（测试里注入假 runner）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Config
from .errors import RenderError

TEMPLATE = (
    "\\documentclass[12pt,border=3pt]{standalone}\n"
    "\\usepackage{amsmath}\n"
    "\\begin{document}\n"
    "$\\displaystyle %s$\n"
    "\\end{document}\n"
)

_LEADING_DELIMS = (re.compile(r"^\s*\\\["), re.compile(r"^\s*\$\$"))
_TRAILING_DELIMS = (re.compile(r"\\\]\s*$"), re.compile(r"\$\$\s*$"))

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class RenderResult:
    png: Path | None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.png is not None


def strip_delimiters(tex: str) -> str:
    """去掉 OCR 常带的外层 ``\\[ ... \\]`` / ``$$ ... $$``。"""
    text = (tex or "").strip()
    for pattern in _LEADING_DELIMS:
        text = pattern.sub("", text, count=1)
    for pattern in _TRAILING_DELIMS:
        text = pattern.sub("", text, count=1)
    return text.strip()


def build_document(tex: str) -> str:
    return TEMPLATE % tex


def render(
    tex: str,
    workdir: str | Path,
    name: str,
    cfg: Config,
    *,
    runner: Runner | None = None,
) -> RenderResult:
    """渲染失败不抛异常，返回 ``RenderResult(None, error)`` 供上层记账。

    只有在 TeX 环境本身不可用时才抛 ``RenderError``——那是配置问题，
    静默记成「块渲染失败」会掩盖真正原因。
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    tex_path = workdir / (name + ".tex")
    pdf_path = workdir / (name + ".pdf")
    png_path = workdir / (name + ".png")
    tex_path.write_text(build_document(tex), encoding="utf-8")
    # 上一次同名渲染的产物必须清掉，否则 xelatex 失败时会把旧 PDF 当新结果
    for stale in (pdf_path, png_path):
        stale.unlink(missing_ok=True)

    cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    run = runner or subprocess.run
    try:
        proc = run(
            cmd,
            cwd=str(workdir),
            env=_tex_env(cfg),
            capture_output=True,
            text=True,
            timeout=cfg.render_timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError as exc:
        raise RenderError("找不到 xelatex，请安装 TeX Live 或设置 tex_bin_dir") from exc
    except subprocess.TimeoutExpired:
        return RenderResult(None, "xelatex 超时（%.0fs）" % cfg.render_timeout)

    if not pdf_path.exists():
        return RenderResult(None, output[-400:])
    try:
        _pdf_to_png(pdf_path, png_path, cfg.render_dpi)
    except Exception as exc:  # PyMuPDF 对个别 PDF 会抛各类异常
        return RenderResult(None, "PDF 转 PNG 失败: %s" % exc)
    return RenderResult(png_path)


def _tex_env(cfg: Config) -> dict[str, str]:
    env = dict(os.environ)
    if cfg.tex_bin_dir:
        env["PATH"] = cfg.tex_bin_dir + os.pathsep + env.get("PATH", "")
    if cfg.temp_dir:
        Path(cfg.temp_dir).mkdir(parents=True, exist_ok=True)
        env["TMP"] = env["TEMP"] = cfg.temp_dir
    return env


def _pdf_to_png(pdf_path: Path, png_path: Path, dpi: int) -> None:
    try:
        import pymupdf
    except ImportError:  # 旧版 PyMuPDF 只提供 fitz
        import fitz as pymupdf
    doc = pymupdf.open(str(pdf_path))
    try:
        page = doc[0]
        page.get_pixmap(dpi=dpi).save(str(png_path))
    finally:
        doc.close()
    if not png_path.exists():  # pragma: no cover - 防御性
        raise RenderError("PNG 未生成: %s" % png_path)


def tex_available() -> bool:
    """TeX 是否可用，用于跳过需要真编译的测试。"""
    from shutil import which

    return which("xelatex") is not None or Path("D:/Texlive/texlive/2025/bin/windows/xelatex.exe").exists()


__all__ = [
    "RenderResult",
    "strip_delimiters",
    "build_document",
    "render",
    "tex_available",
]

if __name__ == "__main__":  # pragma: no cover
    sys.exit("latex 模块不单独运行，请用 python -m pmocr.cli")
