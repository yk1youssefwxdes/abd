; ==============================================================================
; School ERP - Inno Setup 6 Commercial Windows Installer Script
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
; Application source & dependencies (Immutable in Program Files)
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
