; Inno Setup installer script for HDLE Premium
;
; This script creates a Windows installer (.exe) that:
; - Installs application to C:\Program Files\HDLE\
; - Creates desktop shortcut
; - Preserves user data in %LOCALAPPDATA%\HDLE\ during upgrades
; - Handles clean uninstall (without removing user data)

[Setup]
; Application metadata
AppName=HDLE Premium
AppVersion=1.0.1
AppPublisher=Your Organization
AppPublisherURL=https://github.com/yourusername/v_book
AppSupportURL=https://github.com/yourusername/v_book/issues
AppUpdatesURL=https://github.com/yourusername/v_book/releases

; Installation directories
DefaultDirName={autopf}\HDLE
DefaultGroupName=HDLE Premium
DisableProgramGroupPage=yes

; Output configuration
; Path relative to project root (one level up from installer folder)
OutputDir=..\installer\output
OutputBaseFilename=HDLE_Premium_Setup
SetupIconFile=compiler:SetupClassicIcon.ico

; Compression
Compression=lzma2
SolidCompression=yes

; Architecture
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; UI
WizardStyle=modern
; Use default images (compiler: paths commented out to avoid file not found errors)
; WizardImageFile=compiler:WizModernImage-IS.bmp
; WizardSmallImageFile=compiler:WizModernSmallImage-IS.bmp

; Versioning
VersionInfoVersion=1.0.1.0
VersionInfoCompany=Your Organization
VersionInfoDescription=HDLE Premium Installer
VersionInfoCopyright=Copyright (C) 2026
VersionInfoProductName=HDLE Premium
VersionInfoProductVersion=1.0.1

; Privileges
PrivilegesRequired=admin

; User data preservation
; IMPORTANT: %LOCALAPPDATA%\HDLE\ is NOT part of {app}, so it survives upgrades/uninstalls

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Components]
Name: "core"; Description: "Core Application (required)"; Types: full compact custom; Flags: fixed; ExtraDiskSpaceRequired: 800000000
Name: "localmodels"; Description: "Local Models (recommended)"; Types: full custom; ExtraDiskSpaceRequired: 1200000000
Name: "baseline"; Description: "Hebrew Wikipedia Baseline (optional, large)"; Types: full custom; ExtraDiskSpaceRequired: 3000000000

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "openresources"; Description: "Open Resources Manager after installation"; Flags: unchecked
Name: "runhealth"; Description: "Run Health Check after installation"; Flags: unchecked

[Files]
; Application files (onedir mode - entire distribution folder)
; Path is relative to project root (one level up from installer folder)
Source: "..\dist\HDLE_Premium\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core

; Required bundled pronunciation model for premium offline niqqud flows.
Source: "..\installer\resources\local_models\phonikud\*"; DestDir: "{app}\resources\models\phonikud"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist; Components: core

; Optional extra local models package (required phonikud model already ships in core).
Source: "..\installer\resources\local_models\*"; DestDir: "{localappdata}\HDLE\models"; Excludes: "phonikud\*"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist; Components: localmodels

; Optional baseline bundle package (if prepared externally before installer build).
Source: "..\installer\resources\baseline\*.hdleproj"; DestDir: "{localappdata}\HDLE\datasets\baseline"; Flags: ignoreversion skipifsourcedoesntexist; Components: baseline

; NOTE: User data (database, logs, backups) is stored in:
; %LOCALAPPDATA%\HDLE\
; This directory is NOT managed by the installer and survives upgrades/uninstalls

[Icons]
; Start menu shortcut
Name: "{group}\HDLE Premium"; Filename: "{app}\HDLE_Premium.exe"

; Desktop shortcut (optional, user selects during install)
Name: "{autodesktop}\HDLE Premium"; Filename: "{app}\HDLE_Premium.exe"; Tasks: desktopicon

[Run]
; Offer to launch app after installation
Filename: "{app}\HDLE_Premium.exe"; Description: "{cm:LaunchProgram,HDLE Premium}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\HDLE_Premium.exe"; Parameters: "--open-resources-manager"; Description: "Open Resources Manager"; Tasks: openresources; Flags: nowait postinstall skipifsilent
Filename: "{app}\HDLE_Premium.exe"; Parameters: "--run-health-check"; Description: "Run Health Check"; Tasks: runhealth; Flags: nowait postinstall skipifsilent

[Code]
// Custom uninstall confirmation message
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  LocalAppData: String;
  UserDataPath: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    LocalAppData := ExpandConstant('{localappdata}');
    UserDataPath := LocalAppData + '\HDLE';

    MsgBox('HDLE Premium has been uninstalled.' + #13#10 + #13#10 +
           'Your user data (database, backups, logs) has been preserved at:' + #13#10 +
           UserDataPath + #13#10 + #13#10 +
           'To completely remove all data, manually delete this folder.',
           mbInformation, MB_OK);
  end;
end;

[UninstallDelete]
; Clean up application directory only (not user data)
Type: filesandordirs; Name: "{app}"

; NOTE: We do NOT delete %LOCALAPPDATA%\HDLE\ - user data is preserved
