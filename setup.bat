@echo off
REM ==============================================================================
REM School ERP - 1-Click Automated Client Setup for Windows
REM
REM  Default : Builds encrypted/obfuscated release in Programs folder
REM  Override: Pass "--no-programs" for a quick local dev setup instead
REM
REM  Examples:
REM    setup.bat
REM    setup.bat --non-interactive --trial --launch
REM    setup.bat --programs-dir "D:\SchoolERP" --permanent --launch
REM    setup.bat --no-programs
REM ==============================================================================
title School ERP - Client Setup
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Detect --no-programs flag safely (findstr handles quoted args fine)
set "PROGRAMS_MODE=1"
echo.%* | findstr /I /C:"--no-programs" >nul 2>&1
if %ERRORLEVEL% EQU 0 set "PROGRAMS_MODE=0"

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

echo [ERROR] Python was not found on this computer.
echo.
echo  Please install Python 3.10+ from https://www.python.org/downloads/
echo  IMPORTANT: During installation, check "Add python.exe to PATH".
echo.
pause
exit /b 1

:CHECK_PYTHON_VERSION
for /f "tokens=2" %%i in ('%SYSTEM_PYTHON% --version 2^>^&1') do set "PY_VER=%%i"
for /f "tokens=*" %%i in ('%SYSTEM_PYTHON% -c "import sys; print(1 if sys.version_info >= (3,10) else 0)" 2^>nul') do set "PY_OK=%%i"

if not "%PY_OK%"=="1" (
    echo [ERROR] Found Python %PY_VER% - School ERP requires Python 3.10 or newer.
    echo         Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo [OK] Python %PY_VER% detected  (%SYSTEM_PYTHON%)

REM ==============================================================================
REM 2. Check Node.js (optional - WhatsApp microservice only)
REM ==============================================================================
where node >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=*" %%i in ('node -v 2^>nul') do echo [OK] Node.js %%i detected
) else (
    echo [WARN] Node.js not found - WhatsApp integration unavailable.
    echo        Install from https://nodejs.org/ if needed.
)

REM ==============================================================================
REM 3. Ensure virtual environment exists
REM ==============================================================================
set "VENV_DIR=%SCRIPT_DIR%venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if exist "%VENV_PYTHON%" goto CHECK_DEPS

echo.
echo [*] Creating Python virtual environment...
%SYSTEM_PYTHON% -m venv "%VENV_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)
echo [OK] Virtual environment created.

REM ==============================================================================
REM 4. Bootstrap critical dependencies into venv
REM ==============================================================================
:CHECK_DEPS
"%VENV_PYTHON%" -c "import cryptography, django, waitress" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Python dependencies already satisfied.
    goto LAUNCH
)

echo.
echo [*] Installing required Python packages (one-time, may take 1-2 min)...
"%VENV_PYTHON%" -m pip install --no-warn-script-location -r "%SCRIPT_DIR%requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install Python dependencies.
    echo         Check your internet connection and try again.
    pause
    exit /b 1
)
echo [OK] Dependencies installed successfully.

REM ==============================================================================
REM 5. Delegate to setup_client.py
REM ==============================================================================
:LAUNCH
echo.

if "%PROGRAMS_MODE%"=="1" (
    echo [*] Building encrypted client release in Programs folder...
    echo     Deploying to: %LOCALAPPDATA%\Programs\School ERP
    echo.
    "%VENV_PYTHON%" "%SCRIPT_DIR%setup_client.py" --install-programs %*
) else (
    echo [*] Local development setup selected.
    echo.
    "%VENV_PYTHON%" "%SCRIPT_DIR%setup_client.py" %*
)

set "SETUP_EXIT=%ERRORLEVEL%"
echo.
if %SETUP_EXIT% EQU 0 (
    echo ==============================================================================
    echo   Setup completed successfully!
    echo   School ERP shortcut created on your Desktop.
    echo ==============================================================================
) else (
    echo ==============================================================================
    echo   [ERROR] Setup failed ^(exit code %SETUP_EXIT%^).
    echo   Review the messages above for details.
    echo ==============================================================================
    pause
)

exit /b %SETUP_EXIT%
