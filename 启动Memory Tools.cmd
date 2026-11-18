@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Agents Memory Tools

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] 未找到 .venv\Scripts\python.exe
    echo 请先在项目根目录创建虚拟环境，并安装 requirements.txt。
    pause
    exit /b 1
)

if not exist "frontend\out\index.html" (
    echo [1/2] 构建前端静态工作台 ...
    set "PKG=npm.cmd"
    where pnpm >nul 2>&1 && set "PKG=pnpm.cmd"
    pushd "frontend"
    if not exist "node_modules" (
        call %PKG% install
        if errorlevel 1 goto :build_error
    )
    call %PKG% run build
    if errorlevel 1 goto :build_error
    popd
    if not exist "frontend\out\index.html" (
        echo [ERROR] 前端构建后仍未找到 frontend\out\index.html
        pause
        exit /b 1
    )
)

echo.
echo Agents Memory Tools
echo 本地地址: http://127.0.0.1:18922
echo 关闭此窗口即停止服务并释放进程。
echo.
".venv\Scripts\python.exe" "web_app.py" %*
echo.
echo 服务已退出。
pause
exit /b 0

:build_error
popd
echo [ERROR] 前端依赖安装或构建失败。
pause
exit /b 1