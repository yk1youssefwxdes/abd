@echo off
REM ==============================================================================
REM School ERP - Uninstaller
REM Removes everything created by setup.bat:
REM   - Programs folder installation
REM   - Desktop and Start Menu shortcuts
REM   - ProgramData config/license files (optional)
REM   - Local venv\ and build\ folders (optional)
REM ==============================================================================
title School ERP - Uninstaller
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROGRAMS_DIR=%LOCALAPPDATA%\Programs\School ERP"
set "DATA_DIR=%PROGRAMDATA%\SchoolERP"
set "DESKTOP=%USERPROFILE%\Desktop"
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo.
echo ==============================================================================
echo   School ERP - Uninstaller
echo ==============================================================================
echo.
echo  This will remove:
echo    - %PROGRAMS_DIR%
echo    - Desktop shortcut
echo    - Start Menu shortcut
echo    - Startup shortcut (if exists)
echo.
echo  You will be asked separately about:
echo    - Customer data in %DATA_DIR%
echo    - Local venv\ and build\ folders
echo.

set /p CONFIRM= Are you sure you want to uninstall School ERP? [y/N]: 
if /I not "%CONFIRM%"=="y" (
    echo Uninstall cancelled.
    pause
    exit /b 0
)

REM ==============================================================================
REM 1. Stop any running School ERP processes
REM ==============================================================================
echo.
echo [*] Stopping any running School ERP processes...

taskkill /F /IM SchoolERP.exe >nul 2>&1
if %ERRORLEVEL% EQU 0 echo [OK] Stopped SchoolERP.exe

REM Kill pythonw running run_server.py from Programs folder
wmic process where "name='pythonw.exe'" get commandline 2>nul | findstr /I "School ERP" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    wmic process where "name='pythonw.exe' and commandline like '%%School ERP%%'" delete >nul 2>&1
    echo [OK] Stopped pythonw.exe server process
)

timeout /t 1 /nobreak >nul

REM ==============================================================================
REM 2. Remove Programs folder
REM ==============================================================================
echo.
echo [*] Removing Programs folder...
if exist "%PROGRAMS_DIR%" (
    rmdir /s /q "%PROGRAMS_DIR%"
    if exist "%PROGRAMS_DIR%" (
        echo [WARN] Could not fully remove Programs folder - some files may be in use.
        echo        Please close all School ERP windows and run uninstall again.
    ) else (
        echo [OK] Removed: %PROGRAMS_DIR%
    )
) else (
    echo [SKIP] Programs folder not found.
)

REM ==============================================================================
REM 3. Remove Desktop shortcut
REM ==============================================================================
REM Check both regular Desktop and OneDrive Desktop
set "SHORTCUT_NAME=School ERP.lnk"

if exist "%DESKTOP%\%SHORTCUT_NAME%" (
    del /f /q "%DESKTOP%\%SHORTCUT_NAME%"
    echo [OK] Removed Desktop shortcut
)

REM OneDrive Desktop fallback
if exist "%USERPROFILE%\OneDrive\Desktop\%SHORTCUT_NAME%" (
    del /f /q "%USERPROFILE%\OneDrive\Desktop\%SHORTCUT_NAME%"
    echo [OK] Removed OneDrive Desktop shortcut
)

REM ==============================================================================
REM 4. Remove Start Menu shortcuts
REM ==============================================================================
if exist "%STARTMENU%\%SHORTCUT_NAME%" (
    del /f /q "%STARTMENU%\%SHORTCUT_NAME%"
    echo [OK] Removed Start Menu shortcut
)

if exist "%STARTUP%\%SHORTCUT_NAME%" (
    del /f /q "%STARTUP%\%SHORTCUT_NAME%"
    echo [OK] Removed Startup shortcut
)

REM ==============================================================================
REM 5. Customer data (ProgramData) - ask before deleting
REM ==============================================================================
echo.
if exist "%DATA_DIR%" (
    echo [!] Customer data found at:
    echo     %DATA_DIR%
    echo     This contains licenses, database, and configuration files.
    echo.
    set /p DEL_DATA= Delete customer data? This cannot be undone! [y/N]: 
    if /I "%DEL_DATA%"=="y" (
        rmdir /s /q "%DATA_DIR%"
        echo [OK] Removed: %DATA_DIR%
    ) else (
        echo [SKIP] Customer data kept.
    )
) else (
    echo [SKIP] No customer data directory found.
)

REM ==============================================================================
REM 6. Local venv\ and build\ folders - ask before deleting
REM ==============================================================================
echo.
if exist "%SCRIPT_DIR%venv" (
    set /p DEL_VENV= Delete local venv\ folder? [y/N]: 
    if /I "%DEL_VENV%"=="y" (
        rmdir /s /q "%SCRIPT_DIR%venv"
        echo [OK] Removed: %SCRIPT_DIR%venv
    ) else (
        echo [SKIP] Local venv kept.
    )
)

if exist "%SCRIPT_DIR%build" (
    set /p DEL_BUILD= Delete local build\ folder ^(release artifacts^)? [y/N]: 
    if /I "%DEL_BUILD%"=="y" (
        rmdir /s /q "%SCRIPT_DIR%build"
        echo [OK] Removed: %SCRIPT_DIR%build
    ) else (
        echo [SKIP] Local build folder kept.
    )
)

REM ==============================================================================
REM Done
REM ==============================================================================
echo.
echo ==============================================================================
echo   School ERP uninstalled successfully.
echo ==============================================================================
echo.
pause
exit /b 0
