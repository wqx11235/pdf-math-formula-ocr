"""选择性验证门：用廉价特征决定「哪些块可以不送 jev 打分」。

理论依据（可直接引用的现成工作）：
  - Selective Classification for Deep Neural Networks, Geifman & El-Yaniv, NeurIPS 2017
    （arXiv:1705.08500）：允许模型弃权，用 coverage-risk 曲线描述取舍。
  - Conformal Risk Control, Angelopoulos et al. 2022（arXiv:2208.02814）：
    对任意单调损失给出期望风险上界，正是这里「被跳过块的漏检率」需要的保证。

本实现的硬约束：**没有校准数据就一块都不跳**。跳过区间由 Clopper–Pearson 精确上界
在置信度 1-δ 下限制漏检率 ≤ ε 才启用，因此不会让错误率上升（统计意义上）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .errors import DataError

DEFAULT_EPSILON = 0.03
DEFAULT_DELTA = 0.05
WEIGHTS = {"len": 1.0, "cmd": -0.5}


def features(tex: str) -> dict[str, float]:
    """廉价特征：只依赖候选 LaTeX 文本，不额外花钱。"""
    import re

    return {
        "len": float(len(tex)),
        "cmd": float(len(re.findall(r"\\[a-zA-Z]+", tex))),
    }


def raw_score(tex: str) -> float:
    """越大越像 OK（可直接送检？反过来：越大越像 OK → 跳过）。"""
    values = features(tex)
    return sum(WEIGHTS[name] * values[name] for name in WEIGHTS)


def binom_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    total = 0.0
    for i in range(0, k + 1):
        total += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return total


def clopper_pearson_upper(misses: int, n: int, delta: float) -> float:
    """漏检率 p 的单侧 (1-δ) 精确上界：解 P(X ≤ misses; n, p) = δ。"""
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
    """校准后的跳过规则：score ≥ cutoff 的块跳过 jev。"""

    cutoff: float
    skip_fraction: float
    epsilon: float
    delta: float
    n_calibration: int
    bound: float

    def skips(self, tex: str) -> bool:
        return raw_score(tex) >= self.cutoff

    def to_dict(self) -> dict:
        return {
            "cutoff": self.cutoff,
            "skip_fraction": self.skip_fraction,
            "epsilon": self.epsilon,
            "delta": self.delta,
            "n_calibration": self.n_calibration,
            "bound": self.bound,
            "weights": WEIGHTS,
            "note": "score>=cutoff 的块跳过 jev；bound 是跳过区间漏检率的单侧上界",
        }


def calibrate(scores: Sequence[float], truths: Sequence[int],
              epsilon: float = DEFAULT_EPSILON, delta: float = DEFAULT_DELTA) -> Gate:
    """在标注集上选「能跳多少」：从最像 OK 的一端往外扩，直到上界超过 ε。

    truths: 1 = 该块其实有问题（CHECK/错），0 = 没问题。
    """
    if len(scores) != len(truths):
        raise DataError("scores/truths 长度不一致")
    if not scores:
        raise DataError("校准集为空")
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    best = Gate(cutoff=float("inf"), skip_fraction=0.0, epsilon=epsilon, delta=delta,
                n_calibration=len(scores), bound=0.0)
    # 从最像 OK 的一端往外扩；一旦遇到「已知有问题」的块就停——跳过集合里绝不许含问题块。
    for k, index in enumerate(order, start=1):
        if truths[index]:
            break
        bound = clopper_pearson_upper(0, k, delta)
        if bound > epsilon:
            continue
        best = Gate(cutoff=scores[index], skip_fraction=k / len(scores), epsilon=epsilon,
                    delta=delta, n_calibration=len(scores), bound=bound)
    return best


def load(path: str | Path) -> Gate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Gate(cutoff=float(data["cutoff"]), skip_fraction=float(data["skip_fraction"]),
                epsilon=float(data["epsilon"]), delta=float(data["delta"]),
                n_calibration=int(data["n_calibration"]), bound=float(data["bound"]))


def save(gate: Gate, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(gate.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def coverage_risk(scores: Sequence[float], truths: Sequence[int], cutoff: float) -> tuple[int, int]:
    """返回 (跳过块数, 其中真有问题数)，用于报告实测覆盖-风险。"""
    skipped = missed = 0
    for score, truth in zip(scores, truths):
        if score >= cutoff:
            skipped += 1
            missed += int(truth)
    return skipped, missed


__all__ = ["Gate", "calibrate", "coverage_risk", "features", "raw_score",
           "clopper_pearson_upper", "binom_cdf", "load", "save"]
