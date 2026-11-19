"""集中配置：默认值 < JSON 文件 < 环境变量 < 命令行。

源码里不再出现任何绝对路径、端口或模型名。换机器只需改 JSON 或环境变量：

    $env:PMOCR_JEV_URL = 'http://127.0.0.1:18499'
    python -m pmocr.cli --config config/config.json ...

未知键会被拒绝（``ConfigError``），避免拼错配置却静默生效。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping

from .errors import ConfigError

ENV_PREFIX = "PMOCR_"


@dataclass(frozen=True)
class Config:
    """复核流程的可调项。全部带默认值，可只覆盖关心的几项。"""

    # --- Jev 打分服务 ---
    jev_url: str = "http://127.0.0.1:18499"
    jev_model: str = "jev"
    jev_timeout: float = 300.0
    jev_retries: int = 2
    jev_backoff: float = 1.5

    # --- 判定 ---
    threshold: float = 0.6

    # --- 图像与渲染 ---
    max_image_side: int = 1600
    crop_padding: int = 8
    render_dpi: int = 300
    render_timeout: float = 120.0
    tex_bin_dir: str = ""

    # --- 运行环境 ---
    temp_dir: str = ""

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "Config":
        """按 默认 < 文件 < 环境 < overrides 的顺序合成配置。"""
        cfg = cls()
        if path is not None:
            cfg = cfg.merge_json(Path(path))
        cfg = cfg.merge_env(os.environ if environ is None else environ)
        if overrides:
            cfg = cfg.merge({k: v for k, v in overrides.items() if v is not None})
        cfg.validate()
        return cfg

    def merge_json(self, path: Path) -> "Config":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError("找不到配置文件: %s" % path) from exc
        except json.JSONDecodeError as exc:
            raise ConfigError("配置文件不是合法 JSON: %s (%s)" % (path, exc)) from exc
        if not isinstance(raw, dict):
            raise ConfigError("配置文件顶层必须是对象: %s" % path)
        return self.merge(raw)

    def merge_env(self, environ: Mapping[str, str]) -> "Config":
        picked = {
            name: environ[ENV_PREFIX + name.upper()]
            for name in self.field_names()
            if ENV_PREFIX + name.upper() in environ
        }
        return self.merge(picked)

    def merge(self, values: Mapping[str, Any]) -> "Config":
        """覆盖若干字段；键名未知或类型不可转换时报 ConfigError。"""
        known = set(self.field_names())
        unknown = sorted(set(values) - known)
        if unknown:
            raise ConfigError("未知配置项: %s（可用项: %s）" % (", ".join(unknown), ", ".join(sorted(known))))
        changes = {name: _coerce(name, values[name], self) for name in values}
        return replace(self, **changes) if changes else self

    def validate(self) -> None:
        if not 0.0 < self.threshold < 1.0:
            raise ConfigError("threshold 必须在 (0, 1) 之间，当前 %r" % self.threshold)
        for name in ("max_image_side", "render_dpi", "jev_retries"):
            if getattr(self, name) <= 0:
                raise ConfigError("%s 必须为正整数，当前 %r" % (name, getattr(self, name)))
        if self.crop_padding < 0:
            raise ConfigError("crop_padding 不能为负")
        if not self.jev_url.startswith(("http://", "https://")):
            raise ConfigError("jev_url 必须以 http:// 或 https:// 开头，当前 %r" % self.jev_url)

    def as_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return tuple(field.name for field in fields(cls))


def _coerce(name: str, value: Any, current: Config) -> Any:
    target = type(getattr(current, name))
    if target is str:
        return str(value)
    if target is int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError("%s 需要整数，收到 %r" % (name, value)) from exc
    if target is float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError("%s 需要数字，收到 %r" % (name, value)) from exc
    raise ConfigError("不支持的配置类型: %s" % name)  # pragma: no cover
