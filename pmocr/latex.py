"""候选 LaTeX 的清洗、装配与渲染（xelatex → PDF → PNG）。

只负责「把一段 LaTeX 变成一张 PNG」，不认识页、不认识 Jev。
渲染器可按需替换（测试里注入假 runner）。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Config
from .errors import RenderError

# \everymath{\displaystyle} 是必须的，不是审美选择：
# OCR 把多行公式写成 \begin{array}{l}…\end{array}，而 array 单元格默认按 textstyle 排版，
# 求和号上下限会跑到右下角、分式变小，和扫描页的 display 排版不一致，Jev 会因此扣分。
# 22 块实测：均值 0.9470 → 0.9676，其中一块误报 0.4275 → 0.8304。
TEMPLATE = (
    "\\documentclass[12pt,border=3pt]{standalone}\n"
    "\\usepackage{amsmath}\n"
    "\\everymath{\\displaystyle}\n"
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

    cache_dir = _cache_dir(cfg)
    cache_file = cache_dir / (_tex_key(tex, cfg) + ".png") if cache_dir else None
    if cache_file is not None and cache_file.is_file() and cache_file.stat().st_size > 0:
        # 同一段 LaTeX 之前渲染过：直接复用，省掉一次 xelatex（约 1.2s）
        shutil.copyfile(cache_file, png_path)
        return RenderResult(png_path)

    # 上一次同名渲染的产物必须清掉，否则 xelatex 失败时会把旧 PDF 当新结果
    for stale in (pdf_path, png_path):
        stale.unlink(missing_ok=True)

    cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    run = runner or subprocess.run
    try:
        proc = run(
            cmd,
            cwd=str(workdir),
            env=_tex_env(cfg, workdir),
            capture_output=True,
            text=True,
            timeout=cfg.render_timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError as exc:
        raise RenderError("找不到 xelatex，请安装 TeX Live 或设置 tex_bin_dir") from exc
    except subprocess.TimeoutExpired:
        return RenderResult(None, "xelatex 超时（%.0fs）" % cfg.render_timeout)

    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        return RenderResult(None, output[-400:])
    try:
        _pdf_to_png(pdf_path, png_path, cfg.render_dpi)
    except Exception as exc:  # PyMuPDF 对个别 PDF 会抛各类异常
        return RenderResult(None, "PDF 转 PNG 失败: %s" % exc)
    if cache_file is not None:
        try:
            shutil.copyfile(png_path, cache_file)
        except OSError:
            pass
    return RenderResult(png_path)


_CACHE_CHOICES: dict[tuple[bool, str], Path | None] = {}


def _cache_dir(cfg: Config) -> Path | None:
    """渲染缓存目录：同一段 LaTeX 只编译一次，做 A/B 时省掉重复渲染。

    候选目录依次尝试，第一个能写文件的就用（受限进程写 AppData 会被拒）。
    结果按进程缓存：并发渲染时若每次都探测，探针文件会互相踩踏，探测失败就退回「无缓存」。
    """
    key = (cfg.render_cache, cfg.render_cache_dir)
    if key in _CACHE_CHOICES:
        return _CACHE_CHOICES[key]
    if not cfg.render_cache:
        _CACHE_CHOICES[key] = None
        return None
    candidates = []
    if cfg.render_cache_dir:
        candidates.append(Path(cfg.render_cache_dir))
    else:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "pmocr" / "render-cache")
        try:
            tmp = Path(tempfile.gettempdir())
            if tmp.is_absolute():
                candidates.append(tmp / "pmocr" / "render-cache")
        except (FileNotFoundError, OSError):
            pass
    chosen: Path | None = None
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / (".probe-%d" % os.getpid())
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            chosen = base
            break
        except OSError:
            continue
    _CACHE_CHOICES[key] = chosen
    return chosen


def _tex_key(tex: str, cfg: Config) -> str:
    payload = "%s|%d|v1" % (tex, cfg.render_dpi)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _tex_env(cfg: Config, workdir: Path) -> dict[str, str]:
    """xelatex 的 TMP/TEMP 必须指向可写目录。

    实测：TMP 不可写时 xdvipdfmx 会以 driver return code 崩溃，留下 0 字节 PDF，
    看起来像「候选 LaTeX 坏了」，实际是环境问题。旧单文件脚本显式设过 TMP，
    拆分时漏了，这里补回并默认落到本次渲染目录下。
    """
    env = dict(os.environ)
    if cfg.tex_bin_dir:
        env["PATH"] = cfg.tex_bin_dir + os.pathsep + env.get("PATH", "")
    temp = Path(cfg.temp_dir) if cfg.temp_dir else Path(workdir) / ".tex-tmp"
    temp.mkdir(parents=True, exist_ok=True)
    env["TMP"] = env["TEMP"] = str(temp)
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

