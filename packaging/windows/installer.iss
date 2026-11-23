; Inno Setup script (free) – per-user installation, no admin rights needed,
; so that in-app updates run without a UAC prompt.
; Build: iscc /DAppVersion=0.1.0 packaging\windows\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "FrameForge"
#define AppExe "FrameForge.exe"

[Setup]
AppId={{6F3C1B52-9E1A-4B7E-9C55-2B8F0A7D4E11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=FrameForge
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=FrameForge-{#AppVersion}-windows-x64-setup
SetupIconFile=..\icons\frameforge.ico
LicenseFile=..\..\LICENSE
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\FrameForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files of the previous version before copying the new ones
Type: filesandordirs; Name: "{app}\_internal"

[Registry]
; Per-user file association for FrameForge projects (no admin rights needed)
Root: HKCU; Subkey: "Software\Classes\.ffproj"; ValueType: string; ValueName: ""; ValueData: "FrameForge.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\FrameForge.Project"; ValueType: string; ValueName: ""; ValueData: "FrameForge-Projekt"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\FrameForge.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKCU; Subkey: "Software\Classes\FrameForge.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; "Öffnen mit" for astro recordings (does not change the existing default program)
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\FrameForge.Recording"; ValueType: string; ValueName: ""; ValueData: "Astro-Aufnahme"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\FrameForge.Recording\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.ser\OpenWithProgids"; ValueType: string; ValueName: "FrameForge.Recording"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.fits\OpenWithProgids"; ValueType: string; ValueName: "FrameForge.Recording"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.fit\OpenWithProgids"; ValueType: string; ValueName: "FrameForge.Recording"; ValueData: ""; Flags: uninsdeletevalue

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Also runs after a silent in-app update → app restarts automatically
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall
