---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: e1503192c50cbf4a9392ca071882b90f_d44cd8a3b12211f18039525400461939
    ReservedCode1: 5WS8ZIlf31sY8kOZGi3OuLj7wtTR4orlRD+uQa4vpN/zbG9icu3IcPiWHfrwX3FNAnkDwfOlDoaC6pO5on6QU9u6BhQY8Zvk9FgkMQ7xBy5xT9qvgmVNFq1i/Rd205JLy3QoCQjQoilIbKr0n59e8Zxm5NeUzvEkLeDmjfwJRUMj8DxzCVnfPdOP0Hs=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: e1503192c50cbf4a9392ca071882b90f_d44cd8a3b12211f18039525400461939
    ReservedCode2: 5WS8ZIlf31sY8kOZGi3OuLj7wtTR4orlRD+uQa4vpN/zbG9icu3IcPiWHfrwX3FNAnkDwfOlDoaC6pO5on6QU9u6BhQY8Zvk9FgkMQ7xBy5xT9qvgmVNFq1i/Rd205JLy3QoCQjQoilIbKr0n59e8Zxm5NeUzvEkLeDmjfwJRUMj8DxzCVnfPdOP0Hs=
---

# onedir 打包流水线（绿色版 zip + Inno Setup 安装包）

目标：**运行期零解压**——不再产生 `C:\...\Temp\_MEIxxxxxx` 缓存。

- onefile：每次启动把全部素材解压到系统临时目录；崩溃/强杀/断电残留；启动慢（GIF 版 800MB 每次全解压）
- onedir：直接从安装目录加载，任何盘都不产生 `_MEI`，启动快，卸载即净

## 一、构建 onedir + zip 绿色版

应用图标由待机封面帧生成（`python scripts/make_icon.py` → `assets/icon.ico`），
exe 与安装包共用；换形象后重新生成即可。

```powershell
# 全部变体：
#   webm-chat（默认）| webm | gif-chat | gif（GIF 变体加 -Gif 先生成 GIF 素材）
powershell -ExecutionPolicy Bypass -File scripts\build_onedir.ps1 -Variant webm-chat
```

产物：

```
dist-onedir\dsh-pet-standalone-webm-chat\          ← onedir 目录（绿色版 = 整个文件夹）
dist-onedir\dsh-pet-standalone-webm-chat-portable.zip
```

绿色版用法：解压 zip 到任意盘（E:\、D:\、U 盘均可），双击 exe 即用；无安装、无缓存。

### 随包携带的功能扩展包：`<app>\features\`（2026-10-14）

作者用 `scripts/build_mod_example.py` 打出来的功能包（目录或 ZIP）可以随包携带：

```powershell
# Windows（产物里落在 <app>\features\）
powershell -ExecutionPolicy Bypass -File scripts\build_onedir.ps1 -FeaturePackages <包根>
```
```bash
# Linux / macOS（--feature-packages <包根>；macOS 落在 .app/Contents/Resources/features/）
./scripts/build_linux.sh --feature-packages <包根>
./scripts/build_macos.sh --feature-packages <包根>
```

- **两道门，判据只有一份**：`python scripts/verify_feature_package.py --bundle-root <包根>`
  在 PyInstaller **之前**验源包根、在产物里再验一次拷贝（与 `verify_presentmon.py` 同款
  两道门的理由：`Copy-Item`/`cp` 出的那一份截断或漏件，运行期看不出来）。门做三件事——
  清单完整性、摘要校验（结构/兼容性/路径边界/逐文件摘要）、**装前子进程预检**；
  `--target-platform` 传**产物平台**（`win32` / `linux` / `darwin`），所以为别的平台声明的
  包在这里就会被点名拒绝。本地用户自选包按**显式用户信任**校验，这道门不做发布者认证
  （`manifest.sig` 存在也只被忽略，报告里给 `signature_ignored` 告警，`trust_status` 是
  `local_user`）。
- **包根的候选不猜**：根下**每个直接子目录**与**每个 `*.zip`** 都算一份候选（点开头的条目
  除外），没有 `manifest.json` 的子目录被如实报成 `route_rejected`；根下一条候选都找不到
  按失败处理（`bundle_empty`）——"根给错了"比"没坏包"更常见。
- **复制范围 = 验证范围**：构建脚本把包根**整目录**复制进产物，所以根里不许留非候选条目
  （点开头的、非 ZIP 的文件，`bundle_stray_entry`），也不许同一个 owner 有两份包
  （`bundle_duplicate_id`）——两条都在复制**之前**中止构建。要带别的文件，就先打成包。
- **诚实边界**：`<app>\features\` 是设计文档里"旁置 packages 根"在 onedir 树上的落法，
  **产品运行期今天没有读它的地方**——已安装的功能包住在用户配置根
  （`%APPDATA%\<变体名>\plugins\<owner>\`），安装/启停走 MOD 中心那条链
  （`docs/modding/PORT-STATUS.md`）。安装器侧的选装（Setup 内嵌官方 ZIP）与便携模式
  不在本轮范围，所以**不带 `-FeaturePackages` 的构建是正常构建，不代表功能扩展不可用**。
- 不给这两个开关时构建脚本一行都不碰功能包（没有任何门被跳过的问题：没有包要验）。

### 包体瘦身（默认开启，`-SkipSlim` 可关闭）

构建在 Qt runtime 复制之后、中文编码自检之前自动执行 `python scripts\slim_bundle.py`：

- **移除白名单**：Qt Quick/QML 栈（`Qt6Quick` / `Qt6Qml*`）、`Qt6VirtualKeyboard` + 平台输入法插件、`Qt6OpenGL`、`Qt6Pdf` + `qpdf.dll` 图像插件、`opengl32sw.dll`、非中英 `*.qm` 翻译（保留 12 个中英）、PIL `_avif` 扩展 —— 合计 124 文件 / 53 MB；
- **安全校验**：移除前做依赖闭包校验（pefile 反向 import 检测，保留的二进制若仍引用待删文件即中止）与必需清单校验（核心运行文件齐全），任一失败即中止构建；
- **效果**：onedir 目录 309 MB → 256 MB，portable zip 176.2 MB → 146.5 MB（−12.8%）；
- 后续需要完整 Qt 栈（例如启用 QML 界面）时加 `-SkipSlim`；
- 冒烟建议：把配置切到 `voice_chime_schedule=every_minute` 启动 exe，确认 `%APPDATA%\dsh-pet-standalone-<variant>\voice_chime_cache` 新增 mp3（edge-tts 合成落盘），验证完恢复配置。

### 随包分发的第三方二进制：`resources/presentmon/`

游戏帧率段（灵动岛 `fps`）的读数是桌宠**起一个独立子进程**跑官方 PresentMon 拿到的，
程序本体随 Windows 包分发：

| 文件 | 说明 |
|---|---|
| `resources/presentmon/PresentMon-2.6.0-x64.exe` | 上游 v2.6.0 release 的独立控制台程序（x86-64），sha256 `b2a706bc…f1af`，980320 字节 |
| `resources/presentmon/LICENSE.txt` | 同一 release 源码树里的 MIT 许可原文（逐字节相同），随二进制一起进包 |

- **只 Windows**：`--add-data` 只写在 `scripts/build_onedir.ps1`，四个 Windows 变体
  （webm / webm-chat / gif / gif-chat）都带；`scripts/build_linux.sh` 与
  `scripts/build_macos.sh` 不加载也不捆它（`tests/test_presentmon_packaging.py` 钉住）。
  非 Windows 平台上 `pet/game_fps.py` 整段按「不支持」呈现。
- **架构只有 x86-64**：上游 release 里 x64 与 ARM64 是两个资产，产品只支持 x64，
  构建门会校验 PE 头里的机器类型（ARM64 二进制混进来即中止）。没有也不要有 arm64 变体。
  **运行期也判架构**（`game_fps.platform_problem`：读 `PROCESSOR_ARCHITECTURE` /
  `PROCESSOR_ARCHITEW6432`，ARM64 与其它架构按 `unsupported` 降级并说明「ARM64 未验证」）
  ——构建期那道门只管"包里是哪个二进制"，管不了"跑在什么机器上"。
- **两道门**（都在 `scripts/build_onedir.ps1` 里，非零即中止构建）：
  1. PyInstaller **之前**：`python scripts\verify_presentmon.py` 校验源目录里的文件；
  2. **产物里**：`python scripts\verify_presentmon.py --path <app>\_internal\resources\presentmon\<exe>`
     再验一次——`--add-data` 在源目录缺失时一个错都不报，产物会静默少一个后端，而
     界面看不出来（那一段只按「缺少内置采集程序」呈现，功能永远不出数）。
  判据只有一份，来自 `pet/game_fps.py` 的 `BACKEND_EXE_NAME` / `REQUIRED_SHA256`；
  本目录、构建脚本与验证脚本都不再写第二份字面量。
- **升级 PresentMon**：换 exe 后同时改 `pet/game_fps.py` 的 `BACKEND_EXE_NAME` /
  `REQUIRED_SHA256` / `SOURCE_TEXT`、本节的表格与 `THIRD_PARTY_NOTICES.md` 第 6 节。
  文件名自带版本号，就是为了不让「同名不同版」成为静默替换。
- **手工取得（换机 / 升级时）**：`curl -L -o resources/presentmon/PresentMon-2.6.0-x64.exe <release 资产 URL>`，
  然后 `python scripts/verify_presentmon.py` 自证；许可文本从同一 release 的源码树取
  `LICENSE.txt`。构建过程本身**不联网**：仓库带二进制，CI 与干净克隆才能离线复现，
  这也是本仓库对「构建必需二进制」的既有处置方式（同 `assets/icon.ico`）。

### 游戏帧率的采集权限（不随包分发任何提权组件）

PresentMon 的 ETW 会话只对管理员或 `Performance Log Users`（SID `S-1-5-32-559`）成员
开放。**包里没有提权助手**：2026-10-11 的「按需 UAC 独立助手」（`resources/fps-helper/`、
`native/fps_helper/`、`scripts/build_fps_helper.ps1`、`verify_fps_helper.py`）已整体归档到
`.scratch/product-fps-uac-20261011/archived-uac-helper/`，`build_onedir.ps1` 不再编译、校验或
打包它。

- **权限怎么拿**：设置页灵动岛帧率段的「授予采集权限…」按钮（`pet/fps_permission.py`），
  弹**一次**系统管理员授权窗口，把当前账户加入该组；桌宠本体始终普通权限运行。
  组成员关系只进**新登录令牌**，所以需要注销并重新登录后生效。
- **打包侧影响**：只用系统自带的 `powershell.exe` / `whoami.exe`，**不新增任何随包文件**，
  构建管线不变。
- **没验证的**：真实提权加组、重新登录后真实 ETW 会话、任何真实帧读数（本机从未执行）。
  口径见 [`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md) 2026-10-12 条。

## 二、Inno Setup 安装包（正式分发）

本机已装：`E:\tools\InnoSetup6\ISCC.exe`（便携模式，免管理员）。
通用脚本 `packaging\dsh-pet.iss` 用 `/D` 定义编译任意变体：

```powershell
# webm-chat（脚本默认值）
E:\tools\InnoSetup6\ISCC.exe packaging\dsh-pet.iss

# webm
E:\tools\InnoSetup6\ISCC.exe /DMyAppShortName=dsh-pet-standalone-webm /DMyAppExeName=dsh-pet-standalone-webm.exe /DMyAppDir=..\dist-onedir\dsh-pet-standalone-webm "/DMyAppId={{ED2590E4-A968-4E8D-B7C4-75DFE012D0E9}}" "/DMyAppDisplay=dsh-pet-standalone (WebM)" packaging\dsh-pet.iss

# gif-chat
E:\tools\InnoSetup6\ISCC.exe /DMyAppShortName=dsh-pet-standalone-gif-chat /DMyAppExeName=dsh-pet-standalone-gif-chat.exe /DMyAppDir=..\dist-onedir\dsh-pet-standalone-gif-chat "/DMyAppId={{7FE1EEDD-91DB-4F4B-834D-894DFE782256}}" "/DMyAppDisplay=dsh-pet-standalone (GIF Chat)" packaging\dsh-pet.iss

# gif
E:\tools\InnoSetup6\ISCC.exe /DMyAppShortName=dsh-pet-standalone-gif /DMyAppExeName=dsh-pet-standalone-gif.exe /DMyAppDir=..\dist-onedir\dsh-pet-standalone-gif "/DMyAppId={{308454BF-3FD5-4A30-B0FF-1D23BF31DCF1}}" "/DMyAppDisplay=dsh-pet-standalone (GIF)" packaging\dsh-pet.iss
```

产物：`dist-onedir\<shortname>-setup.exe`

安装包特性：

- 免管理员（`PrivilegesRequired=lowest`），默认装 `%LOCALAPPDATA%\Programs\...`，向导中**用户可自行选择任意盘符**
- 创建开始菜单/桌面快捷方式；装完可选立即运行
- 控制面板可卸载；卸载时在删除 exe **之前**调用 `--uninstall-cleanup`（自启项 /
  Claude hooks / DSH 桥接插件），退出码与失败记录见 `[Code]` 段与配置目录里的
  `uninstall-cleanup.log`。安装目录里的 `_MEI*` **不再按名字通配删除**（见第五节）
- 语言：简体中文 + English

## 三、冒烟验证清单

1. 启动 `dist-onedir\<name>\<name>.exe`，8 秒后确认进程存活
2. **系统临时目录无新增 `_MEI*`**（onedir 根本不解压）
3. exe 同目录无 `_MEI*` 残留
4. 退出后进程全部结束
5. `_internal\resources\presentmon\` 下有采集后端与它的 `LICENSE.txt`（构建期已自动校验
   名称 / sha256 / x86-64，见上面「随包分发的第三方二进制」）
6. `_internal\resources\` 下**没有** `fps-helper\`（提权助手已归档，不随包）
7. **FPS 开关打开、当前账户不在 `Performance Log Users` 组时**：岛上那段不显示任何数字，
   而是采集链路自己的权限原文；设置页帧率段出现「授予采集权限…」按钮
   （本机没有验证过真实加组后的采集，见上面「游戏帧率的采集权限」）

## 四、无 Chat 变体兼容性

无 Chat 入口使用 `packaging/pet_entry_no_chat.py`，构建规格明确排除 `pet.chat`
和 `keyring`。配置仍可能来自曾经启用 Chat 的用户目录，因此运行时
`Config._migrate_plaintext_keys_to_keyring()` 对缺失的 `pet.chat` 只跳过迁移，
不能让配置加载失败；除该明确缺失模块外的导入错误仍应抛出。

打包验收至少包含：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q tests/test_chat_subsystem.py::test_no_chat_packaging_uses_isolated_entrypoint
python -m pytest -q tests/test_config_key_migration.py
```

## 五、注意事项

- **开机自启**：onedir 不需要 `start /D` 切目录（无解压），`pet/autostart.py` 现有命令无害可保留
- **`_MEI` 遗留清理按归属，不按名字**：`pet/app.py` 启动时仍调用
  `_cleanup_stale_runtime_dirs`，但 `pet/runtime_cleanup.py` 现在的候选前提是本产品
  自己的归属标记（`_MEIPASS` 里的 `.dsh-pet-runtime-owner`，两个冻结入口启动时写）：
  名字（`_MEI数字`）+ 年龄只用于筛选，**没有标记的目录一个字节都不动**——系统 Temp
  里的同名目录属于别的 PyInstaller 应用，按名字通配删除等于清别人的解包资源。
  链接/junction/重解析点不跟随，删除前复核归属与身份（防扫描与删除之间的替换）。
  因此**旧 onefile 版本留下的 `_MEI`（无标记）不会被自动清理**：这是刻意的安全降级，
  要清就人工确认后删。卸载侧同理：ISS 已去掉 `{app}\_MEI*` 通配条目
- **冻结入口的参数分流**：`--uninstall-cleanup` 与 `--settings` 都在 `import pet.app`
  之前分流（否则会拉成一只完整桌宠）；卸载清理的退出码非 0 时，卸载日志记录退出码，
  交互式卸载还会弹提示，结果同时追加到配置目录的 `uninstall-cleanup.log`
- **本机遗留旧自启项**：注册表 `HKCU\...\Run` 里的 `DesktopPet = E:\software\AI\AI的有用工具\打字统计\dist\DesktopPet.exe` 是 7 月的旧 onefile 构建（无 `start /D`、解压在 C 盘 Temp），建议删除或替换，避免开机双桌宠 + 继续污染 C 盘
- GIF 变体体积大（800MB+），zip/安装包较慢；WebM 变体约 124MB

## 六、CI 验证与三端手动构建（2026-10-11）

### 手动运行三条构建工作流

`build-windows.yml` / `build-macos.yml` / `build-linux.yml` 都支持
Actions → *Run workflow* 手动运行，两个输入：

| 输入 | 默认 | 作用 |
|---|---|---|
| `source_ref` | 空 | 要构建的 ref/SHA。留空 = 触发本 workflow 的 ref（事件默认检出）。三端对齐同一棵树时三端填**同一个提交** |
| `upload_artifacts` | `false` | 是否把产物上传为 Actions artifact。手动默认**不上传**（不往公共仓库堆大产物）；`v*` tag 推送始终上传 |

手动运行**不会**创建或改写 Release：`Publish Release` 只在 `push` + `refs/tags/` 时执行，
tag 推送的既有发布行为不变。每个工作流会把「这次构建的是哪棵树 + 装了什么」写进 run
summary（`git rev-parse HEAD`、`github.sha`、`python --version`、`node --version`、
`pip freeze`）——三端 artifact 对不对得上，看这一步的 SHA。

`pr-test.yml` 同样是 PR/push/手动三种触发：手动运行也有 `source_ref`，用于三端跨平台
对齐同一棵树。**PR 事件仍检出合并提交**（`refs/pull/N/merge`，见 run summary 里同时
记录的 head sha 与 merge sha）——"集成后才有红绿判定"的语义不为对齐需求让步。

### 帧序列素材在 CI 里怎么来

`assets/characters/<角色>/frameseq/` 是刻意不入库的派生产物（`.gitignore`），干净检出里
必然没有；而构建对素材整树拷贝 `assets/characters`（缺了不报错）。因此三条 build
工作流在构建前都会跑一次：

```bash
python scripts/prepare_frameseq_bundle.py --character shenshen
```

顺序是「先验证 → 缺才转 → 转完再验」：素材已完整（缓存命中）直接跳过转换；不完整才跑
`tools/convert_frameseq.py --character shenshen --include random,events`（`--include`
不可省：该 CLI 默认只转热集 11 段，而构建门要**全树 106 段**），全量冷转约 28 min。
两个变体共用这一次素材准备，不重复转。

- **缓存**：`actions/cache` 缓存 `assets/characters/*/frameseq`，key 由
  `python scripts/prepare_frameseq_bundle.py --print-cache-key` 算出 = 源 webm 摘要 +
  转换器/供给实现摘要 + 当前编码档 + 平台/Python/Pillow/imageio-ffmpeg 版本。命中即近零
  成本；**坏缓存不会被盲跳过**（唯一放行依据是验证器的真实退出码，陈旧档 / 半成品世代
  目录 / 源身份不符都会被判红并触发重转）。
- 缓存内容是**本仓库公开源素材的派生物**，不含任何 secret，也不是发布产物。
- **硬门在脚本里，不在 workflow 里**：`scripts/build_onedir.ps1`（非 GIF 变体）、
  `scripts/build_macos.sh`、`scripts/build_linux.sh` 都在 PyInstaller 起跑前调用
  `scripts/check_frameseq_bundle.py`，非零即中止构建。GIF 变体跳过本门：它打包
  `assets/characters_gif`（`convert_to_gif.py` 直出），没有 frameseq 这一层。
  本地构建与 CI 因此是同一口径。

### 本批未覆盖（如实）

CI 这一层只做了 test/build 门与元数据记录：**没有**新增启动/退出冒烟
（`--uninstall-cleanup` 会动 hooks 与注册表，不当冒烟用），启动与退出验证仍是实机欠项。
macOS / Linux 的真实构建必须在对应 runner 上跑过才算通过——本机（Windows）只验证了
工作流的静态结构、shell 脚本语法与素材供给入口的真实命令行为。

*（内容由AI生成，仅供参考）*
