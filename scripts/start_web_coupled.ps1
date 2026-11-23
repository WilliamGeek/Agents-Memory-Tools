param(
    [int]$WaitSeconds = 30
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$InstallDir = 'D:\Agents Memory Tools'
$Sidecar = Join-Path $InstallDir 'memory-tools.exe'
$DataDir = Join-Path $env:LOCALAPPDATA 'AgentsMemoryTools'
$DesktopApi = 'http://127.0.0.1:18923'
$SourceApi = 'http://127.0.0.1:18922'

function Test-Api {
    param([string]$BaseUrl)
    try {
        $response = Invoke-WebRequest -Uri "$BaseUrl/api/status" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-Api {
    param([string]$BaseUrl, [int]$Seconds)
    for ($i = 0; $i -lt ($Seconds * 2); $i++) {
        if (Test-Api $BaseUrl) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Open-Web {
    param([string]$Url)
    Start-Process -FilePath $Url
    Write-Host "已打开网页版：$Url"
}

Write-Host 'Agents Memory Tools - 网页版启动器'

# 1) 桌面版已经运行：直接复用同一个后台和同一份 AppData 数据。
if (Test-Api $DesktopApi) {
    Write-Host '检测到桌面版后台 18923，复用该后台与共享数据。'
    Open-Web $DesktopApi
    exit 0
}

# 2) 桌面版未运行但已安装：拉起它的 sidecar，网页版和 exe 使用同一个后端。
if (Test-Path -LiteralPath $Sidecar) {
    Write-Host '启动桌面版 sidecar（18923）...'
    try {
        $process = Start-Process -FilePath $Sidecar `
            -ArgumentList @('--no-browser', '--port', '18923') `
            -WorkingDirectory $InstallDir `
            -WindowStyle Hidden `
            -PassThru
        if (Wait-Api $DesktopApi $WaitSeconds) {
            Write-Host "sidecar 已就绪（PID $($process.Id)）。"
            Open-Web $DesktopApi
            exit 0
        }
        Write-Warning "sidecar 在 $WaitSeconds 秒内未就绪，尝试回退到源码模式。"
    } catch {
        Write-Warning "启动 sidecar 失败：$($_.Exception.Message)，尝试回退到源码模式。"
    }
}

# 3) 没有安装桌面版时，回退到 D 盘源码的 Python 服务。
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到 Python 环境：$Python"
}

if (Test-Api $SourceApi) {
    Write-Host '检测到源码服务 18922，直接打开。'
    Open-Web $SourceApi
    exit 0
}

Write-Host '启动源码服务（18922，共享 AppData 数据目录）...'
$env:MEMORY_TOOLS_DATA_DIR = $DataDir
Start-Process -FilePath $Python `
    -ArgumentList @('web_app.py', '--no-browser', '--port', '18922') `
    -WorkingDirectory $Root `
    -WindowStyle Hidden | Out-Null

if (Wait-Api $SourceApi $WaitSeconds) {
    Open-Web $SourceApi
    exit 0
}

throw "源码服务在 $WaitSeconds 秒内未就绪；请检查 $Root\logs 或手动运行 web_app.py。"
