# ocr_parse.ps1 - MiniCPM-OCR 整页解析（第一步）
# 用法: .\ocr_parse.ps1 -Input <PDF或图片目录> [-Out <输出目录>] [-SaveCrops]
param(
  [Parameter(Mandatory=$true)][string]$Input,
  [string]$Out = (Join-Path $PSScriptRoot 'out'),
  [switch]$SaveCrops
)
$ErrorActionPreference = 'Stop'

# ---- 固定路径（换机器改这里）----
$Root   = 'D:\deepseek_harness\.minicpm-ocr'
$Py     = Join-Path $Root 'venv312\Scripts\python.exe'
$Layout = Join-Path $Root 'models\PP-DocLayoutV3_infer'
$Ollama = 'D:\deepseek_harness\ollama-app\ollama.exe'
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