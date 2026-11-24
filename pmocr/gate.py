"""选择性验证门：用廉价特征决定「哪些块可以不送 jev 打分」。

理论依据（现成工作，不是自创）：
  - Selective Classification for Deep Neural Networks（Geifman & El-Yaniv, 2017,
    arXiv:1705.08500）：允许弃权，按 coverage-risk 曲线取舍。
  - Conformal Risk Control（Angelopoulos et al., 2022, arXiv:2208.02814，
    代码 https://github.com/aangelopoulos/conformal-risk）：对单调损失给期望风险上界。

本实现的安全规则：
  1. 从「最像 OK」端往外扩跳过集合，**遇到第一个已知问题块立即停**；
  2. 跳过集合的漏检率用 Clopper–Pearson 单侧精确上界控制，只有 ≤ ε 才生效；
  3. 没有校准数据时 cutfoff=+inf，一块都不跳（与现状完全一致）。

CLI:
  python -m pmocr.gate calibrate --labels labels.csv --out gate.json --epsilon 0.10
  python -m pmocr.gate shadow --csv dataset.csv --epsilon 0.10 [--by-book]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .errors import DataError

DEFAULT_EPSILON = 0.05
DEFAULT_DELTA = 0.05
WEIGHTS = {"len": 1.0, "cmd": -0.5}


def features(tex: str) -> dict[str, float]:
    return {
        "len": float(len(tex)),
        "cmd": float(len(re.findall(r"\\[a-zA-Z]+", tex))),
    }


def binom_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(k + 1))


def clopper_pearson_upper(misses: int, n: int, delta: float) -> float:
    """漏检率单侧 (1-δ) 精确上界：解 P(X ≤ misses; n, p) = δ。"""
    if n <= 0:
        return 1.0
    if misses >= n:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(80):
        mid = (low + high) / 2
        if binom_cdf(misses, n, mid) > delta:
            low = mid
        else:
            high = mid
    return high


@dataclass(frozen=True)
class Gate:
    cutoff: float
    mean: dict[str, float]
    std: dict[str, float]
    skip_fraction: float
    epsilon: float
    delta: float
    n_calibration: int
    bound: float

    def score(self, tex: str) -> float:
        values = features(tex)
        total = 0.0
        for name, weight in WEIGHTS.items():
            sigma = self.std.get(name) or 1.0
            total += weight * (values[name] - self.mean.get(name, 0.0)) / sigma
        return total

    def skips(self, tex: str) -> bool:
        return self.score(tex) >= self.cutoff

    def to_dict(self) -> dict:
        return {
            "cutoff": self.cutoff,
            "mean": self.mean,
            "std": self.std,
            "skip_fraction": self.skip_fraction,
            "epsilon": self.epsilon,
            "delta": self.delta,
            "n_calibration": self.n_calibration,
            "bound": self.bound,
            "weights": WEIGHTS,
            "note": "score>=cutoff 的块跳过 jev；bound 为跳过区间漏检率单侧上界",
        }


EMPTY = Gate(cutoff=float("inf"), mean={}, std={}, skip_fraction=0.0,
             epsilon=DEFAULT_EPSILON, delta=DEFAULT_DELTA, n_calibration=0, bound=0.0)


def _normalizer(texs: Sequence[str]) -> tuple[dict[str, float], dict[str, float]]:
    values = [features(t) for t in texs]
    mean, std = {}, {}
    for name in WEIGHTS:
        column = [v[name] for v in values]
        mu = sum(column) / len(column)
        var = sum((x - mu) ** 2 for x in column) / len(column)
        mean[name] = mu
        std[name] = math.sqrt(var) or 1.0
    return mean, std


def calibrate(texs: Sequence[str], truths: Sequence[int],
              epsilon: float = DEFAULT_EPSILON, delta: float = DEFAULT_DELTA) -> Gate:
    """truths: 1 = 该块其实有问题。返回能安全跳过的门（可能一块都不能跳）。"""
    if len(texs) != len(truths):
        raise DataError("texs/truths 长度不一致")
    if not texs:
        raise DataError("校准集为空")
    mean, std = _normalizer(texs)
    probe = Gate(cutoff=float("inf"), mean=mean, std=std, skip_fraction=0.0,
                 epsilon=epsilon, delta=delta, n_calibration=len(texs), bound=0.0)
    order = sorted(range(len(texs)), key=lambda i: probe.score(texs[i]), reverse=True)
    best = probe
    for k, index in enumerate(order, start=1):
        if truths[index]:
            break
        bound = clopper_pearson_upper(0, k, delta)
        if bound > epsilon:
            continue
        best = Gate(cutoff=probe.score(texs[index]), mean=mean, std=std,
                    skip_fraction=k / len(texs), epsilon=epsilon, delta=delta,
                    n_calibration=len(texs), bound=bound)
    return best


def load(path: str | Path) -> Gate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Gate(cutoff=float(data["cutoff"]), mean={k: float(v) for k, v in data["mean"].items()},
                std={k: float(v) for k, v in data["std"].items()},
                skip_fraction=float(data["skip_fraction"]), epsilon=float(data["epsilon"]),
                delta=float(data["delta"]), n_calibration=int(data["n_calibration"]),
                bound=float(data["bound"]))


def save(gate: Gate, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(gate.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def coverage_risk(texs: Sequence[str], truths: Sequence[int], gate: Gate) -> tuple[int, int]:
    skipped = missed = 0
    for tex, truth in zip(texs, truths):
        if gate.skips(tex):
            skipped += 1
            missed += int(truth)
    return skipped, missed


def shadow_report(rows: Iterable[dict], epsilon: float, delta: float = DEFAULT_DELTA,
                  by_book: bool = False) -> dict:
    """影子模式：只用已有 QC 结果推演「本来能跳多少、会漏多少」，不改任何判定。"""
    items = [r for r in rows if r["verdict"] in ("OK", "CHECK")]
    if not items:
        raise DataError("没有可用的 OK/CHECK 行")
    groups = {}
    for row in items:
        key = row.get("book", "") if by_book else "ALL"
        groups.setdefault(key, []).append(row)
    result = {"epsilon": epsilon, "delta": delta, "by_book": by_book, "groups": []}
    for key, group in sorted(groups.items()):
        texs = [r["tex"] for r in group]
        truths = [1 if r["verdict"] == "CHECK" else 0 for r in group]
        gate = calibrate(texs, truths, epsilon=epsilon, delta=delta)
        skipped, missed = coverage_risk(texs, truths, gate)
        result["groups"].append({
            "book": key, "n": len(group), "positives": sum(truths),
            "cutoff": gate.cutoff, "skip": skipped, "skip_fraction": round(gate.skip_fraction, 3),
            "missed": missed, "bound": gate.bound,
        })
    return result


def render_shadow(report: dict) -> str:
    lines = ["ε=%.2f δ=%.2f 校准覆盖 / 实测（影子模式，不改判定）" % (report["epsilon"], report["delta"]),
             "%-8s %5s %5s %6s %8s %6s %6s" % ("book", "n", "正例", "跳过", "占比", "漏检", "上界")]
    for g in report["groups"]:
        lines.append("%-8s %5d %5d %6d %7.0f%% %6d %6.3f"
                     % (g["book"], g["n"], g["positives"], g["skip"],
                        100 * g["skip_fraction"], g["missed"], g["bound"]))
    total_n = sum(g["n"] for g in report["groups"])
    total_skip = sum(g["skip"] for g in report["groups"])
    total_miss = sum(g["missed"] for g in report["groups"])
    lines.append("合计：n=%d 跳过=%d（%.1f%%）漏检=%d"
                 % (total_n, total_skip, 100 * total_skip / total_n if total_n else 0, total_miss))
    return "\n".join(lines)


def _load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pmocr.gate", description="选择性验证门：校准与影子评估")
    sub = parser.add_subparsers(dest="command", required=True)

    cal = sub.add_parser("calibrate", help="用人工标签校准并写出 gate.json")
    cal.add_argument("--labels", required=True, help="labels.csv（含 truth: ok/wrong）")
    cal.add_argument("--out", required=True, help="输出 gate.json")
    cal.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    cal.add_argument("--delta", type=float, default=DEFAULT_DELTA)

    shadow = sub.add_parser("shadow", help="在已有 QC 结果上推演跳过量与漏检（不改判定）")
    shadow.add_argument("--csv", required=True, help="formula_qc.csv / dataset.csv")
    shadow.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    shadow.add_argument("--delta", type=float, default=DEFAULT_DELTA)
    shadow.add_argument("--by-book", action="store_true", help="按书分别校准（留出评估用）")

    args = parser.parse_args(argv)
    if args.command == "calibrate":
        rows = [r for r in _load_rows(Path(args.labels)) if (r.get("truth") or "").strip()]
        truth = [(r.get("truth") or "").strip().lower() == "wrong" for r in rows]
        if not rows:
            raise SystemExit("labels.csv 里没有填好的 truth")
        gate = calibrate([r["tex"] for r in rows], [int(t) for t in truth],
                         epsilon=args.epsilon, delta=args.delta)
        path = save(gate, args.out)
        print("校准完成：n=%d 跳过比例=%.1f%% 上界=%.3f -> %s"
              % (gate.n_calibration, 100 * gate.skip_fraction, gate.bound, path))
        return 0

    report = shadow_report(_load_rows(Path(args.csv)), args.epsilon, args.delta, args.by_book)
    print(render_shadow(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
