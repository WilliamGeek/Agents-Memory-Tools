@echo off
setlocal
chcp 65001 >nul

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
cd /d "%ROOT_DIR%"

echo ======================================================================
echo   Stopping Agents Memory Tools Service on Port 18922
echo ======================================================================
echo.

set STOPPED_ANY=0

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18922 " ^| findstr LISTENING') do (
    if not "%%a"=="0" (
        echo [Info] Stopping Python Engine PID %%a ...
        taskkill /F /PID %%a >nul 2>&1
        set STOPPED_ANY=1
    )
)

if "%STOPPED_ANY%"=="1" (
    echo [Success] Agents Memory Tools service stopped cleanly.
) else (
    echo [Info] No active service found on port 18922.
)

echo.