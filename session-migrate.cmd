@echo off
chcp 65001 >nul
"%~dp0.venv\Scripts\session-migrate.exe" %*
