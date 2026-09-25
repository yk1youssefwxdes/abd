@echo off
title School ERP Server
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" run_server.py %*
) else (
    python run_server.py %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Server exited with error code %ERRORLEVEL%.
    pause
)
