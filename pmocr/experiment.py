"""对照组实验：量出「不做复核 / 只做编译检查 / 编译 + Jev」的差别。

三臂的定义（同一批块、同一份结果 CSV）：

  A  无复核        全部直接出版；没有信号，错的一起出
  B  只做编译检查  RENDER_FAIL 拦下（编不过本身就是硬错误），其余放行
  C  编译 + Jev    OK 放行，CHECK / RENDER_FAIL / SCORE_ERR 全进人工

只有 C 的 CHECK 需要「可能错」的判断；A 与 B 都没有这种能力。
人工成本 = 各臂的 review 块数；检出能力只能在有标签的子集上量。

标签按 (页, 块) 匹配。合并多本书的 CSV 时同页名会撞车，因此一条标签
命中多行会直接报错，而不是悄悄算错。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .errors import DataError
from .qc import BlockResult, VERDICT_OK, VERDICT_RENDER_FAIL, VERDICT_SCORE_ERR
from .report import load_results, summarize

TRUTH_OK = "ok"
TRUTH_WRONG = "wrong"


@dataclass(frozen=True)
class Arm:
    key: str
    name: str
    review: int
    auto_pass: int
    catches_invalid_latex: bool
    can_flag_low_confidence: bool

    @property
    def review_share(self) -> float:
        total = self.review + self.auto_pass
        return self.review / total if total else 0.0


@dataclass(frozen=True)
class LabelMetrics:
    labeled: int
    labeled_ok: int
    labeled_wrong: int
    caught: int
    missed: int
    false_check: int
    unscored_ok: int

    @property
    def recall(self) -> float | None:
        return self.caught / self.labeled_wrong if self.labeled_wrong else None

    @property
    def precision(self) -> float | None:
        flagged = self.caught + self.false_check
        return self.caught / flagged if flagged else None


@dataclass(frozen=True)
class SweepRow:
    threshold: float
    check: int
    review: int
    review_share: float
    caught: int
    missed: int
    false_check: int


def load_labels(path: str | Path) -> dict[tuple[str, int], str]:
    """标签 CSV：page,block,truth（truth ∈ {ok, wrong}）。"""
    path = Path(path)
    if not path.is_file():
        raise DataError("标签文件不存在: %s" % path)
    labels: dict[tuple[str, int], str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"page", "block", "truth"} <= set(reader.fieldnames or ()):
            raise DataError("标签 CSV 需要 page,block,truth 三列")
        for row in reader:
            truth = (row["truth"] or "").strip().lower()
            if truth not in (TRUTH_OK, TRUTH_WRONG):
                raise DataError("truth 只能是 ok / wrong，收到 %r" % row["truth"])
            labels[(row["page"].strip(), int(row["block"]))] = truth
    return labels


def arms(results: Sequence[BlockResult]) -> list[Arm]:
    counts = summarize(results)
    return [
        Arm("A", "无复核（基线）", review=0, auto_pass=counts.total,
            catches_invalid_latex=False, can_flag_low_confidence=False),
        Arm("B", "只做 LaTeX 编译检查", review=counts.render_fail,
            auto_pass=counts.total - counts.render_fail,
            catches_invalid_latex=True, can_flag_low_confidence=False),
        Arm("C", "编译检查 + Jev 打分", review=counts.review, auto_pass=counts.ok,
            catches_invalid_latex=True, can_flag_low_confidence=True),
    ]


def label_metrics(
    results: Iterable[BlockResult],
    labels: dict[tuple[str, int], str],
    threshold: float | None = None,
) -> LabelMetrics:
    """在有人工标签的子集上算检出与误判。threshold=None 用各块自带 verdict。

    CHECK 是「判成可疑」，RENDER_FAIL / SCORE_ERR 是「没给出可靠信号」。
    后者会进人工清单，但不是误判错——分开统计，否则会把技术故障说成准确率问题。
    """
    hits: Counter[tuple[str, int]] = Counter()
    caught = missed = false_check = unscored_ok = 0
    labeled = labeled_ok = labeled_wrong = 0

    for item in results:
        key = (item.page_id, item.index)
        truth = labels.get(key)
        if truth is None:
            continue
        hits[key] += 1
        labeled += 1
        needs_review, judged_suspicious = _classify(item, threshold)
        if truth == TRUTH_WRONG:
            labeled_wrong += 1
            if judged_suspicious:
                caught += 1
            elif needs_review:
                caught += 1  # 编不过 / 没打分也算拦下，不能放过
            else:
                missed += 1
        else:
            labeled_ok += 1
            if judged_suspicious:
                false_check += 1
            elif needs_review:
                unscored_ok += 1

    duplicated = [key for key, count in hits.items() if count > 1]
    if duplicated:
        raise DataError(
            "标签 %r 命中多行：这份 CSV 应该是多本书合并的，标签只对单本书有效" % (duplicated[0],)
        )
    return LabelMetrics(labeled, labeled_ok, labeled_wrong, caught, missed, false_check, unscored_ok)


def sweep(
    results: Sequence[BlockResult],
    labels: dict[tuple[str, int], str],
    thresholds: Sequence[float],
) -> list[SweepRow]:
    counts = summarize(results)
    rows: list[SweepRow] = []
    for threshold in thresholds:
        check = sum(1 for item in results if _suspicious(item, threshold))
        metrics = label_metrics(results, labels, threshold)
        review = check + counts.render_fail + counts.score_err
        rows.append(
            SweepRow(
                threshold=round(threshold, 2),
                check=check,
                review=review,
                review_share=review / counts.total if counts.total else 0.0,
                caught=metrics.caught,
                missed=metrics.missed,
                false_check=metrics.false_check,
            )
        )
    return rows


def render_markdown(
    results: Sequence[BlockResult],
    labels: dict[tuple[str, int], str],
    thresholds: Sequence[float],
    source: str = "",
) -> str:
    counts = summarize(results)
    metrics = label_metrics(results, labels)
    lines = [
        "# 对照组实验报告",
        "",
        "数据源：`%s`，共 %d 个公式块。" % (source or "-", counts.total),
        "",
        "## 一、分流规模",
        "",
        "| 判定 | 块数 | 占比 |",
        "|---|---|---|",
        _ratio_line("OK 直接通过", counts.ok, counts.total),
        _ratio_line("CHECK 低分", counts.check, counts.total),
        _ratio_line("RENDER_FAIL 编不过", counts.render_fail, counts.total),
        _ratio_line("SCORE_ERR 没打分", counts.score_err, counts.total),
        "",
        "## 二、三臂对比（人工成本 / 能力）",
        "",
        "| 臂 | 做法 | 人工必看 | 占比 | 拦编不过 | 能标「可能错」 |",
        "|---|---|---|---|---|---|",
    ]
    for arm in arms(results):
        lines.append(
            "| %s | %s | %d | %.1f%% | %s | %s |"
            % (
                arm.key,
                arm.name,
                arm.review,
                arm.review_share * 100,
                "是" if arm.catches_invalid_latex else "否",
                "是" if arm.can_flag_low_confidence else "否",
            )
        )
    lines += [
        "",
        "## 三、有标签子集上的表现",
        "",
        "标签块 %d（人工确认错误 %d）。" % (metrics.labeled, metrics.labeled_wrong),
        "",
        "| 指标 | 值 |",
        "|---|---|",
        "| 标签块数 | %d |" % metrics.labeled,
        "| 其中真错 | %d |" % metrics.labeled_wrong,
        "| 真错被拦下 | %d |" % metrics.caught,
        "| 真错漏检（判成 OK） | %d |" % metrics.missed,
        "| 真对被标为 CHECK | %d |" % metrics.false_check,
        "| 真对但没打分（需核对） | %d |" % metrics.unscored_ok,
        "| 召回 | %s |" % _pct(metrics.recall),
        "| 精确率（只算 CHECK） | %s |" % _pct(metrics.precision),
        "",
        "> 「真对但没打分」进人工是成本不是误判；召回/精确率在标签不足时不成立，显示为「-」。",
        "",
        "## 四、阈值扫描（人工成本 vs 检出）",
        "",
        "| 阈值 | CHECK | 待复核 | 占比 | 拦下 | 漏检 | 误标 CHECK |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in sweep(results, labels, thresholds):
        lines.append(
            "| %.2f | %d | %d | %.1f%% | %d | %d | %d |"
            % (row.threshold, row.check, row.review, row.review_share * 100,
               row.caught, row.missed, row.false_check)
        )
    lines += [
        "",
        "阈值只影响 CHECK 与 OK 的切分；RENDER_FAIL / SCORE_ERR 不受阈值影响。",
        "",
    ]
    return "\n".join(lines)


def write_json(
    path: str | Path,
    results: Sequence[BlockResult],
    labels: dict[tuple[str, int], str],
    thresholds: Sequence[float],
) -> Path:
    counts = summarize(results)
    metrics = label_metrics(results, labels)
    payload = {
        "counts": counts.__dict__,
        "arms": [arm.__dict__ | {"review_share": arm.review_share} for arm in arms(results)],
        "labels": metrics.__dict__ | {"recall": metrics.recall, "precision": metrics.precision},
        "sweep": [row.__dict__ for row in sweep(results, labels, thresholds)],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pmocr.experiment", description="对照组实验：复核的三臂对比与阈值扫描")
    parser.add_argument("--csv", required=True, help="formula_qc.csv（单本书的一次复核）")
    parser.add_argument("--labels", help="标签 CSV（page,block,truth），只对单本书有效")
    parser.add_argument("--sweep", default="0.3:0.95:0.05", help="扫描区间 from:to:step")
    parser.add_argument("--md", help="输出 Markdown 路径")
    parser.add_argument("--json", help="输出 JSON 路径")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results = load_results(args.csv)
    labels = load_labels(args.labels) if args.labels else {}
    thresholds = _parse_range(args.sweep)
    markdown = render_markdown(results, labels, thresholds, source=args.csv)
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(markdown, encoding="utf-8")
        print("报告:", args.md)
    else:
        print(markdown)
    if args.json:
        print("JSON:", write_json(args.json, results, labels, thresholds))
    return 0


def _classify(item: BlockResult, threshold: float | None) -> tuple[bool, bool]:
    """返回 (是否需要人工, 是否被判成可疑)。"""
    return _needs_review(item, threshold), _suspicious(item, threshold)


def _suspicious(item: BlockResult, threshold: float | None) -> bool:
    """是否被判成「可能错」。没打分的 CHECK 也算可疑（否则会从清单里消失）。"""
    if item.verdict in (VERDICT_SCORE_ERR, VERDICT_RENDER_FAIL):
        return False
    if item.score is None:
        return item.verdict != VERDICT_OK
    if threshold is None:
        return item.verdict != VERDICT_OK
    return item.score < threshold


def _needs_review(item: BlockResult, threshold: float | None) -> bool:
    if item.verdict in (VERDICT_SCORE_ERR, VERDICT_RENDER_FAIL):
        return True
    return _suspicious(item, threshold)


def _parse_range(spec: str) -> list[float]:
    try:
        start, stop, step = (float(part) for part in spec.split(":"))
    except ValueError as exc:
        raise SystemExit("--sweep 需要 from:to:step，例如 0.3:0.95:0.05") from exc
    if step <= 0 or stop < start:
        raise SystemExit("--sweep 区间非法")
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 4))
        current += step
    return values


def _ratio_line(label: str, value: int, total: int) -> str:
    share = (value / total * 100) if total else 0.0
    return "| %s | %d | %.1f%% |" % (label, value, share)


def _pct(value: float | None) -> str:
    return "-" if value is None else "%.1f%%" % (value * 100)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
