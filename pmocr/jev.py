"""Jev 打分客户端：送两张图 + 候选 LaTeX，拿 0–1 的一致性概率。

只做 HTTP 与重试，不做裁图、不管报告。重试策略：
  - 网络异常 / 5xx / 结果缺字段 → 退避重试（默认 2 次）
  - 4xx → 立即失败（参数错了，重试无意义）
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Config
from .errors import JevError

Question = dict
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class JevClient:
    url: str
    model: str
    timeout: float = 300.0
    retries: int = 2
    backoff: float = 1.5
    sleep: Sleeper = time.sleep  # 测试注入

    @classmethod
    def from_config(cls, cfg: Config) -> "JevClient":
        return cls(
            url=cfg.jev_url.rstrip("/") + "/v1/systemone",
            model=cfg.jev_model,
            timeout=cfg.jev_timeout,
            retries=cfg.jev_retries,
            backoff=cfg.jev_backoff,
        )

    def score(self, region_png: Path, tex: str, candidate_png: Path) -> float:
        """返回「候选与区域图一致」的概率。多次重试仍失败则抛 JevError。"""
        body = {
            "model": self.model,
            "state": tex,
            "images": [_b64(region_png), _b64(candidate_png)],
            "questions": {"consistency": {"type": "choice", "criteria": {"0": None, "1": None}}},
        }
        last_error = ""
        for attempt in range(self.retries + 1):
            try:
                return self._post(body)
            except _Retryable as exc:
                last_error = str(exc)
                if attempt < self.retries:
                    self.sleep(self.backoff * (2**attempt))
            except _Fatal as exc:
                raise JevError(str(exc)) from exc
        raise JevError("打分重试 %d 次仍失败: %s" % (self.retries, last_error))

    def _post(self, body: dict) -> float:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            detail = _read_error_body(exc)
            if exc.code >= 500:
                raise _Retryable("HTTP %d %s" % (exc.code, detail)) from exc
            raise _Fatal("HTTP %d %s" % (exc.code, detail)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _Retryable("连接失败: %s" % exc) from exc
        return _parse_score(payload)


class _Retryable(Exception):
    """可重试的失败：网络、5xx、返回体不合预期。"""


class _Fatal(Exception):
    """不可重试的失败：4xx，说明请求本身有问题。"""


def _parse_score(payload: bytes) -> float:
    try:
        data = json.loads(payload.decode("utf-8"))
        prob = data["answers"]["consistency"]["probabilities"]["1"]
    except (KeyError, TypeError, ValueError) as exc:
        raise _Retryable("返回体缺 answers.consistency.probabilities.1") from exc
    try:
        return float(prob)
    except (TypeError, ValueError) as exc:
        raise _Retryable("概率不是数字: %r" % (prob,)) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")[:200]
    except Exception:  # pragma: no cover - 尽力而为
        return ""


def _b64(path: Path) -> str:
    try:
        return base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except OSError as exc:
        raise JevError("读图失败: %s (%s)" % (path, exc)) from exc
