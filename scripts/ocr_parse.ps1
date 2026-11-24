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
    [int]$Workers = 0,
    [int]$RequestTimeoutSec = 0,
    [int]$NumParallel = 0,
    [string]$ServiceScript = $env:PMOCR_SERVICE_SCRIPT,
    [switch]$SaveCrops
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path $PSScriptRoot -Parent
$ConfigPath = if ($Config) { $Config } else { Join-Path $RepoRoot 'config\config.json' }
$Defaults = @{
    minicpm_root             = '<OCR_ROOT>'
    server_url               = 'http://127.0.0.1:18499'
    model                    = 'minicpm-ocr'
    # 11-24 实测（RTX 5060 Laptop 8GB）定稿：workers=2 + np=2 → 42 块/分；
    # workers 默认 32 会让每页 125MB 的图解撑到 4GB 峰值，直接 0xC0000005；
    # 请求超时 300s 会截断扫描件长正文块，整批 500。别再调高并发。
    workers                  = '2'
    request_timeout_sec      = '900'
    request_ready_timeout_sec = '1800'
    num_parallel             = '2'
    max_loaded_models        = '1'
    ollama_keep_alive        = '30m'
    service_script           = ''
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

    $workers = if ($Workers -gt 0) { $Workers }
    elseif (Get-Setting $Settings 'workers') { [int](Get-Setting $Settings 'workers') }
    else { [int]$Defaults['workers'] }

    $timeout = if ($RequestTimeoutSec -gt 0) { $RequestTimeoutSec }
    elseif (Get-Setting $Settings 'request_timeout_sec') { [int](Get-Setting $Settings 'request_timeout_sec') }
    else { [int]$Defaults['request_timeout_sec'] }

    $readyTimeout = if (Get-Setting $Settings 'request_ready_timeout_sec') { [int](Get-Setting $Settings 'request_ready_timeout_sec') }
    else { [int]$Defaults['request_ready_timeout_sec'] }

    $parallel = if ($NumParallel -gt 0) { $NumParallel }
    elseif (Get-Setting $Settings 'num_parallel') { [int](Get-Setting $Settings 'num_parallel') }
    else { [int]$Defaults['num_parallel'] }

    $maxLoaded = if (Get-Setting $Settings 'max_loaded_models') { [int](Get-Setting $Settings 'max_loaded_models') }
    else { [int]$Defaults['max_loaded_models'] }

    $keepAlive = if (Get-Setting $Settings 'ollama_keep_alive') { [string](Get-Setting $Settings 'ollama_keep_alive') }
    else { [string]$Defaults['ollama_keep_alive'] }

    if (-not $ServiceScript) { $ServiceScript = [string](Get-Setting $Settings 'service_script') }

    return @{
        Root          = $root
        Python        = [System.IO.Path]::GetFullPath($python)
        Ollama        = [System.IO.Path]::GetFullPath($ollama)
        Layout        = [System.IO.Path]::GetFullPath($layout)
        Server        = $server.TrimEnd('/')
        Model         = $model
        Workers       = $workers
        Timeout       = $timeout
        ReadyTimeout  = $readyTimeout
        Parallel      = $parallel
        MaxLoaded     = $maxLoaded
        KeepAlive     = $keepAlive
        ServiceScript = $ServiceScript
        Models        = Join-Path $root 'ollama-models'
        Home          = Join-Path $root 'home'
        Runs          = Join-Path $root 'runs'
        Tmp           = Join-Path $root 'vtmp'
        Logs          = Join-Path $root 'logs'
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
    Write-Host "[ollama] 启动 $($Paths.Server)（np=$($Paths.Parallel), workers=$($Paths.Workers)）"

    if ($Paths.ServiceScript -and (Test-Path -LiteralPath $Paths.ServiceScript)) {
        # 生产机上由 serve_ollama.py 托管（内含 np=2 等定稿环境变量，且能长期守护）
        $pythonw = Join-Path (Split-Path $Paths.Python) 'pythonw.exe'
        if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $Paths.Python }
        Write-Host "[ollama] 托管脚本：$($Paths.ServiceScript)"
        $service = Start-Process -FilePath $pythonw -ArgumentList @('-u', $Paths.ServiceScript) -PassThru -WindowStyle Hidden
    } else {
        $service = Start-WithEnv -File $Paths.Ollama -Arguments @('serve') -Environment @{
            USERPROFILE             = $Paths.Home
            OLLAMA_HOST             = ($Paths.Server -replace '^https?://', '')
            OLLAMA_MODELS           = $Paths.Models
            OLLAMA_KEEP_ALIVE       = $Paths.KeepAlive
            OLLAMA_NUM_PARALLEL     = "$($Paths.Parallel)"
            OLLAMA_MAX_LOADED_MODELS = "$($Paths.MaxLoaded)"
        } -Stdout (Join-Path $Paths.Logs 'ollama.out.log') -Stderr (Join-Path $Paths.Logs 'ollama.err.log')
    }

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
        '--workers', "$($Paths.Workers)",
        '--set', 'upright.enabled=false',
        '--set', "engine.request_timeout_sec=$($Paths.Timeout)",
        '--set', "engine.request_ready_timeout_sec=$($Paths.ReadyTimeout)",
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
