; Inno Setup script: per-user install (no admin needed), Start menu + optional desktop shortcut, uninstaller.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8F9AFAD6-CC89-49B8-9F9E-C02BE6F95097}
AppName=Virten Studio
AppVersion={#AppVersion}
AppPublisher=Angelito Jusay
DefaultDirName={localappdata}\Programs\Virten Studio
DefaultGroupName=Virten Studio
UsePreviousAppDir=no
UsePreviousGroup=no
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=VirtenStudio-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\Virten Studio.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Virten Studio\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[InstallDelete]
; Virten Studio was called AutoStyle: remove the old program folder and shortcuts
Type: filesandordirs; Name: "{localappdata}\Programs\AutoStyle"
Type: filesandordirs; Name: "{userprograms}\AutoStyle"
Type: files; Name: "{userdesktop}\AutoStyle.lnk"

[Icons]
Name: "{group}\Virten Studio"; Filename: "{app}\Virten Studio.exe"; AppUserModelID: "AngelitoJusay.VirtenStudio"
Name: "{autodesktop}\Virten Studio"; Filename: "{app}\Virten Studio.exe"; Tasks: desktopicon; AppUserModelID: "AngelitoJusay.VirtenStudio"

[Run]
Filename: "{app}\Virten Studio.exe"; Description: "Start Virten Studio"; Flags: nowait postinstall skipifsilent
