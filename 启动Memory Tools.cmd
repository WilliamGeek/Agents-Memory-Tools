@echo off
setlocal
title Memory Tools Dashboard
cd /d "%~dp0"

echo ========================================================
echo   Memory Tools Web Dashboard (Startup Launcher)
echo   Target URL: http://127.0.0.1:18922
echo ========================================================
echo.

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ERROR] Virtualenv python.exe not found at:
    echo         %~dp0.venv\Scripts\python.exe
    echo.
    pause
    exit /b 1
)

echo [INFO] Launching Memory Tools server...
echo.

"%~dp0.venv\Scripts\python.exe" "%~dp0web_app.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Server terminated with error code %errorlevel%.
    pause
)
