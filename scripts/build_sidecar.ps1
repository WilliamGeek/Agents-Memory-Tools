# 构建 Python sidecar（PyInstaller onefile）
#
# 用法（在项目根目录执行）：
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_sidecar.ps1
#
# 前置：
#   - .venv 内已安装 pyinstaller
#   - 前端已构建（frontend\out\index.html 存在）
#   - Rust / cargo 只用于 Tauri 外壳；sidecar 本身不依赖 Rust
#
# 产物：
#   dist\MemoryTools.exe
#   src-tauri\binaries\memory-tools-x86_64-pc-windows-msvc.exe

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到虚拟环境 Python: $Python"
}
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path -LiteralPath $PyInstaller)) {
    throw "未安装 PyInstaller。请先执行: $Python -m pip install pyinstaller"
}
if (-not (Test-Path -LiteralPath (Join-Path $Root "frontend\out\index.html"))) {
    throw "缺少前端静态产物 frontend\out\index.html；请先构建前端。"
}

$BuildDir = Join-Path $Root "build\pyinstaller"
$DistDir = Join-Path $Root "dist"
New-Item -ItemType Directory -Force -Path $BuildDir, $DistDir | Out-Null

$PyArgs = @(
    "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "MemoryTools",
    "--distpath", $DistDir,
    "--workpath", $BuildDir,
    "--specpath", $BuildDir,
    "--paths", $Root,
    "--add-data", ((Join-Path $Root "frontend\out") + ";frontend/out"),
    "--add-data", ((Join-Path $Root "tools\doubao_sync.py") + ";tools"),
    "--add-data", ((Join-Path $Root "tools\dbkey\decrypt_trae.py") + ";tools/dbkey"),
    "--hidden-import", "session_migrate",
    "--hidden-import", "tiktoken",
    "--hidden-import", "tokenizers",
    "--hidden-import", "requests",
    "--hidden-import", "cryptography",
    "--collect-data", "tiktoken",
    "web_app.py"
)

& $PyInstaller @PyArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 失败，退出码 $LASTEXITCODE"
}

$Exe = Join-Path $DistDir "MemoryTools.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "PyInstaller 未生成 $Exe"
}

$SidecarDir = Join-Path $Root "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $SidecarDir | Out-Null
$Target = Join-Path $SidecarDir "memory-tools-x86_64-pc-windows-msvc.exe"
Copy-Item -LiteralPath $Exe -Destination $Target -Force

Write-Host "sidecar 已生成: $Exe"
Write-Host "Tauri externalBin 目标: $Target"
Write-Host "下一步（需要 Rust/cargo）: cd src-tauri; cargo tauri build"
