@echo off
title School ERP - Enable Local Network (LAN) Access
color 0B
echo ============================================================
echo   School ERP - Setup LAN / Multi-PC Access
echo ============================================================
echo.
echo Adding Windows Firewall Rule to allow other PCs on the school
echo network to connect to School ERP (Port 8000)...
echo.

:: Add Windows Firewall Rule for Port 8000
netsh advfirewall firewall add rule name="School ERP Web Access (Port 8000)" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1

if %errorlevel% equ 0 (
    echo   [OK] Windows Firewall rule created successfully!
) else (
    echo   [WARN] Could not add firewall rule automatically.
    echo          Please right-click this file and choose "Run as administrator".
)

echo.
echo ============================================================
echo   YOUR LOCAL NETWORK IP ADDRESSES:
echo ============================================================
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    echo   Connect from other PCs at:  http:%%a:8000
)
echo ============================================================
echo.
echo Make sure other computers are connected to the same Wi-Fi or router.
echo.
pause
