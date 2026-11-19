"""命令行入口：只做「解析参数 → 装配依赖 → 调服务 → 打印摘要」。

业务逻辑一律不写在这里。任何一段超过 10 行的处理都应回落到对应模块。
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import qc, report
from .config import Config
from .errors import PmocrError
from .paths import OutputLayout, discover_pages, prepare_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmocr",
        description="公式复核：读 pages_json，裁图 → xelatex 重渲染 → Jev 打分 → 分流报告",
    )
    parser.add_argument("--pages", required=True, help="pages_json 目录（*.json）")
    parser.add_argument("--images", required=True, help="页面 PNG 目录（p-01.png ...）")
    parser.add_argument("--out", required=True, help="报告输出目录")
    parser.add_argument("--config", help="配置文件路径（JSON）")
    parser.add_argument("--threshold", type=float, help="低分阈值，默认取配置")
    parser.add_argument("--jev-url", help="Jev 服务地址，默认取配置")
    parser.add_argument("--jev-model", help="Jev 模型名，默认取配置")
    parser.add_argument("--max-image-side", type=int, help="送打分的最长边，默认取配置")
    parser.add_argument("--tex-bin-dir", help="xelatex 所在目录，默认用 PATH")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = Config.load(args.config, overrides=_overrides(args))
        layout = prepare_outputs(args.out)
        summary = qc.run(discover_pages(args.pages, args.images), layout, cfg)
        report.write_csv(summary.results, layout.csv_path)
        report.write_markdown(summary.results, layout.markdown_path, cfg.threshold)
    except PmocrError as exc:
        print("[error] %s" % exc, file=sys.stderr)
        return 2

    _print_summary(summary, layout)
    return 0


def _overrides(args: argparse.Namespace) -> dict[str, object]:
    return {
        "threshold": args.threshold,
        "jev_url": args.jev_url,
        "jev_model": args.jev_model,
        "max_image_side": args.max_image_side,
        "tex_bin_dir": args.tex_bin_dir,
    }


def _print_summary(summary: qc.RunSummary, layout: OutputLayout) -> None:
    counts = report.summarize(summary.results)
    print("公式块 %d：OK %d / CHECK %d / RENDER_FAIL %d / SCORE_ERR %d"
          % (counts.total, counts.ok, counts.check, counts.render_fail, counts.score_err))
    print("待复核 %d（%.1f%%）" % (counts.review, counts.review_share * 100))
    if summary.skipped_pages:
        print("跳过页面 %d：%s" % (len(summary.skipped_pages), ", ".join(summary.skipped_pages)))
    print("报告:", layout.csv_path)
    print("待复核清单:", layout.markdown_path)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
