# ==============================================================================
# School ERP - Windows 1-Line Remote Cloud/GitHub Client Installer
# ==============================================================================
# Run on client's Windows PC via PowerShell (Administrator or standard user):
#   powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/<USER>/<REPO>/main/scripts/install_client.ps1 | iex"
# ==============================================================================

param(
    [string]$Repo = "yk1youssefwxdes/x",
    [string]$Branch = "main",
    [string]$GitHubToken = "",
    [string]$DirectZipUrl = "",
    [string]$InstallDir = "$env:LOCALAPPDATA\SchoolERP",
    [string]$LicenseUrl = "",
    [switch]$Trial = $true,
    [int]$TrialDays = 14,
    [switch]$LockToThisPC = $true,
    [string]$AutoStart = "",
    [switch]$LaunchAfter = $true
)



$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "         School ERP - Automated Windows Cloud Installer               " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " Installation Directory : $InstallDir" -ForegroundColor Yellow
Write-Host " GitHub Repository      : $Repo ($Branch)" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Prepare Target Directories
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$TempDir = Join-Path $env:TEMP "SchoolERP_Install"
if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir }
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
$ZipPath = Join-Path $TempDir "SchoolERP_Release.zip"

# 2. Authenticate & Download from Private Repo
Write-Host "`n[1/5] Downloading code from GitHub repository ($Repo)..." -ForegroundColor Green

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not [string]::IsNullOrWhiteSpace($DirectZipUrl)) {
    # Direct public URL provided
    Write-Host "  Downloading from: $DirectZipUrl" -ForegroundColor Gray
    Invoke-WebRequest -Uri $DirectZipUrl -OutFile $ZipPath -Headers @{ "User-Agent" = "SchoolERP-Installer" }
} else {
    # Private GitHub repository download via Token
    if ([string]::IsNullOrWhiteSpace($GitHubToken)) {
        Write-Host "  Private repository authentication required." -ForegroundColor Yellow
        $GitHubToken = Read-Host "  Enter your GitHub Token (PAT)"
    }

    $ZipApiUrl = "https://api.github.com/repos/$Repo/zipball/$Branch"
    Write-Host "  Connecting to GitHub API ($ZipApiUrl)..." -ForegroundColor Gray
    
    $Headers = @{
        "Authorization" = "Bearer $($GitHubToken.Trim())"
        "Accept"        = "application/vnd.github+json"
        "User-Agent"    = "SchoolERP-Installer"
    }

    Invoke-WebRequest -Uri $ZipApiUrl -Headers $Headers -OutFile $ZipPath
}

$ZipSizeMB = [math]::Round(((Get-Item $ZipPath).Length / 1MB), 2)
Write-Host "  [OK] Download complete ($ZipSizeMB MB)." -ForegroundColor Green


# 4. Extract Package
Write-Host "`n[2/5] Extracting package to $InstallDir..." -ForegroundColor Green
$ExtractTemp = Join-Path $TempDir "extracted"
Expand-Archive -Path $ZipPath -DestinationPath $ExtractTemp -Force

# Locate the root folder containing setup_client.py or manage.py
$SourceRoot = Get-ChildItem -Path $ExtractTemp -Recurse -Filter "setup_client.py" | Select-Object -First 1
if ($SourceRoot) {
    $AppFolder = $SourceRoot.DirectoryName
} else {
    $ManagePy = Get-ChildItem -Path $ExtractTemp -Recurse -Filter "manage.py" | Select-Object -First 1
    if ($ManagePy) {
        $AppFolder = $ManagePy.DirectoryName
    } else {
        $AppFolder = $ExtractTemp
    }
}

# Copy files to final InstallDir
Get-ChildItem -Path $AppFolder | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $InstallDir -Recurse -Force
}
Write-Host "  [OK] Files installed in $InstallDir" -ForegroundColor Green

# 5. Check / Bootstrap Python Environment
Write-Host "`n[3/5] Checking Python runtime on client machine..." -ForegroundColor Green
$PythonExe = $null

# Check bundled runtime first
$BundledPy = Join-Path $InstallDir "runtime\python\python.exe"
if (Test-Path $BundledPy) {
    $PythonExe = $BundledPy
    Write-Host "  Found bundled Python runtime: $BundledPy" -ForegroundColor Gray
} else {
    # Check system python
    $SysPy = (Get-Command python -ErrorAction SilentlyContinue)
    if ($SysPy) {
        $PythonExe = $SysPy.Source
        Write-Host "  Found system Python: $PythonExe" -ForegroundColor Gray
    } else {
        # Check py launcher
        $PyLauncher = (Get-Command py -ErrorAction SilentlyContinue)
        if ($PyLauncher) {
            $PythonExe = $PyLauncher.Source
            Write-Host "  Found Python Launcher (py.exe)" -ForegroundColor Gray
        }
    }
}

# If Python is not installed, download embeddable python automatically
if (-not $PythonExe) {
    Write-Host "  Python is not installed. Downloading standalone embeddable Python..." -ForegroundColor Yellow
    $EmbedPyZip = Join-Path $TempDir "python-embed.zip"
    $EmbedPyDir = Join-Path $InstallDir "runtime\python"
    New-Item -ItemType Directory -Path $EmbedPyDir -Force | Out-Null

    $EmbedUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
    Invoke-WebRequest -Uri $EmbedUrl -OutFile $EmbedPyZip
    Expand-Archive -Path $EmbedPyZip -DestinationPath $EmbedPyDir -Force

    # Enable site-packages in ._pth
    $Pth = Get-ChildItem -Path $EmbedPyDir -Filter "*._pth" | Select-Object -First 1
    if ($Pth) {
        (Get-Content $Pth.FullName) -replace '#import site', 'import site' | Set-Content $Pth.FullName
    }

    # Install pip
    $GetPip = Join-Path $TempDir "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip
    & (Join-Path $EmbedPyDir "python.exe") $GetPip --no-warn-script-location

    $PythonExe = Join-Path $EmbedPyDir "python.exe"
    Write-Host "  [OK] Standalone Python runtime configured." -ForegroundColor Green
}

# 6. Check / Bootstrap Node.js for WhatsApp Service
$BundledNode = Join-Path $InstallDir "runtime\node\node.exe"
$SysNode = (Get-Command node -ErrorAction SilentlyContinue)
if (-not (Test-Path $BundledNode) -and -not $SysNode) {
    Write-Host "`n  Setting up standalone Node.js for WhatsApp automation..." -ForegroundColor Yellow
    $NodeDir = Join-Path $InstallDir "runtime\node"
    New-Item -ItemType Directory -Path $NodeDir -Force | Out-Null
    $NodeUrl = "https://nodejs.org/dist/v20.18.0/win-x64/node.exe"
    Invoke-WebRequest -Uri $NodeUrl -OutFile $BundledNode
    Write-Host "  [OK] Standalone Node.js configured at $BundledNode" -ForegroundColor Green
}


# 6. Windows Autostart Prompt
$EnableAutoStart = $true
if ([string]::IsNullOrWhiteSpace($AutoStart)) {
    $PromptRes = Read-Host "`nStart School ERP automatically when Windows boots? [Y/n]"
    if ($PromptRes -match "^[nN]") {
        $EnableAutoStart = $false
    }
} elseif ($AutoStart -match "^[nN0]") {
    $EnableAutoStart = $false
}

# 7. Run Automated Client Setup Script
Write-Host "`n[4/5] Executing setup_client.py..." -ForegroundColor Green
Set-Location $InstallDir

$SetupArgs = @((Join-Path $InstallDir "setup_client.py"))
if ($Trial) {
    $SetupArgs += "--trial"
    $SetupArgs += "--trial-days"
    $SetupArgs += "$TrialDays"
} elseif ($LockToThisPC) {
    $SetupArgs += "--lock-here"
}
if ($EnableAutoStart) {
    $SetupArgs += "--autostart"
} else {
    $SetupArgs += "--no-autostart"
}
if ($LaunchAfter) {
    $SetupArgs += "--launch"
}

& $PythonExe $SetupArgs


# Cleanup setup scripts and temporary install files
Remove-Item -Path (Join-Path $InstallDir "setup_client.py") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $InstallDir "setup.bat") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $InstallDir "setup.sh") -Force -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue


Write-Host "`n[5/5] Setup finished!" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " INSTALLATION COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host " Application Path : $InstallDir" -ForegroundColor White
Write-Host " Desktop Shortcut : Created on Desktop (School ERP.lnk)" -ForegroundColor White
Write-Host " License Mode     : $(if ($Trial) { "$TrialDays-Day Free Trial (Hardware-locked)" } else { "Full Permanent License" })" -ForegroundColor White
Write-Host " Auto-Start Boot  : $(if ($EnableAutoStart) { 'Enabled (starts on PC boot)' } else { 'Disabled' })" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Cyan


