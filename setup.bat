@echo off
REM ==============================================================================
REM School ERP - 1-Click Automated Client PC Setup
REM ==============================================================================
title School ERP Client Setup

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo ==============================================================================
echo  School ERP - Automated Client Setup
echo ==============================================================================
echo.

REM 1. Detect Python executable (bundled runtime > venv > system python)
if exist "%SCRIPT_DIR%runtime\python\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%runtime\python\python.exe"
    goto RUN_SETUP
)

if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%venv\Scripts\python.exe"
    goto RUN_SETUP
)

if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
    goto RUN_SETUP
)

REM Fallback to system python
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_EXE=python"
    goto RUN_SETUP
)

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_EXE=py"
    goto RUN_SETUP
)

echo [ERROR] Python was not found on this computer.
echo Please install Python 3.10+ or provide the bundled runtime folder.
echo.
pause
exit /b 1

:RUN_SETUP
echo Found Python: %PYTHON_EXE%
echo Running automated setup...
echo.

"%PYTHON_EXE%" "%SCRIPT_DIR%setup_client.py" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Setup encountered an error (Exit code %ERRORLEVEL%).
    pause
    exit /b %ERRORLEVEL%
)

echo.
pause
