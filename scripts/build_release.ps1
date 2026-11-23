# 一键构建并收集 Windows 发布套件
#
# 前置：已安装 .venv、PyInstaller、Rust MSVC、Tauri CLI。
# 用法：powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Version = "0.1.0"
$Release = Join-Path $Root "release"
$AppExe = Join-Path $Root "src-tauri\target\release\agents-memory-tools-desktop.exe"
$Sidecar = Join-Path $Root "src-tauri\target\release\memory-tools.exe"
$Vc = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
$Tauri = Join-Path $env:USERPROFILE ".cargo\bin\cargo-tauri.exe"

if (-not (Test-Path -LiteralPath $Vc)) {
    throw "未找到 MSVC vcvars64.bat：$Vc"
}
if (-not (Test-Path -LiteralPath $Tauri)) {
    throw "未找到 cargo-tauri.exe；请先安装 tauri-cli。"
}

New-Item -ItemType Directory -Force -Path $Release | Out-Null

Write-Host "1/3 构建 sidecar..."
& (Join-Path $Root "scripts\build_sidecar.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "sidecar 构建失败"
}

Write-Host "2/3 构建 Tauri 外壳和 NSIS..."
& (Join-Path $Root "scripts\build_taura.bat")
if ($LASTEXITCODE -ne 0) {
    throw "Tauri build 失败"
}

Write-Host "3/3 收集发布产物..."
$Portable = Join-Path $Release "AgentsMemoryTools-$Version-portable"
if (Test-Path -LiteralPath $Portable) {
    Remove-Item -LiteralPath $Portable -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Portable | Out-Null
if (-not (Test-Path -LiteralPath $AppExe)) {
    throw "缺少 Tauri 应用 exe：$AppExe"
}
Copy-Item -LiteralPath $AppExe -Destination (Join-Path $Portable "AgentsMemoryTools.exe") -Force
Copy-Item -LiteralPath $Sidecar -Destination $Portable -Force
$LauncherDir = Join-Path $Root "src-tauri\launcher"
Copy-Item -LiteralPath $LauncherDir -Destination (Join-Path $Portable "launcher") -Recurse -Force

$Installer = Get-ChildItem -LiteralPath (Join-Path $Root "src-tauri\target\release\bundle\nsis") -Filter "*-setup.exe" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Installer) {
    throw "NSIS 安装包未生成。"
}
Copy-Item -LiteralPath $Installer.FullName -Destination (Join-Path $Release $Installer.Name) -Force

$Zip = Join-Path $Release "AgentsMemoryTools-$Version-portable.zip"
if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }
Compress-Archive -LiteralPath $Portable -DestinationPath $Zip -CompressionLevel Optimal

$Readme = @"
# Agents Memory Tools $Version

本目录是 Windows 发布套件。

- `AgentsMemoryTools-$Version-portable.zip`：解压即用的便携包（需要 WebView2）。
- $($Installer.Name)：NSIS 安装包（currentUser，不写系统目录）。
- `SHA256SUMS.txt` / `SHA256SUMS.json`：校验和。

## 数据与隐私
所有会话解析都在本机完成；本地服务只监听 127.0.0.1:18923。
用户数据默认在 `%LOCALAPPDATA%\AgentsMemoryTools`，卸载不会删除。
首次启动如需完整历史，请执行豆包同步、等待 Trae 解密，或按
`docs/desktop-build.md` 迁移旧缓存。

## 卸载
Windows 设置 → 应用 → Agents Memory Tools → 卸载。
"@
[IO.File]::WriteAllText((Join-Path $Release "README.md"), $Readme, (New-Object Text.UTF8Encoding $false))

$Files = Get-ChildItem -LiteralPath $Release -Recurse -File | Where-Object { $_.Name -notin @("SHA256SUMS.txt", "SHA256SUMS.json") }
$Manifest = foreach ($f in $Files) {
    $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLower()
    [PSCustomObject]@{
        file = $f.FullName.Substring($Release.Length + 1).Replace("\", "/")
        size = $f.Length
        sha256 = $h
    }
}
$Manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Release "SHA256SUMS.json") -Encoding utf8
$Manifest | ForEach-Object { "$($_.sha256)  $($_.file)" } | Set-Content -LiteralPath (Join-Path $Release "SHA256SUMS.txt") -Encoding ascii

Write-Host "发布套件已生成：$Release"
Get-ChildItem -LiteralPath $Release -File | Select-Object Name, Length
