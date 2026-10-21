; petcore onedir installer (Inno Setup 6)
; Build the app first: pwsh -File scripts/build_petcore.ps1
; Then: ISCC.exe packaging\petcore.iss
;
; 安装目录规则：
;   1. 目录页必须显示（DisableDirPage=no），用户可以改安装位置；
;   2. 已经装过时预选上次的安装路径（UsePreviousAppDir=yes，见下方 [Code]）。
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{8f0f2d4e-4f6c-4f7a-9b7c-1f0b6a2d9c31}
AppName=dsh-pet core
AppVersion={#MyAppVersion}
AppPublisher=merzlin
PrivilegesRequired=lowest
; {code:GetDefaultDir} 读取卸载项里记录的 InstallLocation；没有旧安装时回落
; {localappdata}\Programs\dsh-pet-core。Inno 的 WizardDirValue 是只读属性，
; 不能在 InitializeSetup 里赋值，所以用脚本化常量来预选旧路径。
DefaultDirName={code:GetDefaultDir}
DisableDirPage=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=dsh-pet-core-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\dsh-pet-core.exe
UninstallDisplayName=dsh-pet core

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; 以下 5 个官方 feature 默认选中；用户可以在安装向导取消，取消后不写入安装目录。
Name: "mod_divination"; Description: "抽签（fun.divination）"; GroupDescription: "随附扩展：不勾选就不会写进安装目录，之后随安装程序卸载"
Name: "mod_festival"; Description: "节日提醒（fun.festival）"; GroupDescription: "随附扩展：不勾选就不会写进安装目录，之后随安装程序卸载"
Name: "mod_todo"; Description: "待办清单（reminder.todo）"; GroupDescription: "随附扩展：不勾选就不会写进安装目录，之后随安装程序卸载"
Name: "mod_chime"; Description: "整点报时（voice.chime）"; GroupDescription: "随附扩展：不勾选就不会写进安装目录，之后随安装程序卸载"
Name: "mod_music"; Description: "音乐信息（media.music）"; GroupDescription: "随附扩展：不勾选就不会写进安装目录，之后随安装程序卸载"

[Files]
Source: "..\dist\dsh-pet-core\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 随附扩展：装到安装目录的 mods\ 下（卸载随安装目录一起删除），`.trusted`
; 标记表示「安装器授权的官方包」。用户导入的扩展仍装到用户数据目录。
Source: "..\examples\petcore-mods\fun.divination\*"; DestDir: "{app}\mods\fun.divination"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"; Tasks: mod_divination
Source: "trust_marker.txt"; DestDir: "{app}\mods\fun.divination"; DestName: ".trusted"; Flags: ignoreversion; Tasks: mod_divination
Source: "..\examples\petcore-mods\fun.festival\*"; DestDir: "{app}\mods\fun.festival"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"; Tasks: mod_festival
Source: "trust_marker.txt"; DestDir: "{app}\mods\fun.festival"; DestName: ".trusted"; Flags: ignoreversion; Tasks: mod_festival
Source: "..\examples\petcore-mods\reminder.todo\*"; DestDir: "{app}\mods\reminder.todo"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"; Tasks: mod_todo
Source: "trust_marker.txt"; DestDir: "{app}\mods\reminder.todo"; DestName: ".trusted"; Flags: ignoreversion; Tasks: mod_todo
Source: "..\examples\petcore-mods\voice.chime\*"; DestDir: "{app}\mods\voice.chime"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"; Tasks: mod_chime
Source: "trust_marker.txt"; DestDir: "{app}\mods\voice.chime"; DestName: ".trusted"; Flags: ignoreversion; Tasks: mod_chime
Source: "..\examples\petcore-mods\media.music\*"; DestDir: "{app}\mods\media.music"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"; Tasks: mod_music
Source: "trust_marker.txt"; DestDir: "{app}\mods\media.music"; DestName: ".trusted"; Flags: ignoreversion; Tasks: mod_music

[Icons]
Name: "{autoprograms}\dsh-pet core"; Filename: "{app}\dsh-pet-core.exe"
Name: "{autodesktop}\dsh-pet core"; Filename: "{app}\dsh-pet-core.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\dsh-pet-core.exe"; Description: "{cm:LaunchProgram,dsh-pet core}"; Flags: nowait postinstall

[Code]
function PreviousInstallDir(): String;
var
  Value: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8f0f2d4e-4f6c-4f7a-9b7c-1f0b6a2d9c31}_is1',
    'InstallLocation', Value) then
    Result := Value;
end;

function GetDefaultDir(Param: String): String;
var
  Previous: String;
begin
  Previous := PreviousInstallDir();
  if Previous <> '' then
    Result := Previous
  else
    Result := ExpandConstant('{localappdata}\Programs\dsh-pet-core');
end;
