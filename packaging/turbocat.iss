; Inno Setup script for TurboCAT's Windows installer (iscc packaging\turbocat.iss).
; Installs dist\TurboCAT (built by PyInstaller) for the current user, with Start menu and
; optional desktop shortcuts. No admin rights needed.
#ifndef AppVersion
  #define AppVersion "4.0"
#endif

[Setup]
AppId={{6E7B2C4A-1F0B-4C4E-9A61-7D2B5E3A9C10}
AppName=TurboCAT 4
AppVersion={#AppVersion}
AppPublisher=David Hill
AppPublisherURL=https://github.com/davidhill99/TurboCAT4
DefaultDirName={localappdata}\Programs\TurboCAT
DefaultGroupName=TurboCAT 4
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TurboCAT-{#AppVersion}-Windows-Setup
SetupIconFile=build-icons\turbocat.ico
UninstallDisplayIcon={app}\TurboCAT.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Make a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\TurboCAT\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\TurboCAT 4"; Filename: "{app}\TurboCAT.exe"
Name: "{autodesktop}\TurboCAT 4"; Filename: "{app}\TurboCAT.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TurboCAT.exe"; Description: "Start TurboCAT 4"; Flags: nowait postinstall skipifsilent
