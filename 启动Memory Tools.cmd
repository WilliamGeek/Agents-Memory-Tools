@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
cd /d "%ROOT_DIR%"

title Agents Memory Tools

echo ======================================================================
echo   Agents Memory Tools - 跨智能体会话记忆工作台
echo   Web      : http://localhost:3000    (Next.js + React)
echo   Backend  : http://127.0.0.1:18922  (Python SQLite FTS5)
echo ======================================================================
echo.

if not exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
    echo [ERROR] 未找到虚拟环境: %ROOT_DIR%\.venv\Scripts\python.exe
    pause
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未检测到 Node.js，请先安装 Node.js 20 或更高版本。
    pause
    exit /b 1
)

set "PKG=npm.cmd"
where pnpm >nul 2>&1
if not errorlevel 1 set "PKG=pnpm.cmd"

echo [1/3] 检查 Python 核心引擎 (18922) ...
netstat -ano | findstr :18922 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    start "" /min "%ROOT_DIR%\.venv\Scripts\python.exe" "%ROOT_DIR%\web_app.py"
    echo       已启动
) else (
    echo       已在运行，跳过
)

echo [2/3] 检查前端构建产物 ...
if not exist "%ROOT_DIR%\frontend\.next\BUILD_ID" (
    echo       首次启动或构建缺失，正在编译前端（约需 1 分钟）...
    pushd "%ROOT_DIR%\frontend"
    call "%PKG%" run build
    popd
    if not exist "%ROOT_DIR%\frontend\.next\BUILD_ID" (
        echo [ERROR] 前端构建失败，请检查 Node 依赖是否完整。
        pause
        exit /b 1
    )
    echo       构建完成
) else (
    echo       构建产物已就绪
)

echo [3/3] 启动 Web 工作台 (3000) ...
netstat -ano | findstr :3000 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    pushd "%ROOT_DIR%\frontend"
    start "" /min cmd /c "%PKG% run start"
    popd
    ping 127.0.0.1 -n 4 >nul
) else (
    echo       已在运行，跳过
)

start "" http://localhost:3000

echo.
echo ======================================================================
echo   已就绪：http://localhost:3000
echo   停止服务：运行「停止Memory Tools.cmd」，或在此按任意键
echo ======================================================================
pause >nul
call "%ROOT_DIR%\停止Memory Tools.cmd"
