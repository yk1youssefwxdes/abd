# ==============================================================================
# School ERP - Windows Automated Release Builder & Installer Compiler (PowerShell)
# Run this script on a Windows 10/11 x64 build machine.
# ==============================================================================
param(
    [string]$PythonVersion = "3.11.9",
    [string]$NodeVersion = "20.12.2"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ReleaseDir = Join-Path $ProjectRoot "release\SchoolERP"
$DistDir = Join-Path $ProjectRoot "dist"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " School ERP Commercial Windows Release Builder" -ForegroundColor Cyan
Write-Host " Project Root: $ProjectRoot" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Clean previous release folders
Write-Host "[1/7] Cleaning previous release folders..." -ForegroundColor Yellow
if (Test-Path $ReleaseDir) { Remove-Item -Recurse -Force $ReleaseDir }
if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
New-Item -ItemType Directory -Force -Path (Join-Path $ReleaseDir "runtime\python") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ReleaseDir "runtime\node") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ReleaseDir "runtime\chromium") | Out-Null
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

# 2. Copy Application Files (excluding data and dev artifacts)
Write-Host "[2/7] Copying immutable application files to release directory..." -ForegroundColor Yellow
$ExcludeList = @("data", "logs", "backups", "venv", ".venv", ".git", "dist", "release", "__pycache__", "whatsapp_session", ".wwebjs_cache")
Get-ChildItem -Path $ProjectRoot | Where-Object { $ExcludeList -notcontains $_.Name } | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $ReleaseDir -Recurse -Force
}

# 3. Setup Bundled Standalone Python
Write-Host "[3/7] Setting up Bundled Python Runtime (python-embed-amd64)..." -ForegroundColor Yellow
$PythonEmbedZip = Join-Path $ProjectRoot "runtime_downloads\python-$PythonVersion-embed-amd64.zip"
$PythonDest = Join-Path $ReleaseDir "runtime\python"

if (-not (Test-Path $PythonEmbedZip)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "runtime_downloads") | Out-Null
    $PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Write-Host "  Downloading $PythonUrl..."
    Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonEmbedZip
}

Expand-Archive -Path $PythonEmbedZip -DestinationPath $PythonDest -Force

# Enable site-packages in embeddable python (uncomment import site in ._pth)
$PthFile = Get-ChildItem -Path $PythonDest -Filter "*._pth" | Select-Object -First 1
if ($PthFile) {
    (Get-Content $PthFile.FullName) -replace '#import site', 'import site' | Set-Content $PthFile.FullName
}

# Install pip and wheels into bundled python
$GetPipPy = Join-Path $ProjectRoot "runtime_downloads\get-pip.py"
if (-not (Test-Path $GetPipPy)) {
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPipPy
}
& (Join-Path $PythonDest "python.exe") $GetPipPy --no-warn-script-location
& (Join-Path $PythonDest "python.exe") -m pip install --no-warn-script-location -r (Join-Path $ProjectRoot "requirements.txt")

# 4. Setup Bundled Standalone Node.js
Write-Host "[4/7] Setting up Bundled Node.js Runtime..." -ForegroundColor Yellow
$NodeDest = Join-Path $ReleaseDir "runtime\node"
$NodeExe = Join-Path $ProjectRoot "runtime_downloads\node.exe"
if (-not (Test-Path $NodeExe)) {
    $NodeUrl = "https://nodejs.org/dist/v$NodeVersion/win-x64/node.exe"
    Write-Host "  Downloading $NodeUrl..."
    Invoke-WebRequest -Uri $NodeUrl -OutFile $NodeExe
}
Copy-Item -Path $NodeExe -Destination (Join-Path $NodeDest "node.exe") -Force

# 5. Build Locked Node Modules
Write-Host "[5/7] Preparing production Node dependencies in whatsapp_service..." -ForegroundColor Yellow
Push-Location (Join-Path $ReleaseDir "whatsapp_service")
npm ci --omit=dev --ignore-scripts
Pop-Location

# 6. Collect Static Assets
Write-Host "[6/7] Collecting static assets into staticfiles/..." -ForegroundColor Yellow
Push-Location $ReleaseDir
& (Join-Path $PythonDest "python.exe") manage.py collectstatic --noinput
Pop-Location

# 7. Compile Inno Setup Installer
Write-Host "[7/7] Compiling Inno Setup Installer (SchoolERP_Setup.exe)..." -ForegroundColor Yellow
$InnoCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $InnoCompiler)) {
    $InnoCompiler = "C:\Program Files\Inno Setup 6\ISCC.exe"
}

if (Test-Path $InnoCompiler) {
    & $InnoCompiler (Join-Path $ProjectRoot "installer.iss")
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host " INSTALLER BUILD SUCCESSFUL!" -ForegroundColor Green
    Write-Host " Output: $(Join-Path $DistDir 'SchoolERP_Setup_v1.0.0.exe')" -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Green
} else {
    Write-Host "WARNING: Inno Setup 6 compiler (ISCC.exe) not found at default paths." -ForegroundColor Yellow
    Write-Host "Release folder prepared at: $ReleaseDir" -ForegroundColor Green
    Write-Host "You can open installer.iss manually in Inno Setup GUI to build the .EXE installer." -ForegroundColor Green
}
