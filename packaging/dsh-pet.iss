; -*- mode: ini -*-
; Generic dsh-pet-standalone onedir installer (Inno Setup 6)
;
; Compile (defaults build the webm-chat variant):
;   E:\tools\InnoSetup6\ISCC.exe packaging\dsh-pet.iss
;
; Other variants (override defines on the command line):
;   E:\tools\InnoSetup6\ISCC.exe /DMyAppShortName=dsh-pet-standalone-webm `
;       /DMyAppExeName=dsh-pet-standalone-webm.exe `
;       /DMyAppDir=..\dist-onedir\dsh-pet-standalone-webm `
;       /DMyAppId=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx `
;       /DMyAppDisplay="dsh-pet-standalone (WebM)" packaging\dsh-pet.iss
;
; Output: dist-onedir\<shortname>-setup.exe

#ifndef MyAppShortName
#define MyAppShortName "dsh-pet-standalone-webm-chat"
#endif
#ifndef MyAppExeName
#define MyAppExeName "dsh-pet-standalone-webm-chat.exe"
#endif
#ifndef MyAppDir
#define MyAppDir "..\dist-onedir\dsh-pet-standalone-webm-chat"
#endif
#ifndef MyAppId
; NOTE: value must include the double-brace escaping required by AppId ({{GUID})
#define MyAppId "{{3424d6cc-af3c-4383-8797-ab520b923aa6}"
#endif
#ifndef MyAppDisplay
#define MyAppDisplay "dsh-pet-standalone (WebM Chat)"
#endif
#ifndef MyAppVersion
; 默认版本与 pet/__init__.py 的 __version__ 一致；CI 构建时通过
; /DMyAppVersion=<版本> 从单一来源注入（见 build-windows.yml）。
#define MyAppVersion "4.3.0"
#endif

[Setup]
AppId={#MyAppId}
AppName={#MyAppDisplay}
AppVersion={#MyAppVersion}
AppPublisher=merzlin
; 安装包图标（待机封面帧生成，scripts/make_icon.py）
SetupIconFile=..\assets\icon.ico
; Per-user install, no admin needed; user may pick any drive in the wizard
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppShortName}
DisableProgramGroupPage=yes
OutputDir=..\dist-onedir
OutputBaseFilename={#MyAppShortName}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 在线更新会以静默方式覆盖现有 onedir；由 Inno 负责关闭占用文件的旧进程。
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
UninstallDisplayName={#MyAppDisplay}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; 5A：官方功能包选装。默认不勾选——Core 不带它们也能启动；勾选后安装到
; {app}\features\，由产品侧的 official_package_source 读取。删除/停用走应用内
; MOD 中心的事务链，安装器不另造安装状态。
Name: "official_ai_chat"; Description: "AI chat package (official)"; GroupDescription: "Official feature packages:"; Flags: unchecked
Name: "official_screen"; Description: "Screen understanding package (official)"; GroupDescription: "Official feature packages:"; Flags: unchecked
Name: "official_account_usage"; Description: "Account usage package (official)"; GroupDescription: "Official feature packages:"; Flags: unchecked
Name: "official_music"; Description: "Music launcher package (official)"; GroupDescription: "Official feature packages:"; Flags: unchecked
Name: "official_voice_chime"; Description: "Voice chime package (official)"; GroupDescription: "Official feature packages:"; Flags: unchecked
Name: "official_persona_phrases"; Description: "Persona phrases package (official)"; GroupDescription: "Official feature packages:"; Flags: unchecked
Name: "official_quick_launch"; Description: "Quick launch package (official)"; GroupDescription: "Official feature packages:"; Flags: unchecked

[Files]
; 基础产物：排除 features\ 下七个官方包，改由下面的 [Tasks] 选装项控制。
; portable.json 也排除：安装态必须走平台数据目录，构建树里的便携标记不许
; 被复制进安装目录（否则数据会写进 {app}，用户看不出区别）。
; skipifsourcedoesntexist 让不带包的构建（-FeaturePackages 省略）仍能编译。
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Excludes: "features\ai-chat\*,features\screen-understanding\*,features\account-usage\*,features\music\*,features\voice-chime\*,features\persona-phrases\*,features\quick-launch\*,portable.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MyAppDir}\features\ai-chat\*"; DestDir: "{app}\features\ai-chat"; Tasks: official_ai_chat; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#MyAppDir}\features\screen-understanding\*"; DestDir: "{app}\features\screen-understanding"; Tasks: official_screen; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#MyAppDir}\features\account-usage\*"; DestDir: "{app}\features\account-usage"; Tasks: official_account_usage; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#MyAppDir}\features\music\*"; DestDir: "{app}\features\music"; Tasks: official_music; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#MyAppDir}\features\voice-chime\*"; DestDir: "{app}\features\voice-chime"; Tasks: official_voice_chime; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#MyAppDir}\features\persona-phrases\*"; DestDir: "{app}\features\persona-phrases"; Tasks: official_persona_phrases; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#MyAppDir}\features\quick-launch\*"; DestDir: "{app}\features\quick-launch"; Tasks: official_quick_launch; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; skipifsilent：静默安装（更新器/CI/验收脚本）不替用户拉起 GUI；普通向导仍可勾选立即运行。
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppShortName}}"; Flags: nowait postinstall skipifsilent

; 注：这里刻意没有 `_MEI*` 的 [UninstallDelete]。
; 旧版有一条 `Type: filesandordirs; Name: "{app}\_MEI*"`，是按名字通配删除——
; `_MEI数字` 是 PyInstaller 的解包目录命名，安装目录里出现的同名目录并不保证是
; 本产品的（任何以本目录为工作目录启动的 onefile 程序都会在这里解包）。没有归属
; 证据就不删：本产品自己的 onefile 运行目录由 pet/runtime_cleanup.py 按归属标记
; 清理（见下方 [Code] 的卸载清理调用）。
; 唯一的 [UninstallDelete] 是首启回执：它由 [Code] 写，不在 Inno 的安装文件
; 日志里，不显式删会留下一个只剩该文件的安装目录。
[UninstallDelete]
Type: files; Name: "{app}\startup-receipt.json"

[Code]
{ 5A：首启回执。安装器只写“这次装了哪些官方包”，产品侧后续按它做首启确认；
  不在这里执行包代码，也不写安装状态。Inno 的字符串字面量保持 ASCII。}
procedure CurStepChanged(CurStep: TSetupStep);
var
  Receipt: String;
  AiChat: String;
  Screen: String;
  AccountUsage: String;
  Music: String;
  VoiceChime: String;
  PersonaPhrases: String;
  QuickLaunch: String;
begin
  if CurStep <> ssPostInstall then
    exit;

  { createallsubdirs 会为被 Excludes 的官方包留下空目录；未勾选时删掉（RemoveDir
    只删空目录，绝不会碰已安装的文件），让"没装"在盘上也真的没有 features\。}
  if not WizardIsTaskSelected('official_ai_chat') then
    RemoveDir(ExpandConstant('{app}\features\ai-chat'));
  if not WizardIsTaskSelected('official_screen') then
    RemoveDir(ExpandConstant('{app}\features\screen-understanding'));
  if not WizardIsTaskSelected('official_account_usage') then
    RemoveDir(ExpandConstant('{app}\features\account-usage'));
  if not WizardIsTaskSelected('official_music') then
    RemoveDir(ExpandConstant('{app}\features\music'));
  if not WizardIsTaskSelected('official_voice_chime') then
    RemoveDir(ExpandConstant('{app}\features\voice-chime'));
  if not WizardIsTaskSelected('official_persona_phrases') then
    RemoveDir(ExpandConstant('{app}\features\persona-phrases'));
  if not WizardIsTaskSelected('official_quick_launch') then
    RemoveDir(ExpandConstant('{app}\features\quick-launch'));
  RemoveDir(ExpandConstant('{app}\features'));

  { 回执写"盘上实际有什么"，不是"这次勾了什么"：升级时 Inno 会保留上一版由
    Setup 装下的包文件，仅按本次勾选写 false 会把已安装的包误报成未安装。}
  if FileExists(ExpandConstant('{app}\features\ai-chat\manifest.json')) then
    AiChat := 'true'
  else
    AiChat := 'false';
  if FileExists(ExpandConstant('{app}\features\screen-understanding\manifest.json')) then
    Screen := 'true'
  else
    Screen := 'false';
  if FileExists(ExpandConstant('{app}\features\account-usage\manifest.json')) then
    AccountUsage := 'true'
  else
    AccountUsage := 'false';
  if FileExists(ExpandConstant('{app}\features\music\manifest.json')) then
    Music := 'true'
  else
    Music := 'false';
  if FileExists(ExpandConstant('{app}\features\voice-chime\manifest.json')) then
    VoiceChime := 'true'
  else
    VoiceChime := 'false';
  if FileExists(ExpandConstant('{app}\features\persona-phrases\manifest.json')) then
    PersonaPhrases := 'true'
  else
    PersonaPhrases := 'false';
  if FileExists(ExpandConstant('{app}\features\quick-launch\manifest.json')) then
    QuickLaunch := 'true'
  else
    QuickLaunch := 'false';
  Receipt := '{"schema":"dsh-pet-startup-receipt/v1","ai_chat":' + AiChat +
             ',"screen":' + Screen + ',"account_usage":' + AccountUsage +
             ',"music":' + Music + ',"voice_chime":' + VoiceChime +
             ',"persona_phrases":' + PersonaPhrases +
             ',"quick_launch":' + QuickLaunch + '}';
  if not SaveStringToFile(ExpandConstant('{app}\startup-receipt.json'), Receipt, False) then
    Log('dsh-pet startup receipt could not be written');
end;

{ 卸载清理必须在删除 exe 之前跑：exe 一旦被删，清理实现就没了。
  usUninstall 是卸载流程里最早的步骤，此处的 Exec 先于文件删除。
  清理只删本产品 own 的东西（自启项 / Claude hooks / DSH 桥接插件），
  失败必须留痕：退出码写进卸载日志，交互式卸载还会弹一次提示。
  注：本 .iss 是 UTF-8 无 BOM（Inno 按 ANSI 读取），因此**字符串字面量只用 ASCII**，
  中文说明留在注释里；面向用户的详细结果由 Python 侧写进 uninstall-cleanup.log。}
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CleanupExe: String;
  WorkDir: String;
  ResultCode: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  CleanupExe := ExpandConstant('{app}\{#MyAppExeName}');
  if not FileExists(CleanupExe) then
  begin
    Log('dsh-pet uninstall cleanup skipped: executable not found: ' + CleanupExe);
    exit;
  end;
  { 工作目录先取系统临时目录：onefile 形态会用 --runtime-tmpdir 在当前目录解包，
    指到安装目录会在卸载过程中再造一个解包目录；TEMP 不可用时退回安装目录本身
    （它一定存在，因为 exe 就在那里）。}
  WorkDir := ExpandConstant('{%TEMP}');
  if (WorkDir = '') or (not DirExists(WorkDir)) then
    WorkDir := ExpandConstant('{app}');
  if Exec(CleanupExe, '--uninstall-cleanup', WorkDir,
          SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
      Log('dsh-pet uninstall cleanup finished (exit 0)')
    else
    begin
      Log('dsh-pet uninstall cleanup failed for some steps (exit '
        + IntToStr(ResultCode) + ')');
      SuppressibleMsgBox('dsh-pet uninstall cleanup did not fully succeed (exit code '
        + IntToStr(ResultCode) + '). Autostart, Claude hooks or the DSH bridge plugin'
        + ' may still be present; see uninstall-cleanup.log in the configuration'
        + ' directory for details.', mbError, MB_OK, IDOK);
    end;
  end
  else
  begin
    Log('dsh-pet uninstall cleanup could not start: ' + SysErrorMessage(ResultCode));
    SuppressibleMsgBox('Could not run the dsh-pet uninstall cleanup program: '
      + SysErrorMessage(ResultCode), mbError, MB_OK, IDOK);
  end;
end;
