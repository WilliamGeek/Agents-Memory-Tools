@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Agents Memory Tools - Web Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_web_coupled.ps1"
pause
