# 含公式 PDF 识别 · 完整流程（单文件版）

> 2026-11-19 定版。本文档自包含：流程说明 + 两个脚本全文，交给任意 AI 或另一台机器都能照做。
> 文中的 Windows 路径是本机实测路径，换机器时改脚本顶部「固定路径」那一段即可。

---

## 一、这套流程解决什么

把扫描 PDF 变成可信的 Markdown：正文、表格、公式都在，公式是真 LaTeX。

核心是两段：**整页解析**负责结构和正文，**公式复核**负责把公式挑出来单独打分。
第一段的错来自「整页上下文互相干扰」——长公式被手写批注、相邻行带歪；
第二段就是针对这个：按块裁图、单独渲染、逐块打分，低分的才给人看。

### 什么时候用这套，什么时候用 GTM 那套

| 场景 | 用哪套 |
|---|---|
| 英文数学书，只要全文可搜 | GTM 那套（Windows OCR，2.3 秒/页，免费） |
| 中文教材 / 扫描质量一般 / 要还原公式和表格 | **这套** |
| 只要某一页的公式 | GTM 的 gtm.ps1 formula 出页面图，喂视觉模型 |
| 整本书要成稿 | 这套（两段跑完 + 只看低分块） |

---

## 二、实测数据（2026-11-19，29 页扫描件）

| 项 | 数值 |
|---|---|
| 整页解析 29 页 | 约 7 分钟（CPU 版面 + GPU 识别） |
| 单页 | 约 15 秒 |
| 公式复核单块 | 约 2 秒（渲染 1.5 + 打分 0.4） |
| 显存占用 | 模型 2GB，8G 卡够用 |
| 正文准确率 | 抽查 11 页，零错误 |
| 表格 | 3 个表、26 行数字，全对 |
| 公式 | 28 个编号覆盖 23 个显式保留；抽查 40 个公式，1 处真错 |

复核验证（p-13 五个公式块）：

| 块 | 分数 | 判定 |
|---|---|---|
| 1 | 0.8626 | OK |
| 2 | 0.7031 | OK |
| 3 | 0.9590 | OK |
| 4 | 0.9766 | OK |
| 5 | **0.2736** | **CHECK** ← 唯一那块错的 |

阈值 0.6，低分的自动进待复核清单。

---

## 三、环境（一次性，换机器照做）

全部装在 <OCR_ROOT>\。

| 组件 | 版本/路径 | 说明 |
|---|---|---|
| MiniCPM-OCR 模型 | ollama-models | Q8 GGUF，2GB |
| Jev 打分模型 | ollama-models | Q8 GGUF 2GB + mmproj 671MB |
| Ollama | <OCR_ROOT>\..\ollama-app\ollama.exe | **解压版**，不是安装版（见坑 1） |
| Python 环境 | venv312\Scripts\python.exe | Python 3.12，minicpm-ocr 1.0.5 + paddlepaddle 3.3.1 |
| 版面模型 | models\PP-DocLayoutV3_infer | 手工解压，约 130MB |
| TeX | <TeX 安装目录> | xelatex + standalone，渲染公式用 |

### 从零装一遍（顺序别乱）

**1) 拉模型（ModelScope，国内直连）**

    $b = 'https://modelscope.cn/models'
    curl.exe -L -o MiniCPM-OCR-1_0-Q8_0.gguf  "$b/OpenBMB/MiniCPM-OCR-1.0-gguf/resolve/master/MiniCPM-OCR-1_0-Q8_0.gguf"
    curl.exe -L -o mmproj-model-f16-4x.gguf    "$b/OpenBMB/MiniCPM-OCR-1.0-gguf/resolve/master/mmproj-model-f16-4x.gguf"
    curl.exe -L -o dspark-MiniCPM-OCR-1_0-Q8_0.gguf "$b/OpenBMB/MiniCPM-OCR-1.0-DSpark-gguf/resolve/master/dspark-MiniCPM-OCR-1_0-Q8_0.gguf"
    curl.exe -L -o jev-q8.gguf      "$b/OpenBMB/MiniCPM-OCR-Jev-gguf/resolve/master/MiniCPM-OCR-Jev-Q8_0.gguf"
    curl.exe -L -o jev-mmproj.gguf  "$b/OpenBMB/MiniCPM-OCR-Jev-gguf/resolve/master/mmproj-model-f16.gguf"

**2) Ollama 用解压版**（安装器会写注册表被拒，别浪费时间）

下 ollama-windows-amd64.zip（v0.40.16 实测可用），解压到 <OCR_ROOT>\..\ollama-app。
然后在 gguf 所在目录，用 Modelfile 导入：

    $env:USERPROFILE  = '<OCR_ROOT>\home'
    $env:OLLAMA_HOST  = '127.0.0.1:18499'
    $env:OLLAMA_MODELS = '<OCR_ROOT>\ollama-models'
    <OCR_ROOT>\..\ollama-app\ollama.exe create minicpm-ocr -f .\Modelfile
    <OCR_ROOT>\..\ollama-app\ollama.exe create jev -f .\jev\Modelfile

Modelfile 内容：

    FROM ./MiniCPM-OCR-1_0-Q8_0.gguf
    FROM ./mmproj-model-f16-4x.gguf
    DRAFT ./dspark-MiniCPM-OCR-1_0-Q8_0.gguf
    PARAMETER num_ctx 8192
    PARAMETER temperature 0

Jev 的 Modelfile 只要前两行（FROM 主模型 + FROM mmproj）。

**3) Python SDK**

    & 'uv' venv --python '<你的 Python 3.12 目录>\python.exe' venv312
    & 'uv' pip install --python venv312\Scripts\python.exe 'minicpm-ocr[all]' paddlepaddle==3.3.1 --index-url https://pypi.tuna.tsinghua.edu.cn/simple

**4) 版面模型**

    curl.exe -L -o PP-DocLayoutV3_infer.tar 'https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-DocLayoutV3_infer.tar'
    tar -xf PP-DocLayoutV3_infer.tar -C models

---

## 四、日常操作（两步）

### 第一步：整页解析

    cd '<书目录>\GTM\公式OCR'
    .\ocr_parse.ps1 -Input 'C:\path\to\扫描目录' -Out 'D:\工作\out'

产物：

- out\*.md — 每页一份 Markdown（正文 + 公式 + 表格 + 图）
- <OCR_ROOT>\runs\<最新>\pages_json\*.json — 块级数据，含每块的 label / bbox / content

### 第二步：公式复核

    $py = '<OCR_ROOT>\venv312\Scripts\python.exe'
    & $py '<书目录>\GTM\公式OCR\formula_qc.py' --pages <最新>\pages_json --images <扫描目录> --out <复核目录> --threshold 0.6

产物：

- 复核\formula_qc.csv — 每块一行：页、块号、bbox、分数、判定、LaTeX
- 复核\待复核.md — 只列低分块，人工只看这个

---

## 五、阈值怎么定

分数是「候选与区域图一致」的概率，0-1。

| 区间 | 含义 | 处置 |
|---|---|---|
| > 0.9 | 很一致 | 直接信 |
| 0.6 - 0.9 | 大致一致 | 抽查 |
| < 0.6 | 可疑 | 必须人看 |

实测分布：正确块 0.70-0.98，错误块 0.27。0.6 能干净切开。

---

## 六、坑（今天踩过的，按顺序）

| # | 现象 | 原因 / 解法 |
|---|---|---|
| 1 | Ollama 安装器静默失败 | 要写 AppData\Local\Programs 和注册表 HKCU\Environment，被拒。**改用 zip 解压版** |
| 2 | ollama serve 报 could not create directory ~/.ollama | 启动前把 $env:USERPROFILE 指到工作区内的 home 目录 |
| 3 | 解压版面模型 PermissionError | 运行时新建的子目录丢写权限。**先 New-Item -Force 建好目录再解压** |
| 4 | paddlex 报 C:\Users\...\.paddlex 拒绝访问 | icacls <dir> /setintegritylevel "(OI)(CI)Low" 授予低完整性写权限 |
| 5 | SDK 连不上 18499 | 服务没起。ocr_parse.ps1 会自动拉起并等就绪 |
| 6 | PowerShell 调 exe 报 \\.\pipe\... is denied | 沙箱禁命名管道捕获。用 Start-Process -RedirectStandardOutput 或 cmd /c |
| 7 | Jev 打分看着是反的 | 先确认原图到底印了什么，别拿数学常识覆盖证据（p-14 我错过一次） |
| 8 | matplotlib 渲染被 Jev 判不一致 | 字体不像。**必须用 xelatex 渲染** |
| 9 | 复核大面积 SCORE_ERR / HTTP 500 | 两个原因：bbox 是「处理后图像」坐标，要按 image_width 换算到页面图尺寸；图宽超过 1600px 也会触发，要在裁图和渲染后都做等比缩放 |

---

## 七、已知边界

- **手写批注会被当公式**：页边手写会被认成 display_formula，识别必错，但 Jev 给低分，正好被复核拦住。
- **分页公式**：跨页公式会被切成两块，两边都只认半截。
- **编号保留不完整**：28 个编号 23 个显式出现，5 个只留公式不留 (4-x)。要编号就人工补。
- **表格**：转成 HTML table，不是 Markdown 管道表。
- **页眉页码**：偶尔混进正文，后处理时要过滤。
- **Jev 偶发 500**：图太宽（>1600px）或多行 array 时，Jev 可能回 Internal Server Error。脚本已做双向缩放，仍有约 1/4 的块会失败（GTM177 实测 7/25），失败的进待复核清单，人工兜底。
  - **2026-11-19 复核结论**：这 7 个 500 块已逐字对照原图，**LaTeX 全部正确，零错误**（见 `人工复核报告.md`）。所以 **500 是技术性打分失败，不是识别错误**；它和真正抓到过错的低分块（如 0.2736）是两回事。待复核清单里应把 `SCORE_ERR`（未打分，需核对）和 `CHECK`（低分，可能错）分开写，别让人带着"找错"心态去看 500 块。
- **弯引号**：英文书的弯引号偶尔识别成乱码（`"change,"` 变 `??changee,??`），概率低但见到就手动改。

---

## 八、文件地图

| 路径 | 用途 |
|---|---|
| <书目录>\GTM\公式OCR\ocr_parse.ps1 | 第一步：整页解析 |
| <书目录>\GTM\公式OCR\formula_qc.py | 第二步：公式复核打分 |
| <OCR_ROOT>\ | 模型、环境、运行目录（**别删**） |
| ↳ ollama-app\ | Ollama 解压版 |
| ↳ venv312\ | Python 环境 |
| ↳ models\ | 版面模型 |
| ↳ ollama-models\ | 两个 GGUF 模型 |
| ↳ runs\ | 每次解析的块级数据，复核靠它 |

---

## 九、两条线的关系

GTM 那套（Windows OCR）是**保底**：快、免费、英文稳，但只让正文可搜，公式仍要回到页面图。
这套是**成稿**：慢一点，但公式直接出 LaTeX，还有自动复核兜底。

建议分工：

- 279 本全量索引 → 继续走 GTM 那套，不动。
- 要精读、要笔记、要公式的书 → 单独用这套跑一遍。


---

## 附录 A · ocr_parse.ps1（第一步：整页解析）

```powershell
# ocr_parse.ps1 - MiniCPM-OCR 整页解析（第一步）
# 用法: .\ocr_parse.ps1 -Input <PDF或图片目录> [-Out <输出目录>] [-SaveCrops]
param(
  [Parameter(Mandatory=$true)][string]$Input,
  [string]$Out = (Join-Path $PSScriptRoot 'out'),
  [switch]$SaveCrops
)
$ErrorActionPreference = 'Stop'

# ---- 固定路径（换机器改这里）----
$Root   = '<OCR_ROOT>'
$Py     = Join-Path $Root 'venv312\Scripts\python.exe'
$Layout = Join-Path $Root 'models\PP-DocLayoutV3_infer'
$Ollama = '<OCR_ROOT>\..\ollama-app\ollama.exe'
$Home2  = Join-Path $Root 'home'
$Model  = 'minicpm-ocr'
$Host_  = '127.0.0.1:18499'

if (-not (Test-Path $Py))    { throw "找不到 Python: $Py" }
if (-not (Test-Path $Ollama)){ throw "找不到 ollama.exe: $Ollama" }

# ---- 确保服务在跑 ----
$up = $false
try { $r = Invoke-RestMethod -Uri "http://$Host_/api/version" -TimeoutSec 3; $up = [bool]$r.version } catch {}
if (-not $up) {
  Write-Host "启动 Ollama 服务 ($Host_)..."
  New-Item -ItemType Directory -Force $Home2 | Out-Null
  $env:USERPROFILE = $Home2
  $env:OLLAMA_HOST = $Host_
  $env:OLLAMA_MODELS = Join-Path $Root 'ollama-models'
  $env:OLLAMA_KEEP_ALIVE = '30m'
  $so = Join-Path $Root 'ollama-out.log'
  $se = Join-Path $Root 'ollama-err.log'
  $pp = @{ FilePath = $Ollama; ArgumentList = 'serve'; RedirectStandardOutput = $so; RedirectStandardError = $se; WindowStyle = 'Hidden' }
  Start-Process @pp | Out-Null
  $ok = $false
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try { $r = Invoke-RestMethod -Uri "http://$Host_/api/version" -TimeoutSec 2; if ($r.version) { $ok = $true; break } } catch {}
  }
  if (-not $ok) { throw "Ollama 起不来，看 $se" }
}

# ---- 调用 SDK ----
New-Item -ItemType Directory -Force $Out | Out-Null
$env:TMP  = Join-Path $Root 'vtmp'
$env:TEMP = $env:TMP
$env:OLLAMA_HOST = $Host_
New-Item -ItemType Directory -Force $env:TMP | Out-Null

$runRoot = Join-Path $Root 'runs'
$a = @('-m','minicpmvocr','parse','--input',$Input,'--device','cpu',
       '--layout-model',$Layout,'--backend','ollama',
       '--server-url',"http://$Host_",'--model',$Model,
       '--set','upright.enabled=false','--set',"run.run_root=$runRoot",
       '-o',$Out)
if ($SaveCrops) { $a += @('--set','pipeline.save_crops=true') }

# 注意：不要用 & $Py @a —— 沙箱下这条会撞命名管道（\\.\pipe\... is denied）
$so = Join-Path $Root 'parse-out.log'
$se = Join-Path $Root 'parse-err.log'
$pp = @{ FilePath = $Py; ArgumentList = $a; RedirectStandardOutput = $so; RedirectStandardError = $se; WindowStyle = 'Hidden'; Wait = $true; PassThru = $true }
$proc = Start-Process @pp
Get-Content $so -Tail 5 -ErrorAction SilentlyContinue
if ($proc.ExitCode -ne 0) {
  Get-Content $se -Tail 20 -ErrorAction SilentlyContinue
  throw "解析失败，退出码 $($proc.ExitCode)"
}

Write-Host ''
Write-Host "完成。Markdown: $Out"
Write-Host "块级数据: $runRoot 下最新目录的 pages_json\*.json"
```

## 附录 B · formula_qc.py（第二步：公式复核打分）

```python
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
```
