"""复核服务：编排「裁图 → 渲染 → 打分」，产出逐块结论。

这一层只做顺序与错误分流，具体动作都在 geometry / latex / jev / paths 里。
四个判定：

  OK           分数 ≥ 阈值，可直接信
  CHECK        分数低，可能错，优先人工看
  RENDER_FAIL  候选 LaTeX 编不出 PDF（编不过本身就是强信号）
  SCORE_ERR    服务失败没打分，未打分 ≠ 错，需核对而非纠错
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import latex
from .config import Config
from .gate import Gate
from .errors import JevError, PmocrError
from .geometry import Size, fit_max_side, scale_bbox
from .jev import JevClient
from .ocr import FormulaBlock, load_page
from .paths import OutputLayout, PageRef

VERDICT_OK = "OK"
VERDICT_CHECK = "CHECK"
VERDICT_RENDER_FAIL = "RENDER_FAIL"
VERDICT_SCORE_ERR = "SCORE_ERR"


@dataclass(frozen=True)
class BlockResult:
    page_id: str
    index: int
    bbox: tuple[float, float, float, float]
    tex: str
    verdict: str
    score: float | None = None
    note: str = ""

    @property
    def passed_automatically(self) -> bool:
        return self.verdict == VERDICT_OK


@dataclass(frozen=True)
class RunSummary:
    results: tuple[BlockResult, ...]
    skipped_pages: tuple[str, ...]

    def count(self, verdict: str) -> int:
        return sum(1 for item in self.results if item.verdict == verdict)

    @property
    def review_needed(self) -> int:
        return sum(1 for item in self.results if not item.passed_automatically)


def run(
    pages: Sequence[PageRef],
    layout: OutputLayout,
    cfg: Config,
    *,
    client: JevClient | None = None,
    renderer: Callable[..., latex.RenderResult] = latex.render,
    gate: Gate | None = None,
    log: Callable[[str], None] | None = None,
) -> RunSummary:
    """逐页逐块复核。单块失败只记账，不中断整批。

    裁图在主线程做（PIL 图像不跨线程共享），渲染与打分按 qc_workers 并发——
    xelatex 是 CPU 串行的大头，并发后复核段能砍掉三分之一以上。
    """
    say = log or (lambda message: print(message, file=sys.stderr))
    jev = client or JevClient.from_config(cfg)
    skipped: list[str] = []
    pending: list[tuple[int, FormulaBlock, Path]] = []
    slots: list[BlockResult | None] = []

    for ref in pages:
        if not ref.usable:
            skipped.append(ref.page_id)
            say("[skip] 缺页面图 %s" % ref.page_id)
            continue
        try:
            page = load_page(ref)
        except PmocrError as exc:
            skipped.append(ref.page_id)
            say("[skip] %s 块级数据不可用: %s" % (ref.page_id, exc))
            continue

        with closing(_open_image(ref.image_path)) as image:
            page_size = Size(image.width, image.height)
            for block in page.blocks:
                try:
                    region = _save_region(block, image, page_size, page.image_size, layout, cfg)
                except (PmocrError, OSError, ValueError) as exc:
                    slots.append(_result(block, VERDICT_RENDER_FAIL, note="裁图失败: %s" % exc))
                    continue
                pending.append((len(slots), block, region))
                slots.append(None)
        say("[done] %s 公式块 %d" % (ref.page_id, len(page.blocks)))

    if cfg.qc_workers <= 1:
        for index, block, region in pending:
            slots[index] = evaluate_region(block, region, layout, cfg, jev, renderer, gate)
    else:
        with ThreadPoolExecutor(max_workers=cfg.qc_workers) as pool:
            futures = {
                index: pool.submit(evaluate_region, block, region, layout, cfg, jev, renderer, gate)
                for index, block, region in pending
            }
            for index, future in futures.items():
                slots[index] = future.result()

    return RunSummary(results=tuple(item for item in slots if item is not None), skipped_pages=tuple(skipped))


def evaluate_region(
    block: FormulaBlock,
    region: Path,
    layout: OutputLayout,
    cfg: Config,
    client,
    renderer: Callable[..., latex.RenderResult] = latex.render,
    gate: Gate | None = None,
) -> BlockResult:
    """块已裁好：渲染 → 打分 → 判定。渲染与打分都可以并发调用。"""
    rendered = renderer(block.tex, layout.render_dir, _render_name(block), cfg)
    if not rendered.ok:
        return _result(block, VERDICT_RENDER_FAIL, note=rendered.error)

    if gate is not None and gate.skips(block.tex):
        # 校准过的门认为这块足够安全：不送 jev，直接放行（note 里留痕）
        return _result(block, VERDICT_OK, note="gate-skip skips>=%.2f" % gate.cutoff)

    candidate = _shrink(rendered.png, cfg.max_image_side)
    try:
        score = client.score(region, block.tex, candidate)
    except JevError as exc:
        # jev 对过宽/多行 array 的图会 500；原样重试救不回来。
        # 实测把两张图降到 800px 重发，12 个 SCORE_ERR 里能救回 9 个。
        score = _retry_downscaled(region, block.tex, candidate, layout, cfg, client)
        if score is None:
            return _result(block, VERDICT_SCORE_ERR, note=str(exc)[:200])

    stored = round(score, 4)
    verdict = VERDICT_OK if stored >= cfg.threshold else VERDICT_CHECK
    return _result(block, verdict, score=stored)


def evaluate_block(
    *,
    block: FormulaBlock,
    page_image,
    page_size: Size,
    source_size: Size,
    layout: OutputLayout,
    cfg: Config,
    client,
    renderer: Callable[..., latex.RenderResult] = latex.render,
) -> BlockResult:
    """单块入口（裁图 + 渲染 + 打分），保留给直接调用与单测。"""
    try:
        region = _save_region(block, page_image, page_size, source_size, layout, cfg)
    except (PmocrError, OSError, ValueError) as exc:
        return _result(block, VERDICT_RENDER_FAIL, note="裁图失败: %s" % exc)
    return evaluate_region(block, region, layout, cfg, client, renderer)


def _retry_downscaled(
    region: Path,
    tex: str,
    candidate: Path,
    layout: OutputLayout,
    cfg: Config,
    client,
) -> float | None:
    """把两张图等比缩到 retry_max_side 再打一次分；仍失败返回 None。"""
    from PIL import Image

    def smaller(source: Path, name: str) -> Path:
        target = layout.render_dir / name
        with Image.open(source) as img:
            img = img.convert("RGB")
            scale = min(1.0, cfg.retry_max_side / max(img.width, img.height))
            if scale < 1.0:
                img = img.resize(
                    (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                    Image.LANCZOS,
                )
            img.save(target, format="JPEG", quality=92)
        return target

    small_region = smaller(region, region.stem + "_retry.jpg")
    small_candidate = smaller(candidate, candidate.stem + "_retry.jpg")
    try:
        return client.score(small_region, tex, small_candidate)
    except JevError:
        return None


def _result(
    block: FormulaBlock,
    verdict: str,
    *,
    score: float | None = None,
    note: str = "",
) -> BlockResult:
    return BlockResult(
        page_id=block.page_id,
        index=block.index,
        bbox=block.bbox,
        tex=block.tex,
        verdict=verdict,
        score=score,
        note=note,
    )


def _render_name(block: FormulaBlock) -> str:
    return "%s_b%d" % (block.page_id, block.index)


def _save_region(
    block: FormulaBlock,
    page_image,
    page_size: Size,
    source_size: Size,
    layout: OutputLayout,
    cfg: Config,
) -> Path:
    box = scale_bbox(block.bbox, source_size, page_size, cfg.crop_padding)
    region = page_image.crop(box)
    if region.width <= 0 or region.height <= 0:
        raise PmocrError("裁出空图")
    region = _resize(region, cfg.max_image_side)
    path = layout.crop_path(block.page_id, block.index)
    region.save(path)
    return path


def _shrink(path: Path, max_side: int) -> Path:
    """Jev 对超宽图会直接 500，渲染图也要限宽（多行 array 会渲得很宽）。"""
    from PIL import Image

    with Image.open(path) as image:
        target = fit_max_side(Size(image.width, image.height), max_side)
        if target.width == image.width and target.height == image.height:
            return path
        resized = image.resize((target.width, target.height), Image.LANCZOS)
    resized.save(path)
    return path


def _resize(image, max_side: int):
    target = fit_max_side(Size(image.width, image.height), max_side)
    if target.width == image.width and target.height == image.height:
        return image
    from PIL import Image

    return image.resize((target.width, target.height), Image.LANCZOS)


def _open_image(path: Path | None):
    from PIL import Image

    if path is None:  # pragma: no cover - run() 已过滤
        raise PmocrError("页面图缺失")
    image = Image.open(path)
    image.load()
    return image



