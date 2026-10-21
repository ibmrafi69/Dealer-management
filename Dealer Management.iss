#define MyAppName "Dealer Management"
#define MyAppVersion "1.0.0"
#define MyAppExeName "Dealer Management.exe"

[Setup]
AppId={{93E0D614-4E85-4B8C-ACF0-456B579D141D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=Dealer Management Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
AppMutex=DealerManagementLauncher

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\Dealer Management\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "db.sqlite3"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

; User business data lives in %LOCALAPPDATA%\Dealer Management, outside the
; install directory. No [UninstallDelete] rule is used, so uninstalling never
; removes business data.
