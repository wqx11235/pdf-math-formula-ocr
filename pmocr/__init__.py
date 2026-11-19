"""pmocr —— 两段式扫描 PDF → Markdown 的公式复核工具包。

第一段（整页解析）由 ``scripts/ocr_parse.ps1`` 调用 minicpm-ocr SDK 完成；
第二段（公式复核）由本包完成：裁图 → xelatex 重渲染 → Jev 打分 → 分流报告。

模块划分见 ``docs/架构.md``，每个模块只做一件事。
"""

__version__ = "0.2.0"
