# -*- coding: utf-8 -*-
"""formula_qc.py - 公式复核（第二步）

读 SDK 的块级数据，对每个 display_formula 块：
  1. 按 bbox 从原图裁出区域
  2. 用 xelatex 把候选 LaTeX 渲染成 PNG
  3. 送 Jev 打分（0-1，越高越一致）
低分块写进报告，人工只看这些。

用法:
  python formula_qc.py --pages <pages_json目录> --images <页面图目录> --out <报告目录> [--threshold 0.6]
"""
import argparse, base64, csv, json, os, re, subprocess, sys, urllib.request

ROOT = r'<OCR_ROOT>'
PY_ENV = dict(os.environ, TMP=os.path.join(ROOT, 'vtmp'), TEMP=os.path.join(ROOT, 'vtmp'))
JEV_URL = 'http://127.0.0.1:18499/v1/systemone'
JEV_MODEL = 'jev'
FORMULA_LABELS = ('display_formula', 'isolate_formula', 'interline_equation')


def strip_delims(s):
    s = (s or '').strip()
    s = re.sub(r'^\\\[', '', s); s = re.sub(r'\\\]$', '', s)
    s = re.sub(r'^\$\$', '', s); s = re.sub(r'\$\$$', '', s)
    return s.strip()


def render_xelatex(tex, workdir, name):
    """候选 LaTeX -> PNG（300dpi）。失败返回 (None, 错误)。"""
    texp = os.path.join(workdir, name + '.tex')
    with open(texp, 'w', encoding='utf-8') as f:
        f.write('\\documentclass[12pt,border=3pt]{standalone}\n'
                '\\usepackage{amsmath}\n\\begin{document}\n'
                '$\\displaystyle ' + tex + '$\n\\end{document}\n')
    r = subprocess.run(['xelatex', '-interaction=nonstopmode', '-halt-on-error', name + '.tex'],
                       cwd=workdir, env=PY_ENV, capture_output=True, text=True)
    pdfp = os.path.join(workdir, name + '.pdf')
    if not os.path.exists(pdfp):
        return None, (r.stdout or '')[-300:]
    png = os.path.join(workdir, name + '_xe.png')
    import fitz
    d = fitz.open(pdfp)
    d[0].get_pixmap(dpi=300).save(png)
    d.close()
    return png, ''


def b64(path):
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode()


def jev_score(orig_png, cand_tex, render_png):
    """返回 prob_1：候选与区域图一致的概率。"""
    body = {
        'model': JEV_MODEL,
        'state': cand_tex,
        'images': [b64(orig_png), b64(render_png)],
        'questions': {'consistency': {'type': 'choice', 'criteria': {'0': None, '1': None}}},
    }
    req = urllib.request.Request(JEV_URL, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as resp:
        d = json.loads(resp.read().decode())
    return d['answers']['consistency']['probabilities'].get('1')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', required=True, help='pages_json 目录')
    ap.add_argument('--images', required=True, help='页面 PNG 目录（p-01.png ...）')
    ap.add_argument('--out', required=True, help='报告输出目录')
    ap.add_argument('--threshold', type=float, default=0.6)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    workdir = os.path.join(args.out, '_render')
    os.makedirs(workdir, exist_ok=True)

    from PIL import Image
    rows = []
    files = sorted(f for f in os.listdir(args.pages) if f.endswith('.json'))
    for fn in files:
        page_id = fn[:-5]
        img_path = os.path.join(args.images, page_id + '.png')
        if not os.path.exists(img_path):
            print('[skip] 无页面图', page_id, file=sys.stderr)
            continue
        page = Image.open(img_path)
        d = json.load(open(os.path.join(args.pages, fn), encoding='utf-8'))
        ocr = d.get('ocr') or {}
        blocks = ocr.get('blocks') or []
        # bbox 的坐标系是「处理后图像」，可能和页面图尺寸不同，必须换算
        W0 = float(ocr.get('image_width') or page.width)
        H0 = float(ocr.get('image_height') or page.height)
        sx, sy = page.width / W0, page.height / H0
        idx = 0
        for b in blocks:
            if b.get('label') not in FORMULA_LABELS:
                continue
            tex = strip_delims(b.get('content'))
            if not tex:
                continue
            idx += 1
            bx0, by0, bx1, by1 = [float(v) for v in b['bbox']]
            x0, y0, x1, y1 = bx0 * sx, by0 * sy, bx1 * sx, by1 * sy
            pad = 8
            box = (max(0, int(x0) - pad), max(0, int(y0) - pad),
                   min(page.width, int(x1) + pad), min(page.height, int(y1) + pad))
            crop = os.path.join(workdir, '%s_b%d.png' % (page_id, idx))
            cimg = page.crop(box)
            # Jev 对过宽的图会回 500，先按最长边 1600 等比缩
            if cimg.width > 1600:
                _r = 1600.0 / cimg.width
                cimg = cimg.resize((1600, max(1, int(cimg.height * _r))), Image.LANCZOS)
            cimg.save(crop)

            png, err = render_xelatex(tex, workdir, '%s_b%d' % (page_id, idx))
            if png:
                # 渲染图同样限制最长边（多行 array 会渲得特别宽）
                rim = Image.open(png)
                if max(rim.width, rim.height) > 1600:
                    _r = 1600.0 / max(rim.width, rim.height)
                    rim = rim.resize((max(1, int(rim.width * _r)), max(1, int(rim.height * _r))), Image.LANCZOS)
                    rim.save(png)
                rim.close()
            if not png:
                rows.append(dict(page=page_id, block=idx, bbox=b['bbox'], score='',
                                 verdict='RENDER_FAIL', tex=tex, note=err))
                continue
            try:
                s = jev_score(crop, tex, png)
                verdict = 'OK' if (s is not None and s >= args.threshold) else 'CHECK'
                rows.append(dict(page=page_id, block=idx, bbox=b['bbox'], score=round(s, 4) if s is not None else '',
                                 verdict=verdict, tex=tex, note=''))
            except Exception as e:
                rows.append(dict(page=page_id, block=idx, bbox=b['bbox'], score='',
                                 verdict='SCORE_ERR', tex=tex, note=str(e)[:150]))

    # 写报告
    csvp = os.path.join(args.out, 'formula_qc.csv')
    with open(csvp, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['page', 'block', 'bbox', 'score', 'verdict', 'tex', 'note'])
        w.writeheader(); w.writerows(rows)

    low = [r for r in rows if r['verdict'] != 'OK']
    with open(os.path.join(args.out, '待复核.md'), 'w', encoding='utf-8') as f:
        f.write('# 公式复核 · 待人工确认\n\n')
        f.write('阈值 %.2f，共 %d 个公式块，待复核 %d 个。\n\n' % (args.threshold, len(rows), len(low)))
        for r in low:
            f.write('## %s block %d  (score=%s)\n\n' % (r['page'], r['block'], r['score']))
            fence = chr(96) * 3
            f.write(fence + 'latex\n%s\n%s\n\n' % (r['tex'], fence))
            if r['note']:
                f.write('错误: %s\n\n' % r['note'])

    print('公式块 %d 个，待复核 %d 个' % (len(rows), len(low)))
    print('报告:', csvp)
    print('待复核清单:', os.path.join(args.out, '待复核.md'))


if __name__ == '__main__':
    main()
