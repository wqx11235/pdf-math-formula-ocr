# PDF Math Formula OCR

把扫描 PDF 变成可信 Markdown 的两段式流程：正文、表格、公式都在，公式是真 LaTeX。

A two-stage pipeline: full-page parsing for structure and text, then per-block re-render and scoring with MiniCPM-OCR Jev, so suspicious formulas surface themselves.


> 2026-11-19 定版。给「中文教材 / 公式密集扫描件」用的两段式流程。
> 与 GTM工作流说明.md 那套（Windows OCR 全量 + 按页出图）是并列关系，不是替代。

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

全部装在 D:\deepseek_harness\.minicpm-ocr\。

| 组件 | 版本/路径 | 说明 |
|---|---|---|
| MiniCPM-OCR 模型 | ollama-models | Q8 GGUF，2GB |
| Jev 打分模型 | ollama-models | Q8 GGUF 2GB + mmproj 671MB |
| Ollama | D:\deepseek_harness\ollama-app\ollama.exe | **解压版**，不是安装版（见坑 1） |
| Python 环境 | venv312\Scripts\python.exe | Python 3.12，minicpm-ocr 1.0.5 + paddlepaddle 3.3.1 |
| 版面模型 | models\PP-DocLayoutV3_infer | 手工解压，约 130MB |
| TeX | D:\Texlive\texlive\2025 | xelatex + standalone，渲染公式用 |

### 前置检查（三样）

    # 1) Python 3.12，且能建虚拟环境
    python -c "import sys; print(sys.version)"

    # 2) TeX：必须有 xelatex + standalone + amsmath
    xelatex --version
    kpsewhich standalone.cls
    kpsewhich amsmath.sty

    # 3) 显卡：8 GB 及以上，nvidia-smi 能列出来
    nvidia-smi --query-gpu=name,memory.total --format=csv

TeX 没装的话，装 TeX Live（Windows：texlive 官方 iso 或 scoop），
只要 basic scheme + latex-extra 就够；或用 MiKTeX 勾选 standalone。

### 从零装一遍（顺序别乱）

**1) 拉模型（ModelScope，国内直连）**

    $b = 'https://modelscope.cn/models'
    curl.exe -L -o MiniCPM-OCR-1_0-Q8_0.gguf  "$b/OpenBMB/MiniCPM-OCR-1.0-gguf/resolve/master/MiniCPM-OCR-1_0-Q8_0.gguf"
    curl.exe -L -o mmproj-model-f16-4x.gguf    "$b/OpenBMB/MiniCPM-OCR-1.0-gguf/resolve/master/mmproj-model-f16-4x.gguf"
    curl.exe -L -o dspark-MiniCPM-OCR-1_0-Q8_0.gguf "$b/OpenBMB/MiniCPM-OCR-1.0-DSpark-gguf/resolve/master/dspark-MiniCPM-OCR-1_0-Q8_0.gguf"
    curl.exe -L -o jev-q8.gguf      "$b/OpenBMB/MiniCPM-OCR-Jev-gguf/resolve/master/MiniCPM-OCR-Jev-Q8_0.gguf"
    curl.exe -L -o jev-mmproj.gguf  "$b/OpenBMB/MiniCPM-OCR-Jev-gguf/resolve/master/mmproj-model-f16.gguf"

**2) Ollama 用解压版**（安装器会写注册表被拒，别浪费时间）

下 ollama-windows-amd64.zip（v0.40.16 实测可用），解压到 D:\deepseek_harness\ollama-app。

    curl.exe -L -o ollama.zip https://github.com/ollama/ollama/releases/download/v0.40.16/ollama-windows-amd64.zip
    tar -xf ollama.zip -C D:\deepseek_harness\ollama-app

GitHub 直连慢的话用 gh-proxy 前缀，或者换 0.40.x 里任意一个版本（只要 >= 0.40.12）。

然后在 gguf 所在目录，用 Modelfile 导入：

    $env:USERPROFILE  = 'D:\deepseek_harness\.minicpm-ocr\home'
    $env:OLLAMA_HOST  = '127.0.0.1:18499'
    $env:OLLAMA_MODELS = 'D:\deepseek_harness\.minicpm-ocr\ollama-models'
    D:\deepseek_harness\ollama-app\ollama.exe create minicpm-ocr -f .\Modelfile
    D:\deepseek_harness\ollama-app\ollama.exe create jev -f .\jev\Modelfile

Modelfile 内容（主模型，存成 OCR\Modelfile）：

    FROM ./MiniCPM-OCR-1_0-Q8_0.gguf
    FROM ./mmproj-model-f16-4x.gguf
    DRAFT ./dspark-MiniCPM-OCR-1_0-Q8_0.gguf
    PARAMETER num_ctx 8192
    PARAMETER temperature 0

Jev 的 Modelfile（存成 jev\Modelfile）：

    FROM ./jev-q8.gguf
    FROM ./jev-mmproj.gguf
    PARAMETER num_ctx 8192
    PARAMETER temperature 0

注意 Ollama 的 create 必须在 ollama-app 目录下跑（Workdir），
不然会报 could not locate ollama app：

    cd D:\deepseek_harness\ollama-app
    .\ollama.exe create minicpm-ocr -f D:\path\to\Modelfile
    .\ollama.exe create jev -f D:\path\to\jev\Modelfile

**3) Python SDK**

    & 'D:\deepseek_harness\tools\uv\uv.exe' venv --python 'D:\deepseek_harness\tools\uv-python\cpython-3.12.15-windows-x86_64-none\python.exe' venv312
    & 'D:\deepseek_harness\tools\uv\uv.exe' pip install --python venv312\Scripts\python.exe 'minicpm-ocr[all]' paddlepaddle==3.3.1 --index-url https://pypi.tuna.tsinghua.edu.cn/simple

**4) 版面模型**

    curl.exe -L -o PP-DocLayoutV3_infer.tar 'https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-DocLayoutV3_infer.tar'
    New-Item -ItemType Directory -Force models\PP-DocLayoutV3_infer | Out-Null
    tar -xf PP-DocLayoutV3_infer.tar -C models

解压前先建目录，避免运行时的权限坑（见坑 3）。

### 装完自检（四条，全绿再往下）

    # 1) 服务在线
    curl.exe -s http://127.0.0.1:18499/api/version
    # 期望: {"version":"0.40.x"}

    # 2) 两个模型都在
    curl.exe -s http://127.0.0.1:18499/api/tags
    # 期望: minicpm-ocr:latest 和 jev:latest

    # 3) SDK 能起来
    .\venv312\Scripts\python.exe -m minicpmvocr list-backends
    # 期望: 打印引擎和版面 provider 列表

    # 4) xelatex 能编一个公式
    echo '$\frac{1}{1-z}=1+z+\cdots$' > t.tex
    # 前后补上 documentclass 和 begin/end document 再编译
    xelatex -interaction=nonstopmode t.tex
    # 期望: Output written on t.pdf

---

## 四、日常操作（两步）

### 第一步：整页解析

    cd <脚本所在目录>
    .\ocr_parse.ps1 -Input 'C:\path\to\扫描目录' -Out 'D:\工作\out'

产物：

- out\*.md — 每页一份 Markdown（正文 + 公式 + 表格 + 图）
- D:\deepseek_harness\.minicpm-ocr\runs\<最新>\pages_json\*.json — 块级数据，含每块的 label / bbox / content

### 第二步：公式复核

    $py = 'D:\deepseek_harness\.minicpm-ocr\venv312\Scripts\python.exe'
    & $py <脚本所在目录>\formula_qc.py --pages <最新>\pages_json --images <扫描目录> --out <复核目录> --threshold 0.6

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
- **弯引号**：英文书的弯引号偶尔识别成乱码（`"change,"` 变 `??changee,??`），概率低但见到就手动改。

---

## 八、文件地图

| 路径 | 用途 |
|---|---|
| D:\数学\GTM\公式OCR\ocr_parse.ps1 | 第一步：整页解析 |
| D:\数学\GTM\公式OCR\formula_qc.py | 第二步：公式复核打分 |
| D:\deepseek_harness\.minicpm-ocr\ | 模型、环境、运行目录（**别删**） |
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
