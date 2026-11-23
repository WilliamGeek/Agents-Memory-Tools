param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Version = '0.1.0'
$InstallDir = 'D:\Agents Memory Tools'
$InstalledSidecar = Join-Path $InstallDir 'memory-tools.exe'
$BuiltSidecar = Join-Path $Root 'src-tauri\binaries\memory-tools-x86_64-pc-windows-msvc.exe'
$WebEntry = Join-Path $Root 'web_app.py'
$FrontendOut = Join-Path $Root 'frontend\out\index.html'

if (-not $SkipBuild) {
    Write-Host '== 构建网页版与桌面版共用的 sidecar / 安装包 =='
    & (Join-Path $PSScriptRoot 'build_release.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'build_release.ps1 失败' }
}

$ReleaseInstaller = Join-Path $Root "release\Agents Memory Tools_${Version}_x64-setup.exe"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReleaseInstaller) | Out-Null

$Installer = Get-ChildItem -LiteralPath (Join-Path $Root 'src-tauri\target\release\bundle\nsis') `
    -Filter '*-setup.exe' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $Installer -and (Test-Path -LiteralPath $ReleaseInstaller)) {
    $Installer = Get-Item -LiteralPath $ReleaseInstaller
}
if (-not $Installer) { throw '未找到 NSIS 安装包' }

if ($Installer.FullName -ne $ReleaseInstaller) {
    Copy-Item -LiteralPath $Installer.FullName -Destination $ReleaseInstaller -Force
}

function Get-Sha256 {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
    return ''
}

$Info = [ordered]@{
    generated_at = (Get-Date).ToString('o')
    source_path = $Root
    source_commit = (& git -C $Root rev-parse HEAD)
    source_branch = (& git -C $Root rev-parse --abbrev-ref HEAD)
    source_dirty = [bool]((& git -C $Root status --porcelain) | Where-Object { $_ })
    web_entry = $WebEntry
    web_entry_sha256 = (Get-Sha256 $WebEntry)
    frontend_out = $FrontendOut
    frontend_out_sha256 = (Get-Sha256 $FrontendOut)
    built_sidecar = $BuiltSidecar
    built_sidecar_sha256 = (Get-Sha256 $BuiltSidecar)
    installed_app_dir = $InstallDir
    installed_sidecar = $InstalledSidecar
    installed_sidecar_sha256 = (Get-Sha256 $InstalledSidecar)
    installer = $ReleaseInstaller
    installer_sha256 = (Get-Sha256 $ReleaseInstaller)
    data_dir = (Join-Path $env:LOCALAPPDATA 'AgentsMemoryTools')
    desktop_api = 'http://127.0.0.1:18923'
    source_api = 'http://127.0.0.1:18922'
}

$Info | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Root 'BUILD_INFO.json') -Encoding utf8
$Info | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Root 'release\BUILD_INFO.json') -Encoding utf8

Write-Host "已生成：$($Info.installer)"
Write-Host "已写入：$(Join-Path $Root 'BUILD_INFO.json')"
$Info.GetEnumerator() | ForEach-Object { Write-Host ("{0}: {1}" -f $_.Key, $_.Value) }
