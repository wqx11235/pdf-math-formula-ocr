"""本包统一的异常类型。

调用方只需捕获 ``PmocrError``；具体子类用来区分「该重试」还是「该改配置」。
"""

from __future__ import annotations


class PmocrError(RuntimeError):
    """所有本包异常的基类。"""


class ConfigError(PmocrError):
    """配置缺项、类型不对、存在未知键。属于用户错误，不该重试。"""


class RenderError(PmocrError):
    """候选 LaTeX 编译不出 PDF。通常意味着候选本身有问题，也可能是 TeX 环境缺包。"""


class JevError(PmocrError):
    """Jev 打分服务不可用或返回体不合预期。"""


class DataError(PmocrError):
    """pages_json / CSV / 标签文件格式不对。"""
