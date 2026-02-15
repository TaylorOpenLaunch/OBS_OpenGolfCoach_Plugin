; Open Golf Coach for OBS - Inno Setup Installer Script
; Bundles Python 3.12 + opengolfcoach so users don't need to install Python.

#define MyAppName "Open Golf Coach for OBS"
#define MyAppPublisher "Open Golf Coach Community"
#define MyAppURL "https://github.com/TaylorOpenLaunch/OBS_OpenGolfCoach_Plugin"

[Setup]
AppId={{E7A3B2C1-4D5F-6A7B-8C9D-0E1F2A3B4C5D}
AppName={#MyAppName}
AppVersion={#SetupSetting("AppVersion")}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={userappdata}\obs-studio\ogc-python
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
LicenseFile=..\LICENSE
OutputDir=..\build\installer-output
OutputBaseFilename=OpenGolfCoach-OBS-Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
SetupIconFile=compiler:SetupClassicIcon.ico
UninstallDisplayName={#MyAppName}
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Bundled Python 3.12 + opengolfcoach (from build/python-embed/)
Source: "..\build\python-embed\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Plugin script
Source: "..\obs_open_golf_coach.py"; DestDir: "{app}\scripts"; Flags: ignoreversion

; Documentation
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Code]
var
  OldPythonPath: string;

function GetGlobalIniPath(): string;
begin
  Result := ExpandConstant('{userappdata}\obs-studio\global.ini');
end;

function ReadIniValue(const FileName, Section, Key, Default: string): string;
begin
  Result := Default;
  if FileExists(FileName) then
    Result := GetIniString(Section, Key, Default, FileName);
end;

procedure WriteIniValue(const FileName, Section, Key, Value: string);
begin
  SetIniString(Section, Key, Value, FileName);
end;

procedure ConfigureOBSPython();
var
  GlobalIni: string;
  ExistingPath: string;
  InstallDir: string;
  Msg: string;
begin
  GlobalIni := GetGlobalIniPath();
  InstallDir := ExpandConstant('{app}');

  // Check for existing Python configuration
  ExistingPath := ReadIniValue(GlobalIni, 'Python', 'Path64bit', '');

  if (ExistingPath <> '') and (CompareText(ExistingPath, InstallDir) <> 0) then
  begin
    // Existing different Python path found - ask user
    OldPythonPath := ExistingPath;
    Msg := 'OBS is currently configured to use Python at:' + #13#10 +
           ExistingPath + #13#10#13#10 +
           'Do you want to switch to the bundled Python?' + #13#10 +
           '(The old path will be restored if you uninstall)';
    if MsgBox(Msg, mbConfirmation, MB_YESNO) = IDNO then
      exit;
  end;

  // Write the Python path
  WriteIniValue(GlobalIni, 'Python', 'Path64bit', InstallDir);
  Log('Set Python Path64bit to: ' + InstallDir);

  // Save old path for uninstall restoration
  if OldPythonPath <> '' then
    WriteIniValue(GlobalIni, 'OpenGolfCoach', 'PreviousPythonPath', OldPythonPath);
end;

procedure ShowPostInstallMessage();
var
  ScriptPath: string;
begin
  ScriptPath := ExpandConstant('{app}\scripts\obs_open_golf_coach.py');
  MsgBox('Installation complete!' + #13#10#13#10 +
         'To finish setup:' + #13#10 +
         '1. Open OBS Studio' + #13#10 +
         '2. Go to Tools > Scripts' + #13#10 +
         '3. Click the + button' + #13#10 +
         '4. Browse to:' + #13#10 +
         '   ' + ScriptPath + #13#10#13#10 +
         '5. Click "Create All Sources" in the script settings' + #13#10 +
         '6. Connect your Nova launch monitor!',
         mbInformation, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    ConfigureOBSPython();
    ShowPostInstallMessage();
  end;
end;

procedure RestorePreviousPythonPath();
var
  GlobalIni: string;
  PreviousPath: string;
begin
  GlobalIni := GetGlobalIniPath();
  PreviousPath := ReadIniValue(GlobalIni, 'OpenGolfCoach', 'PreviousPythonPath', '');

  if PreviousPath <> '' then
  begin
    // Restore the previous Python path
    WriteIniValue(GlobalIni, 'Python', 'Path64bit', PreviousPath);
    Log('Restored previous Python path: ' + PreviousPath);
  end
  else
  begin
    // No previous path - clear the setting
    DeleteIniEntry('Python', 'Path64bit', GlobalIni);
    Log('Cleared Python Path64bit');
  end;

  // Clean up our tracking section
  DeleteIniSection('OpenGolfCoach', GlobalIni);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CurrentPath: string;
  GlobalIni: string;
  InstallDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    GlobalIni := GetGlobalIniPath();
    InstallDir := ExpandConstant('{app}');
    CurrentPath := ReadIniValue(GlobalIni, 'Python', 'Path64bit', '');

    // Only restore if OBS is still pointing to our install
    if CompareText(CurrentPath, InstallDir) = 0 then
      RestorePreviousPythonPath();
  end;
end;
