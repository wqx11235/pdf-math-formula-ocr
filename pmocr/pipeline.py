"""一键流程：PDF → 页图 → 整页解析 → 公式复核 → 成稿。

就是把 render / parse / qc / merge 四步按顺序接起来，任何一步的产物
都落在工作目录里，可以在中途停下来单独重跑某一步。

设计取舍：解析那步必须调 PowerShell 脚本（SDK 在 venv 里、要拉 Ollama），
所以这里只做「发命令 + 等退出码 + 找最新的 pages_json」，命令本身不重写。
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import merge, qc, render, report
from .config import Config
from .errors import DataError, PmocrError
from .paths import OutputLayout, discover_pages, prepare_outputs

ParseRunner = Callable[[Sequence[str], Path, Path], int]
QcService = Callable[[Path, Path, OutputLayout, Config], qc.RunSummary]

PAGES_DIR = "pages"
MD_DIR = "md"
QC_DIR = "qc"
BOOK_NAME = "book.md"


@dataclass(frozen=True)
class BookRun:
    pages: int
    blocks: int
    review: int
    skipped_pages: tuple[str, ...]
    pages_dir: Path
    qc_dir: Path
    book: Path

    def as_lines(self) -> list[str]:
        return [
            "页图 %d 页 -> %s" % (self.pages, self.pages_dir),
            "公式块 %d，待复核 %d" % (self.blocks, self.review),
            "复核报告 -> %s" % (self.qc_dir / "formula_qc.csv"),
            "成稿 -> %s" % self.book,
        ]


def find_latest_pages_json(runs_dir: Path, since: float) -> Path | None:
    """解析完成后，SDK 会在 runs 下新建一个带时间戳的目录；取其中最新的那个。"""
    if not runs_dir.is_dir():
        raise DataError("runs 目录不存在: %s" % runs_dir)
    candidates = [p for p in runs_dir.iterdir() if p.is_dir() and (p / "pages_json").is_dir()]
    fresh = [p for p in candidates if p.stat().st_mtime >= since - 2]
    if not fresh:
        return None
    return max(fresh, key=lambda p: p.stat().st_mtime) / "pages_json"


def run_book(
    *,
    pdf: str | Path,
    title: str,
    workdir: str | Path,
    cfg: Config,
    repo_root: str | Path,
    subtitle: str = "",
    note: str = "",
    skip: Sequence[int] = (),
    keep_pages: bool = False,
    parse_runner: ParseRunner | None = None,
    qc_service: QcService | None = None,
    log: Callable[[str], None] | None = None,
) -> BookRun:
    """跑完一本书。失败即抛 PmocrError，不吞异常。"""
    say = log or (lambda message: print(message, file=sys.stderr))
    root = Path(workdir)
    pages_dir = root / PAGES_DIR
    md_dir = root / MD_DIR
    qc_dir = root / QC_DIR
    book = root / BOOK_NAME

    say("[1/4] 渲页 %s" % pdf)
    rendered = render.render_pdf(pdf, pages_dir, edge=cfg.page_edge, log=say)
    if rendered.written == 0 and rendered.skipped == 0:
        raise DataError("PDF 没有可渲染的页: %s" % pdf)

    say("[2/4] 整页解析 %d 页" % rendered.total)
    started = time.time()
    code = (parse_runner or _run_parse)(
        _parse_command(repo_root, pages_dir, md_dir),
        Path(repo_root),
        root / "parse.log",
    )
    if code != 0:
        raise PmocrError("整页解析失败（退出码 %d），看 %s" % (code, root / "parse.log"))

    runs_dir = _runs_dir(cfg)
    pages_json = find_latest_pages_json(runs_dir, started)
    if pages_json is None:
        raise PmocrError("解析没有产出 pages_json（%s 里没有新目录）" % runs_dir)

    say("[3/4] 公式复核 %s" % pages_json.name)
    layout = prepare_outputs(qc_dir)
    summary = (qc_service or _run_qc)(pages_json, pages_dir, layout, cfg)
    report.write_csv(summary.results, layout.csv_path)
    report.write_markdown(summary.results, layout.markdown_path, cfg.threshold)

    say("[4/4] 合并成稿")
    merged = merge.merge_pages(md_dir, book, title=title, subtitle=subtitle, note=note, skip=skip)

    if not keep_pages:
        _cleanup(pages_dir)
    counts = report.summarize(summary.results)
    return BookRun(
        pages=rendered.total,
        blocks=counts.total,
        review=counts.review,
        skipped_pages=summary.skipped_pages,
        pages_dir=pages_dir,
        qc_dir=qc_dir,
        book=merged.path,
    )


def _parse_command(repo_root: str | Path, pages_dir: Path, md_dir: Path) -> list[str]:
    script = Path(repo_root) / "scripts" / "ocr_parse.ps1"
    return ["pwsh", "-NoProfile", "-File", str(script),
            "-InputPath", str(pages_dir), "-Out", str(md_dir)]


def _run_parse(cmd: Sequence[str], cwd: Path, log_path: Path) -> int:
    script = Path(cmd[cmd.index("-File") + 1]) if "-File" in cmd else None
    if script is not None and not script.is_file():
        raise DataError("找不到解析脚本: %s" % script)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(list(cmd), cwd=str(cwd), stdout=handle, stderr=subprocess.STDOUT)
    return proc.returncode


def _run_qc(pages_json: Path, pages_dir: Path, layout: OutputLayout, cfg: Config) -> qc.RunSummary:
    return qc.run(discover_pages(pages_json, pages_dir), layout, cfg)


def _runs_dir(cfg: Config) -> Path:
    if not cfg.minicpm_root:
        raise DataError("没有配置 minicpm_root，无法定位 runs 目录（config.json 或 PMOCR_MINICPM_ROOT）")
    return Path(cfg.minicpm_root) / "runs"


def _cleanup(pages_dir: Path) -> None:
    if not pages_dir.is_dir():
        return
    for path in pages_dir.iterdir():
        path.unlink()
    pages_dir.rmdir()
