@echo off
title School ERP - Stop All Services
color 0F
echo ============================================================
echo   School ERP - Safe Service Stopper (Unlock Files)
echo ============================================================
echo.
echo Stopping running School ERP background processes...
echo.

:: 1. Kill process on Port 8000 (Django / Waitress)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [OK] Stopping Web Server process (PID: %%a)...
    taskkill /F /PID %%a >nul 2>&1
)

:: 2. Kill process on Port 3000 (WhatsApp service)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo [OK] Stopping WhatsApp Service process (PID: %%a)...
    taskkill /F /PID %%a >nul 2>&1
)

:: 3. Kill any lingering pythonw.exe or node.exe in this directory
wmic process where "name='pythonw.exe' and commandline like '%%run_server%%'" call terminate >nul 2>&1
wmic process where "name='node.exe' and commandline like '%%whatsapp%%'" call terminate >nul 2>&1

echo.
echo ============================================================
echo   ALL SERVICES STOPPED SUCCESSFULLY!
echo   All files are now unlocked. You can copy/extract updates.
echo ============================================================
echo.
pause
