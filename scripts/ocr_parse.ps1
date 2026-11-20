# ocr_parse.ps1 —— 第一步：MiniCPM-OCR 整页解析
#
# 入口只做四件事：解析参数 → 读配置 → 确保服务在线 → 调 SDK。
# 路径、端口、模型名一律来自 参数 / 环境变量 / config\config.json，
# 脚本里不再出现与某台机器绑死的绝对路径。
#
# 用法:
#   .\scripts\ocr_parse.ps1 -InputPath 'C:\path\to\pages' -Out 'D:\work\out'
#   .\scripts\ocr_parse.ps1 -InputPath .\scan -Config .\config\config.json
#
# 注意: 沙箱里不要用 `& $Py @args` 直接捕获子进程输出（会撞 \\.\pipe\ 拒绝），
#       这里统一 Start-Process + 重定向到文件。

param(
    [Parameter(Mandatory = $true)]
    [Alias('Input')]
    [string]$InputPath,

    [string]$Out = (Join-Path $PSScriptRoot '..\out'),

    [string]$Config,

    [string]$MinicpmRoot = $env:PMOCR_MINICPM_ROOT,
    [string]$OllamaExe = $env:PMOCR_OLLAMA_EXE,
    [string]$PythonExe = $env:PMOCR_PYTHON_EXE,
    [string]$ServerUrl = $env:PMOCR_JEV_URL,
    [string]$Model = $env:PMOCR_OCR_MODEL,
    [string]$LayoutModel,
    [switch]$SaveCrops
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path $PSScriptRoot -Parent
$ConfigPath = if ($Config) { $Config } else { Join-Path $RepoRoot 'config\config.json' }
$Defaults = @{
    minicpm_root = '<OCR_ROOT>'
    server_url   = 'http://127.0.0.1:18499'
    model        = 'minicpm-ocr'
}

function Read-Settings {
    param([string]$Path, [hashtable]$Base)

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host "[config] 未找到 $Path，使用默认值"
        return $Base
    }
    $json = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json
    $merged = $Base.Clone()
    foreach ($property in $json.PSObject.Properties) {
        if ($Base.ContainsKey($property.Name)) { $merged[$property.Name] = [string]$property.Value }
    }
    Write-Host "[config] 已加载 $Path"
    return $merged
}

function Get-Setting {
    param([hashtable]$Settings, [string]$Key)
    if ($Settings.ContainsKey($Key)) { return $Settings[$Key] }
    return $null
}

function Resolve-Paths {
    param([hashtable]$Settings)

    $root = if ($MinicpmRoot) { $MinicpmRoot } else { $Settings['minicpm_root'] }
    $root = [System.IO.Path]::GetFullPath($root)

    if ($PythonExe) { $python = $PythonExe }
    elseif (Get-Setting $Settings 'python_exe') { $python = Get-Setting $Settings 'python_exe' }
    else { $python = Join-Path $root 'venv312\Scripts\python.exe' }

    if ($OllamaExe) { $ollama = $OllamaExe }
    elseif (Get-Setting $Settings 'ollama_exe') { $ollama = Get-Setting $Settings 'ollama_exe' }
    else { $ollama = Join-Path (Split-Path $root -Parent) 'ollama-app\ollama.exe' }

    if ($LayoutModel) { $layout = $LayoutModel }
    elseif (Get-Setting $Settings 'layout_model') { $layout = Get-Setting $Settings 'layout_model' }
    else { $layout = Join-Path $root 'models\PP-DocLayoutV3_infer' }

    if ($ServerUrl) { $server = $ServerUrl }
    elseif (Get-Setting $Settings 'server_url') { $server = Get-Setting $Settings 'server_url' }
    else { $server = $Defaults['server_url'] }

    if ($Model) { $model = $Model }
    elseif (Get-Setting $Settings 'model') { $model = Get-Setting $Settings 'model' }
    else { $model = $Defaults['model'] }

    return @{
        Root   = $root
        Python = [System.IO.Path]::GetFullPath($python)
        Ollama = [System.IO.Path]::GetFullPath($ollama)
        Layout = [System.IO.Path]::GetFullPath($layout)
        Server = $server.TrimEnd('/')
        Model  = $model
        Models = Join-Path $root 'ollama-models'
        Home   = Join-Path $root 'home'
        Runs   = Join-Path $root 'runs'
        Tmp    = Join-Path $root 'vtmp'
        Logs   = Join-Path $root 'logs'
    }
}

function Start-WithEnv {
    param(
        [string]$File,
        [object[]]$Arguments,
        [hashtable]$Environment,
        [string]$Stdout,
        [string]$Stderr,
        [switch]$Wait
    )

    $saved = @{}
    foreach ($key in $Environment.Keys) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key)
        [Environment]::SetEnvironmentVariable($key, $Environment[$key])
    }
    try {
        $launch = @{
            FilePath               = $File
            ArgumentList           = $Arguments
            WindowStyle            = 'Hidden'
            RedirectStandardOutput = $Stdout
            RedirectStandardError  = $Stderr
            PassThru               = $true
        }
        if ($Wait) { $launch.Wait = $true }
        return Start-Process @launch
    } finally {
        foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key]) }
    }
}

function Test-Service {
    param([string]$BaseUrl)
    try {
        $reply = Invoke-RestMethod -Uri "$BaseUrl/api/version" -TimeoutSec 3
        return [bool]$reply.version
    } catch {
        return $false
    }
}

function Start-ServiceIfNeeded {
    param([hashtable]$Paths)

    if (Test-Service -BaseUrl $Paths.Server) {
        Write-Host "[ollama] 已在线 $($Paths.Server)"
        return
    }

    New-Item -ItemType Directory -Force -Path $Paths.Home, $Paths.Logs | Out-Null
    Write-Host "[ollama] 启动 $($Paths.Server)"
    $service = Start-WithEnv -File $Paths.Ollama -Arguments @('serve') -Environment @{
        USERPROFILE       = $Paths.Home
        OLLAMA_HOST       = ($Paths.Server -replace '^https?://', '')
        OLLAMA_MODELS     = $Paths.Models
        OLLAMA_KEEP_ALIVE = '30m'
    } -Stdout (Join-Path $Paths.Logs 'ollama.out.log') -Stderr (Join-Path $Paths.Logs 'ollama.err.log')

    for ($i = 1; $i -le 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Service -BaseUrl $Paths.Server) {
            Write-Host "[ollama] 就绪（$i 秒）"
            return
        }
    }
    Stop-Process -Id $service.Id -Force -ErrorAction SilentlyContinue
    throw "Ollama 30 秒内未就绪，看 $($Paths.Logs)\ollama.err.log"
}

function Invoke-Sdk {
    param([hashtable]$Paths, [string]$Output, [switch]$Crops)

    New-Item -ItemType Directory -Force -Path $Output, $Paths.Tmp, $Paths.Logs | Out-Null

    $arguments = @(
        '-m', 'minicpmvocr', 'parse',
        '--input', $InputPath,
        '--device', 'cpu',
        '--layout-model', $Paths.Layout,
        '--backend', 'ollama',
        '--server-url', $Paths.Server,
        '--model', $Paths.Model,
        '--set', 'upright.enabled=false',
        '--set', "run.run_root=$($Paths.Runs)",
        '-o', $Output
    )
    if ($Crops) { $arguments += @('--set', 'pipeline.save_crops=true') }
    # Start-Process 只是把数组用空格拼起来，含空格的路径必须自己加引号
    $arguments = $arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }

    $stdout = Join-Path $Paths.Logs 'parse.out.log'
    $stderr = Join-Path $Paths.Logs 'parse.err.log'
    $process = Start-WithEnv -File $Paths.Python -Arguments $arguments -Wait -Environment @{
        TMP        = $Paths.Tmp
        TEMP       = $Paths.Tmp
        OLLAMA_HOST = ($Paths.Server -replace '^https?://', '')
    } -Stdout $stdout -Stderr $stderr

    Get-Content -LiteralPath $stdout -Tail 5 -ErrorAction SilentlyContinue
    if ($process.ExitCode -ne 0) {
        Get-Content -LiteralPath $stderr -Tail 20 -ErrorAction SilentlyContinue
        throw "解析失败，退出码 $($process.ExitCode)；完整日志 $stderr"
    }
}

# ---- 入口：只做装配与调用，不含业务逻辑 ----
$settings = Read-Settings -Path $ConfigPath -Base $Defaults
$paths = Resolve-Paths -Settings $settings

foreach ($tool in @('Python', 'Ollama', 'Layout')) {
    if (-not (Test-Path -LiteralPath $paths[$tool])) { throw "找不到 $tool：$($paths[$tool])" }
}

Start-ServiceIfNeeded -Paths $paths
$outputDir = [System.IO.Path]::GetFullPath($Out)
Invoke-Sdk -Paths $paths -Output $outputDir -Crops:$SaveCrops

Write-Host ''
Write-Host "完成。Markdown: $outputDir"
Write-Host "块级数据: $($paths.Runs) 下最新目录的 pages_json\*.json"
