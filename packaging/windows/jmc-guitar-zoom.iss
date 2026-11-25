; Inno Setup script. Compile after PyInstaller has built dist\jmc-guitar-zoom:
;   ISCC.exe /DAppVersion=0.1.0 packaging\windows\jmc-guitar-zoom.iss
; Output: dist\JMC_Guitar_Zoom-<version>-Setup.exe
#ifndef AppVersion
  #error Pass the version with /DAppVersion=x.y.z
#endif

#define AppName "JMC Guitar Zoom"
#define AppExe "jmc-guitar-zoom.exe"

[Setup]
; Fixed identifier: it lets a newer installer upgrade and uninstall the same installation. Never change it.
AppId={{593BF2A3-F945-4E79-A878-696DD9331589}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=JMC Guitar Zoom
AppPublisherURL=https://github.com/cruceno/jmc-guitar-zoom
AppSupportURL=https://github.com/cruceno/jmc-guitar-zoom/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install by default; the dialog lets the user choose an all-users install.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\..\LICENSE
SetupIconFile=..\icons\app-icon.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\..\dist
OutputBaseFilename=JMC_Guitar_Zoom-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\jmc-guitar-zoom\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
