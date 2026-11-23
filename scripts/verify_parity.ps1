$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$InfoPath = Join-Path $Root 'BUILD_INFO.json'
$InstallDir = 'D:\Agents Memory Tools'
$InstalledSidecar = Join-Path $InstallDir 'memory-tools.exe'
$BuiltSidecar = Join-Path $Root 'src-tauri\binaries\memory-tools-x86_64-pc-windows-msvc.exe'
$DesktopApi = 'http://127.0.0.1:18923'
$SourceApi = 'http://127.0.0.1:18922'
$failures = @()

function Get-Sha256 {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
    return ''
}

function Test-Api {
    param([string]$BaseUrl)
    try {
        $response = Invoke-WebRequest -Uri "$BaseUrl/api/status" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-Json {
    param([string]$Url)
    return Invoke-RestMethod -Uri $Url -TimeoutSec 10
}

if (-not (Test-Path -LiteralPath $InfoPath)) {
    throw "缺少 $InfoPath；请先运行 scripts\build_all.ps1"
}
$info = Get-Content -LiteralPath $InfoPath -Raw | ConvertFrom-Json

$builtHash = Get-Sha256 $BuiltSidecar
$installedHash = Get-Sha256 $InstalledSidecar
if (-not $builtHash) {
    $failures += "缺少已构建 sidecar：$BuiltSidecar"
} elseif ($builtHash -ne $installedHash) {
    $failures += "D 盘安装版 sidecar 与当前构建不一致：built=$builtHash installed=$installedHash"
}

$commit = (& git -C $Root rev-parse HEAD)
if ($info.source_commit -and $info.source_commit -ne $commit) {
    $failures += "BUILD_INFO 记录的 commit 与当前源码不一致：$($info.source_commit) != $commit"
}

if (-not (Test-Api $DesktopApi)) {
    Write-Host "桌面版后台未运行：$DesktopApi"
} else {
    $desktopStatus = Get-Json "$DesktopApi/api/status"
    Write-Host "桌面版：total=$($desktopStatus.total_sessions) doubao=$($desktopStatus.format_counts.doubao)"
    $desktopTop = Get-Json "$DesktopApi/api/sessions?format=doubao&sort_by=mtime&order=desc&limit=1&fields=full"
    if ($desktopTop.sessions.Count -gt 0) {
        Write-Host "桌面版最近活跃：$($desktopTop.sessions[0].title) / $($desktopTop.sessions[0].started_at) / mtime=$($desktopTop.sessions[0].mtime)"
    }
}

if (Test-Api $SourceApi) {
    $sourceStatus = Get-Json "$SourceApi/api/status"
    Write-Host "网页源码服务：total=$($sourceStatus.total_sessions) doubao=$($sourceStatus.format_counts.doubao)"
    if (Test-Api $DesktopApi) {
        $sourceTop = Get-Json "$SourceApi/api/sessions?format=doubao&sort_by=mtime&order=desc&limit=1&fields=full"
        if ($sourceTop.sessions.Count -gt 0 -and $desktopTop.sessions.Count -gt 0) {
            $sameCount = ($sourceStatus.total_sessions -eq $desktopStatus.total_sessions)
            $sameTop = ($sourceTop.sessions[0].title -eq $desktopTop.sessions[0].title)
            if (-not $sameCount) { $failures += '18923 与 18922 的会话总数不一致' }
            if (-not $sameTop) { $failures += '18923 与 18922 的最近活跃首条不一致' }
        }
    }
} else {
    Write-Host "网页源码服务未运行：$SourceApi（如果网页版复用了 18923，这是正常的）"
}

Write-Host ''
Write-Host "当前源码 commit：$commit"
Write-Host "已构建 sidecar：$builtHash"
Write-Host "D 盘安装版 sidecar：$installedHash"
Write-Host "安装包：$($info.installer)"
Write-Host "安装包 SHA256：$($info.installer_sha256)"

if ($failures.Count -gt 0) {
    Write-Host ''
    Write-Host '对齐检查未通过：'
    $failures | ForEach-Object { Write-Host " - $_" }
    exit 1
}

Write-Host ''
Write-Host '对齐检查通过：网页版源码、构建产物和 D 盘安装版使用同一版本。'
exit 0
