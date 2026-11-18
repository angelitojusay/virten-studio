; Inno Setup script: per-user install (no admin needed), Start menu + optional desktop shortcut, uninstaller.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8F9AFAD6-CC89-49B8-9F9E-C02BE6F95097}
AppName=Virten Studio
AppVersion={#AppVersion}
AppPublisher=Angelito Jusay
AppCopyright=Copyright (c) 2026 Angelito Jusay
AppComments=Virten Studio - Companion Workflow for Adobe(R) Lightroom(R) Classic Catalogs. Adobe and Lightroom are either registered trademarks or trademarks of Adobe Inc. in the United States and/or other countries. Virten Studio is an independent product and is not affiliated with, sponsored by, or endorsed by Adobe Inc.
VersionInfoDescription=Virten Studio - Companion Workflow for Adobe Lightroom Classic Catalogs
VersionInfoCopyright=Copyright (c) 2026 Angelito Jusay. Adobe and Lightroom are trademarks of Adobe Inc.; Virten Studio is not affiliated with Adobe Inc.
LicenseFile=..\LICENSE.txt
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
Source: "..\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Replace the whole previous app bundle, so nothing a newer version dropped stays behind (e.g. 1.6.1's GPL-only
; Qt Virtual Keyboard, or built-in Looks that were renamed). User data lives in %APPDATA% and isn't touched.
Type: filesandordirs; Name: "{app}\_internal"
; Virten Studio was called AutoStyle: remove the old program folder and shortcuts
Type: filesandordirs; Name: "{localappdata}\Programs\AutoStyle"
Type: filesandordirs; Name: "{userprograms}\AutoStyle"
Type: files; Name: "{userdesktop}\AutoStyle.lnk"

[Icons]
Name: "{group}\Virten Studio"; Filename: "{app}\Virten Studio.exe"; AppUserModelID: "AngelitoJusay.VirtenStudio"
Name: "{autodesktop}\Virten Studio"; Filename: "{app}\Virten Studio.exe"; Tasks: desktopicon; AppUserModelID: "AngelitoJusay.VirtenStudio"

[Run]
Filename: "{app}\Virten Studio.exe"; Description: "Start Virten Studio"; Flags: nowait postinstall skipifsilent
