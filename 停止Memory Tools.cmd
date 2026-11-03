@echo off
setlocal
title Stop Memory Tools Service
cd /d "%~dp0"

echo ========================================================
echo   Stopping Memory Tools Server (Port 18922)...
echo ========================================================
echo.

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18922" ^| findstr "LISTENING"') do (
    echo [Info] Terminating process PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)

if "%FOUND%"=="1" (
    echo [Success] Memory Tools server stopped successfully.
) else (
    echo [Info] No active Memory Tools server found on port 18922.
)

echo.
ping 127.0.0.1 -n 3 >nul
