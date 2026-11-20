"""命令行入口：``qc`` / ``render`` / ``merge`` 三个子命令。

每个子命令函数只做「读参数 → 装配 → 调服务 → 打印一行摘要」，
业务逻辑一律不写在这里。实验另有独立入口 ``python -m pmocr.experiment``。
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import merge, qc, render, report
from .config import Config
from .errors import PmocrError
from .paths import OutputLayout, discover_pages, prepare_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmocr",
        description="扫描 PDF → Markdown 的两段式流程：render（PDF→页图）/ qc（公式复核）/ merge（成稿）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_qc(sub)
    _add_render(sub)
    _add_merge(sub)
    return parser


def _add_qc(sub) -> None:
    parser = sub.add_parser("qc", help="公式复核：裁图 → xelatex 重渲染 → Jev 打分 → 分流报告")
    parser.add_argument("--pages", required=True, help="pages_json 目录（*.json）")
    parser.add_argument("--images", required=True, help="页面 PNG 目录（p-01.png ...）")
    parser.add_argument("--out", required=True, help="报告输出目录")
    parser.add_argument("--config", help="配置文件路径（JSON）")
    parser.add_argument("--threshold", type=float, help="低分阈值，默认取配置")
    parser.add_argument("--jev-url", help="Jev 服务地址，默认取配置")
    parser.add_argument("--jev-model", help="Jev 模型名，默认取配置")
    parser.add_argument("--max-image-side", type=int, help="送打分的最长边，默认取配置")
    parser.add_argument("--tex-bin-dir", help="xelatex 所在目录，默认用 PATH")
    parser.set_defaults(func=_run_qc)


def _add_render(sub) -> None:
    parser = sub.add_parser("render", help="PDF → 逐页 PNG（p-01.png ...）")
    parser.add_argument("--pdf", required=True, help="PDF 路径")
    parser.add_argument("--out", required=True, help="页图输出目录")
    parser.add_argument("--config", help="配置文件路径（JSON）")
    parser.add_argument("--edge", type=int, help="页图长边像素，默认取配置（8157）")
    parser.add_argument("--overwrite", action="store_true", help="重渲染已存在的页")
    parser.set_defaults(func=_run_render)


def _add_merge(sub) -> None:
    parser = sub.add_parser("merge", help="逐页 Markdown → 一本成稿")
    parser.add_argument("--pages", required=True, help="逐页 Markdown 目录")
    parser.add_argument("--out", required=True, help="成稿 .md 路径")
    parser.add_argument("--title", required=True, help="书名")
    parser.add_argument("--subtitle", default="", help="副标题")
    parser.add_argument("--note", default="", help="书名下的说明")
    parser.add_argument("--skip", default="", help="要跳过的页码，逗号分隔，如 1,2,3")
    parser.set_defaults(func=_run_merge)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PmocrError as exc:
        print("[error] %s" % exc, file=sys.stderr)
        return 2


def _run_qc(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config, overrides=_qc_overrides(args))
    layout = prepare_outputs(args.out)
    summary = qc.run(discover_pages(args.pages, args.images), layout, cfg)
    report.write_csv(summary.results, layout.csv_path)
    report.write_markdown(summary.results, layout.markdown_path, cfg.threshold)
    _print_qc_summary(summary, layout)
    return 0


def _run_render(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config, overrides={"page_edge": args.edge})
    summary = render.render_pdf(args.pdf, args.out, edge=cfg.page_edge, overwrite=args.overwrite)
    print("页数 %d：新渲染 %d，跳过 %d" % (summary.total, summary.written, summary.skipped))
    print("页图目录:", args.out)
    return 0


def _run_merge(args: argparse.Namespace) -> int:
    summary = merge.merge_pages(
        args.pages,
        args.out,
        title=args.title,
        subtitle=args.subtitle,
        note=args.note,
        skip=_skip_numbers(args.skip),
    )
    print("合并 %d 页 -> %s (%d KB)" % (summary.kept, summary.path, summary.size // 1024))
    return 0


def _qc_overrides(args: argparse.Namespace) -> dict[str, object]:
    return {
        "threshold": args.threshold,
        "jev_url": args.jev_url,
        "jev_model": args.jev_model,
        "max_image_side": args.max_image_side,
        "tex_bin_dir": args.tex_bin_dir,
    }


def _skip_numbers(raw: str) -> tuple[int, ...]:
    return tuple(int(item) for item in raw.split(",") if item.strip().isdigit())


def _print_qc_summary(summary: qc.RunSummary, layout: OutputLayout) -> None:
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
