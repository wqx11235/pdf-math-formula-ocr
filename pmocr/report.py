"""把复核结果写成 CSV 与 Markdown 报告（并读回 CSV 供实验比对）。

报告分两节，因为「低分」和「没打分」要人工做的事完全不同：
  CHECK       低分，可能错 —— 带着「找错」的心态看
  RENDER_FAIL / SCORE_ERR  没拿到可靠信号 —— 核对而非纠错
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .errors import DataError
from .qc import BlockResult, NON_OK, VERDICT_CHECK, VERDICT_OK, VERDICT_RENDER_FAIL, VERDICT_SCORE_ERR

CSV_FIELDS = ("page", "block", "bbox", "score", "verdict", "tex", "note")
_UNSCORED = (VERDICT_RENDER_FAIL, VERDICT_SCORE_ERR)


@dataclass(frozen=True)
class Counts:
    total: int
    ok: int
    check: int
    render_fail: int
    score_err: int

    @property
    def unscored(self) -> int:
        return self.render_fail + self.score_err

    @property
    def review(self) -> int:
        return self.total - self.ok

    @property
    def review_share(self) -> float:
        return self.review / self.total if self.total else 0.0


def summarize(results: Iterable[BlockResult]) -> Counts:
    tally = Counter(item.verdict for item in results)
    return Counts(
        total=sum(tally.values()),
        ok=tally[VERDICT_OK],
        check=tally[VERDICT_CHECK],
        render_fail=tally[VERDICT_RENDER_FAIL],
        score_err=tally[VERDICT_SCORE_ERR],
    )


def write_csv(results: Sequence[BlockResult], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for item in results:
            writer.writerow(
                {
                    "page": item.page_id,
                    "block": item.index,
                    "bbox": list(item.bbox),
                    "score": "" if item.score is None else item.score,
                    "verdict": item.verdict,
                    "tex": item.tex,
                    "note": item.note,
                }
            )
    return path


def write_markdown(results: Sequence[BlockResult], path: Path, threshold: float) -> Path:
    counts = summarize(results)
    lines = [
        "# 公式复核 · 待人工确认",
        "",
        "阈值 %.2f。共 %d 个公式块：自动通过 %d，待复核 %d（低分 %d，未打分 %d）。"
        % (threshold, counts.total, counts.ok, counts.review, counts.check, counts.unscored),
        "",
        "> 低分 = 可能错，优先看；未打分 = 服务失败，未打分 ≠ 错，是核对不是纠错。",
        "",
    ]
    lines += _section("低分 · 可能错（优先看）", [r for r in results if r.verdict == VERDICT_CHECK])
    lines += _section("未打分 · 需核对（不是纠错）", [r for r in results if r.verdict in _UNSCORED])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_results(path: str | Path) -> list[BlockResult]:
    """读回 write_csv 的产物（也兼容历史版本：bbox 为列表字面量）。"""
    path = Path(path)
    if not path.is_file():
        raise DataError("结果 CSV 不存在: %s" % path)
    results: list[BlockResult] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            results.append(
                BlockResult(
                    page_id=row["page"],
                    index=int(row["block"]),
                    bbox=_parse_bbox(row.get("bbox", "")),
                    tex=row.get("tex", ""),
                    verdict=row["verdict"],
                    score=_parse_score(row.get("score", "")),
                    note=row.get("note", ""),
                )
            )
    return results


def _section(title: str, items: Sequence[BlockResult]) -> list[str]:
    lines = ["## %s（%d）" % (title, len(items)), ""]
    if not items:
        lines += ["无。", ""]
        return lines
    fence = "```"
    for item in items:
        score = "-" if item.score is None else "%.4f" % item.score
        lines.append("### %s block %d  ·  %s  ·  score=%s" % (item.page_id, item.index, item.verdict, score))
        lines.append("")
        lines.append(fence + "latex")
        lines.append(item.tex)
        lines.append(fence)
        lines.append("")
        if item.note:
            lines.append("说明：%s" % item.note)
            lines.append("")
    return lines


def _parse_score(raw: str) -> float | None:
    raw = (raw or "").strip()
    return None if not raw else float(raw)


def _parse_bbox(raw: str) -> tuple[float, float, float, float]:
    text = (raw or "").strip().strip("[]")
    parts = [p for p in text.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 4:
        raise DataError("bbox 无法解析: %r" % raw)
    x0, y0, x1, y1 = (float(p) for p in parts)
    return (x0, y0, x1, y1)


__all__ = [
    "Counts",
    "summarize",
    "write_csv",
    "write_markdown",
    "load_results",
    "NON_OK",
]
