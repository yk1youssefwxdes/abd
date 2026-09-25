@echo off
REM ==============================================================================
REM School ERP - 1-Click Automated Client Setup for Windows
REM
REM  Default mode  : Builds encrypted/obfuscated release in Programs folder
REM  Alternate mode: Pass "--no-programs" for a quick local dev setup instead
REM
REM  Usage examples:
REM    setup.bat                                   (interactive Programs install)
REM    setup.bat --non-interactive --trial --launch
REM    setup.bat --programs-dir "D:\SchoolERP" --permanent --launch
REM    setup.bat --no-programs                     (local dev setup, no encryption)
REM ==============================================================================
title School ERP - Client Setup
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM --- Check if caller explicitly wants local dev mode ----------------------
set "PROGRAMS_MODE=1"
set "EXTRA_ARGS=%*"

for %%A in (%*) do (
    if /I "%%A"=="--no-programs" set "PROGRAMS_MODE=0"
)

echo.
echo ==============================================================================
echo   School ERP - Automated Client Setup
echo ==============================================================================
echo.

REM ==============================================================================
REM 1. Detect System Python (3.10+ required)
REM ==============================================================================
set "SYSTEM_PYTHON="

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 ( set "SYSTEM_PYTHON=python" & goto CHECK_PYTHON_VERSION )

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 ( set "SYSTEM_PYTHON=py" & goto CHECK_PYTHON_VERSION )

where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 ( set "SYSTEM_PYTHON=python3" & goto CHECK_PYTHON_VERSION )

:PYTHON_NOT_FOUND
echo [ERROR] Python was not found on this computer.
echo.
echo  Please install Python 3.10+ from https://www.python.org/downloads/
echo  IMPORTANT: During installation, check "Add python.exe to PATH".
echo.
pause
exit /b 1

:CHECK_PYTHON_VERSION
for /f "tokens=*" %%i in ('%SYSTEM_PYTHON% -c "import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}\")" 2^>nul') do set "PY_VER=%%i"
for /f "tokens=*" %%i in ('%SYSTEM_PYTHON% -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2^>nul') do set "PY_OK=%%i"

if not "%PY_OK%"=="1" (
    echo [ERROR] Found Python %PY_VER% — School ERP requires Python 3.10 or newer.
    echo         Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo [OK] Python %PY_VER% detected  ^(%SYSTEM_PYTHON%^)

REM ==============================================================================
REM 2. Check Node.js / npm  (required for WhatsApp microservice only)
REM ==============================================================================
where node >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=*" %%i in ('node -v 2^>nul') do echo [OK] Node.js %%i detected
) else (
    echo [WARN] Node.js not found — WhatsApp integration unavailable.
    echo        Install from https://nodejs.org/ if needed.
)

REM ==============================================================================
REM 3. Ensure virtual environment exists
REM ==============================================================================
set "VENV_DIR=%SCRIPT_DIR%venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo.
    echo [*] Creating Python virtual environment in venv\...
    %SYSTEM_PYTHON% -m venv "%VENV_DIR%"
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b %ERRORLEVEL%
    )
    echo [OK] Virtual environment created.
)

REM ==============================================================================
REM 4. Bootstrap critical dependencies (cryptography, django, etc.) into venv
REM ==============================================================================
"%VENV_PYTHON%" -c "import cryptography, django, waitress" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [*] Installing required Python packages (one-time, may take 1-2 min)...
    "%VENV_PYTHON%" -m pip install --no-warn-script-location -r "%SCRIPT_DIR%requirements.txt"
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install Python dependencies.
        echo         Check your internet connection and try again.
        pause
        exit /b %ERRORLEVEL%
    )
    echo [OK] Dependencies installed successfully.
) else (
    echo [OK] Python dependencies already satisfied.
)

REM ==============================================================================
REM 5. Delegate to setup_client.py
REM    Default: --install-programs  (encrypted release in Programs folder)
REM    Override: --no-programs flag skips this and does a local dev setup
REM ==============================================================================
echo.

if "%PROGRAMS_MODE%"=="1" (
    echo [*] Building encrypted client release in Programs folder...
    echo     Code will be obfuscated and deployed to:
    echo     %%LOCALAPPDATA%%\Programs\School ERP
    echo.

    REM Remove --no-programs from forwarded args if present
    set "CLEAN_ARGS=!EXTRA_ARGS:--no-programs=!"

    "%VENV_PYTHON%" "%SCRIPT_DIR%setup_client.py" --install-programs !CLEAN_ARGS!
) else (
    echo [*] Starting local development setup (in-place, no obfuscation)...
    echo.

    set "CLEAN_ARGS=!EXTRA_ARGS:--no-programs=!"

    "%VENV_PYTHON%" "%SCRIPT_DIR%setup_client.py" !CLEAN_ARGS!
)

set "SETUP_EXIT=%ERRORLEVEL%"

echo.
if %SETUP_EXIT% EQU 0 (
    echo ==============================================================================
    echo   Setup completed successfully!
    echo   Open http://127.0.0.1:8000 in your browser to access School ERP.
    echo ==============================================================================
) else (
    echo ==============================================================================
    echo   [ERROR] Setup failed with exit code %SETUP_EXIT%.
    echo   Review the messages above for details.
    echo ==============================================================================
    pause
)

exit /b %SETUP_EXIT%
