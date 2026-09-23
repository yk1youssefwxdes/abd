@echo off
REM ============================================================================
REM School ERP - Windows Release Builder Batch Wrapper
REM ============================================================================
echo Starting School ERP Windows Release Build...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows_release.ps1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Build failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)
echo.
echo Build completed successfully.
pause
