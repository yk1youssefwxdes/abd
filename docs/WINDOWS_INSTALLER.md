# School ERP — Windows Installer & Packaging Specification

This document provides the complete specification and build instructions for creating the commercial Windows installer (Inno Setup / NSIS) for **School ERP** on Windows 10/11 (64-bit).

---

## 1. Architectural Model & Directory Separation

The application enforces strict separation between **immutable application binaries** and **mutable customer data**:

```
C:\Program Files\SchoolERP\               <-- Read-Only (Installed via Administrator Setup)
    ├── app\                              <-- Django code, core/, templates/, static/
    ├── whatsapp_service\                 <-- Node service (server.js, node_modules/)
    ├── runtime\                          <-- Bundled private runtimes (Zero customer dependencies)
    │   ├── python\                       <-- Standalone Python 3.11+ / 3.12+ with site-packages
    │   ├── node\                         <-- Standalone node.exe & npm.cmd
    │   └── chromium\                     <-- Tested, pinned Chromium / Chrome binary
    ├── staticfiles\                      <-- Pre-collected static assets
    ├── run_server.py (or launcher.exe)   <-- Desktop supervisor / launcher
    ├── version.json
    └── unins000.exe                      <-- Windows Uninstaller

C:\ProgramData\SchoolERP\                 <-- Read-Write (Accessible to standard users)
    ├── database\
    │   └── database.sqlite3             <-- Active customer database & WAL files
    ├── media\                           <-- Student photos, receipts, documents
    ├── backups\                         <-- Database snapshots & automated backups
    ├── whatsapp_session\                <-- Persistent WhatsApp auth & profile
    ├── logs\
    │   ├── launcher.log
    │   ├── django.log
    │   └── whatsapp.log
    ├── config\
    │   └── run_server_config.json       <-- Local settings (WA_API_KEY, port history)
    ├── messages\                        <-- Editable WhatsApp notification templates
    └── licenses\
        └── license.enc                  <-- Hardware-locked license file
```

---

## 2. Bundled Private Runtimes (Zero Prerequisites)

The customer PC does **not** need Python, Node.js, npm, or Chrome installed globally. The installer bundles:

### A. Python Runtime (`runtime/python/`)
* **Option 1 (Embedded / Standalone Python)**: Use official python-embed-amd64 with `pip` installed and wheels from `requirements.txt` installed into `Lib/site-packages`.
* **Option 2 (Nuitka / PyInstaller compiled launcher)**: Compile `run_server.py` into a single standalone binary `SchoolERP.exe`.

### B. Node.js Runtime (`runtime/node/`)
* Download official standalone Windows `node.exe` (Node 20 LTS x64).
* Place `node.exe` in `runtime/node/node.exe`.
* Dependencies in `whatsapp_service/node_modules/` are pre-installed during build via `npm ci --omit=dev`.

### C. Chromium Runtime (`runtime/chromium/`)
* Download a pinned, tested Chromium build (or Puppeteer-compatible Chrome for Testing).
* Place the executable at `runtime/chromium/chrome.exe`.

---

## 3. Inno Setup Script Template (`installer.iss`)

Save this script as `installer.iss` and compile using **Inno Setup 6+** on a Windows build machine:

```iss
; ==============================================================================
; School ERP - Inno Setup Commercial Installer Script
; ==============================================================================

#define MyAppName "School ERP"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "School ERP Systems"
#define MyAppURL "https://www.school-erp.com"
#define MyAppExeName "run_server.py"

[Setup]
AppId={{D3A4B889-497B-4E65-B62C-38A2A82939B1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
OutputDir=dist
OutputBaseFilename=SchoolERP_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
; Create ProgramData customer directory with Full Access for all standard Users
Name: "{commonappdata}\SchoolERP"; Permissions: users-full
Name: "{commonappdata}\SchoolERP\database"; Permissions: users-full
Name: "{commonappdata}\SchoolERP\media"; Permissions: users-full
Name: "{commonappdata}\SchoolERP\backups"; Permissions: users-full
Name: "{commonappdata}\SchoolERP\whatsapp_session"; Permissions: users-full
Name: "{commonappdata}\SchoolERP\logs"; Permissions: users-full
Name: "{commonappdata}\SchoolERP\config"; Permissions: users-full
Name: "{commonappdata}\SchoolERP\messages"; Permissions: users-full
Name: "{commonappdata}\SchoolERP\licenses"; Permissions: users-full

[Files]
; Application source & dependencies (Immutable)
Source: "release\SchoolERP\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: """{app}\run_server.py"""; WorkingDir: "{app}"; IconFilename: "{app}\static\images\app_icon.ico"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: """{app}\run_server.py"""; WorkingDir: "{app}"; IconFilename: "{app}\static\images\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\python\pythonw.exe"; Parameters: """{app}\run_server.py"""; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean only runtime temporary caches, NEVER customer database or media
Type: filesandordirs; Name: "{app}\staticfiles"
Type: filesandordirs; Name: "{app}\__pycache__"
```

---

## 4. Upgrade & Data Safety Rules

1. **Idempotent Upgrades**:
   - The installer replaces files under `C:\Program Files\SchoolERP\`.
   - The installer **never** overwrites or deletes `C:\ProgramData\SchoolERP\database\`, `media\`, `backups\`, or `whatsapp_session\`.
2. **First Run Initialization**:
   - When the user launches `School ERP`, `core/paths.py` checks if `database.sqlite3` exists. If not, it applies initial migrations automatically and initializes default settings without administrator intervention.

---

## 5. Security & Firewall Considerations

* **Standard User Execution**: The application runs under standard user credentials. It never requests UAC elevation during daily use.
* **Port Binding**: Loopback sockets on `127.0.0.1:3000` (Node) and `0.0.0.0:8000` (Waitress) are unprivileged (>1024).
* **LAN Access**: If teachers or receptionists connect from other PCs on the center's local Wi-Fi/Ethernet, Windows Firewall may ask to permit incoming connections on Waitress port (prompted once by Windows).
