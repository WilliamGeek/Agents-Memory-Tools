@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
cd /d "%ROOT_DIR%"

title Agents Memory Tools

echo ======================================================================
echo   Agents Memory Tools - 跨智能体会话记忆工作台 (单端口极速架构)
echo   访问地址: http://127.0.0.1:18922  (React 现代化工作台 + Python SQLite FTS5)
echo ======================================================================
echo.

if not exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
    echo [ERROR] 未找到虚拟环境: %ROOT_DIR%\.venv\Scripts\python.exe
    pause
    exit /b 1
)

set "PKG=npm.cmd"
where pnpm >nul 2>&1
if not errorlevel 1 set "PKG=pnpm.cmd"

echo [1/2] 检查前端静态产物 ...
if not exist "%ROOT_DIR%\frontend\out\index.html" (
    echo       首次启动或产物缺失，正在编译静态工作台（约需 20 秒）...
    pushd "%ROOT_DIR%\frontend"
    call "%PKG%" run build
    popd
    if not exist "%ROOT_DIR%\frontend\out\index.html" (
        echo [ERROR] 前端构建失败，请检查 Node 依赖是否完整。
        pause
        exit /b 1
    )
    echo       构建完成
) else (
    echo       静态产物已就绪
)

echo [2/2] 检查核心服务引擎 (18922) ...
netstat -ano | findstr :18922 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    start "" /min "%ROOT_DIR%\.venv\Scripts\python.exe" "%ROOT_DIR%\web_app.py"
    echo       核心引擎已启动
) else (
    echo       核心引擎已在运行
)

start "" http://127.0.0.1:18922

echo.
echo ======================================================================
echo   已就绪：http://127.0.0.1:18922
echo   单端口服务由 Python 引擎统一托管，无需占用额外 Node 端口。
echo   停止服务：运行「停止Memory Tools.cmd」，或在此按任意键
echo ======================================================================
pause >nul
call "%ROOT_DIR%\停止Memory Tools.cmd"
