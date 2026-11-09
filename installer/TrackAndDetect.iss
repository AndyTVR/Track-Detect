; Inno Setup script for the Track & Detect customer beta installer.
; Built by .github/workflows/build-beta.yml:
;   iscc /DAppVersion=0.9.1 /DSourceDir=..\build\app.dist installer\TrackAndDetect.iss

#ifndef AppVersion
  #define AppVersion "0.9.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\app.dist"
#endif

[Setup]
AppId={{6100FFCD-378A-4F80-9BD8-7B9FFDC79EB6}
AppName=Track & Detect (Beta)
AppVersion={#AppVersion}
AppVerName=Track & Detect {#AppVersion} Beta
AppPublisher=Thermal Vision Ecology
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Track & Detect beta installer
; installs for this user only: no administrator rights needed
PrivilegesRequired=lowest
DefaultDirName={autopf}\Track and Detect
DefaultGroupName=Track & Detect
DisableProgramGroupPage=yes
LicenseFile=..\LICENCE-BETA.txt
SetupIconFile=..\static\app.ico
UninstallDisplayIcon={app}\Track and Detect.exe
UninstallDisplayName=Track & Detect (Beta)
OutputDir=..\dist
OutputBaseFilename=Track-and-Detect-Beta-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put a Track && Detect icon on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Track & Detect"; Filename: "{app}\Track and Detect.exe"
Name: "{group}\Uninstall Track & Detect"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Track & Detect"; Filename: "{app}\Track and Detect.exe"; Tasks: desktopicon

[Registry]
; the date the beta was first installed on this computer (starts the 90-day trial).
; Kept on uninstall, so reinstalling doesn't restart the trial.
Root: HKCU; Subkey: "Software\Thermal Vision Ecology\Track and Detect"; ValueType: string; ValueName: "InstallDate"; ValueData: "{code:Today}"; Flags: createvalueifdoesntexist uninsdeletekeyifempty

[Run]
Filename: "{app}\Track and Detect.exe"; Description: "Open Track && Detect now"; Flags: nowait postinstall skipifsilent

[Code]
function Today(Param: String): String;
begin
  Result := GetDateTimeString('yyyy/mm/dd', '-', ':');
end;
