"""pmocr —— 扫描 PDF → Markdown 的全流程工具包。

四步各有入口、可单独跑，也可串联：

  ``render``   PDF → 逐页 PNG
  ``qc``       公式复核：裁图 → xelatex 重渲染 → Jev 打分 → 四类分流
  ``merge``    逐页 Markdown → 一本成稿
  ``experiment`` 对照组：三臂人工成本、标签指标、阈值扫描

整页解析由 ``scripts/ocr_parse.ps1`` 调用 minicpm-ocr SDK 完成。
模块划分见 ``docs/架构.md``，每个模块只做一件事。
"""

__version__ = "0.3.0"

