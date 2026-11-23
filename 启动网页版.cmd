@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Agents Memory Tools - Web
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_web_coupled.ps1"
if errorlevel 1 pause
