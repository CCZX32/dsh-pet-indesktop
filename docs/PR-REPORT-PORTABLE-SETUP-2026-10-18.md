# 便携模式 + 5A Setup 编译与安装验收（2026-10-18）

> 基线：分支 `dlc/mod-center-port`，起点 `9f641c9`（阶段 4 收尾）。
> 本轮目标（用户 2026-10-18 决定）：安装 Inno Setup 6 → 编译 `packaging/dsh-pet.iss`
> 并做装/卸/升级验收；**本轮不做签名**；**便携模式进入发布线**。
> 本文只记录实际跑过的结果；没跑的能力在「边界与未验证」里如实列出。

## 0. 结论

- Inno Setup 6.7.3 已装（`winget install JRSoftware.InnoSetup`，用户级），
  `ChineseSimplified.isl` 从 jsDelivr 镜像取回；`packaging/dsh-pet.iss` **编译成功**
  （122.5 s，产物 587,036,763 bytes）。
- 静默安装矩阵四项全过：不选官方包 / 两个都选 / 升级（先 AI 后仅识屏）/ 卸载。
  首启回执与实际盘上内容一致；未勾选时不留下空的 `features\` 目录；
  卸载后安装目录消失；安装态数据写在隔离 APPDATA，安装目录里不产生 `data\`。
- 显式便携已落地：`portable.json`（exe 同级）→ 数据根 = 标记目录；
  便携 zip 根目录带 canonical 标记；冻结 onedir 实测把 `settings.lock` 写进
  `<exe>\data\`，隔离 APPDATA 保持为空。
- 签名（Authenticode / 离线 Ed25519 发布清单）按用户决定**本轮不做**，
  未生成任何签名产物。

## 1. 修改文件说明

新增：

| 文件 | 行数 | 改了什么 + 为什么 |
|---|---|---|
| `pet/runtime_layout.py` | 239 | 便携布局唯一解析点：标记读取/schema 校验、相对路径与逃逸检查、reparse point/NFTS/可写探针、进程内缓存（负结果也缓存）。安装态返回平台数据目录/变体名，便携态返回标记目录。 |
| `scripts/write_portable_marker.py` | 74 | 构建脚本把 canonical `portable.json` 追加进便携 zip（或目录）；已存在同内容视为幂等成功，内容不同则报错退出，避免静默改语义。 |
| `tests/test_runtime_layout.py` | 284 | 标记契约红绿用例：合法/嵌套路径、缺标记、空/绝对/`..`/盘符、坏 JSON/schema、标记目录、data 是文件、reparse、非 NTFS、不可写、`Config` 与设置进程路径、负缓存、zip 脚本。 |
| `docs/PORTABLE-MODE-2026-10-18.md` | 92 | 便携合同：两种布局、标记格式、校验规则、跟随便携根的路径、不跟的 OS 级契约、打包边界、未验证项。 |

修改（`git diff --numstat`，+ 新增 / − 删除）：

| 文件 | +/− | 改了什么 + 为什么 |
|---|---|---|
| `pet/config.py` | +17/−4 | `Config.dir` 改走 `runtime_layout.app_data_dir()`：便携态=标记目录，安装态仍 `base/APP_DIR_NAME`；便携不做 `%APPDATA%` 旧数据迁移。`_default_base()` 保持纯 OS 推导与测试注入口径。 |
| `pet/app.py` | +9/−2 | `config_dir` 用同一解析；`PortableLayoutError` 在启动期捕获后弹错误框并退出（不静默回退）。 |
| `pet/__main__.py` | +8/−1 | `--settings` 进程构造 `Config` 时捕获布局错误并弹框退出，避免设置进程在坏标记下继续跑。 |
| `pet/overlay_settings_command.py` | +11/−5 | 拓扑门读主配置的路径改为便携感知；安装态仍按模块级 `_default_base`/`APP_DIR_NAME` 拼，保留测试注入。 |
| `pet/catalog.py` | +7/−4 | 外部角色目录用 app 数据根；便携态不再读 `%APPDATA%` 旧目录。 |
| `pet/click_sound.py` | +13/−6 | 音效缓存在便携态落 `<portable>/sounds_cache`；安装态保持 QStandardPaths；无标记热路径不做 resolve。 |
| `pet/music_lyric.py` | +3/−3 | 歌词缓存跟随 app 数据根。 |
| `pet/island_extension_host.py` | +4/−4 | 灵动岛用户扩展根跟随 app 数据根。 |
| `pet/harness_launcher.py` | +4/−11 | harness 探测缓存跟随 app 数据根；删掉旧的 APPDATA 兜底（坏标记不再静默回退）。 |
| `scripts/build_onedir.ps1` | +15/−1 | 便携 zip 默认写 `portable.json`（`-NoPortableMarker` 可关）；顶部说明便携语义。 |
| `packaging/dsh-pet.iss` | +23/−5 | ①基础复制排除 `portable.json`（安装态绝不继承便携标记）；②`[Run]` 加 `skipifsilent`（静默安装不拉起 GUI）；③`[UninstallDelete]` 只删自写回执；④未勾选 Task 时删掉 `createallsubdirs` 留下的空 `features\` 目录；⑤回执改为按盘上 `manifest.json` 实际存在写 true/false（升级保留旧包时不误报）；⑥`WizardIsTaskSelected` 替换已改名的 `IsTaskSelected`。 |
| `tests/test_setup_optional_features.py` | +36/−4 | 结构判据：回执/排除/任务、静默不启动、卸载删回执、未选不留空目录、回执按盘上内容。 |
| `docs/ONEDIR_PACKAGING.md` | +17/−5 | ISCC 实际安装路径与语言文件来源；便携 zip 标记语义；安装包选装/回执特性。 |
| `docs/INDEX.md` | +1 | 登记便携合同文档（新文档入场规则）。 |

## 2. 性能分析

环境：Windows，Python 3.12（`.venv`），同机实测；数值为进程内 `timeit`。

| 场景 | 实测 | 说明 |
|---|---|---|
| 安装态（无标记）一次解析 | **16.3 µs/call**（3000 次） | 只做一次 `exists()`；每个进程只付一次 |
| 便携态一次解析（含 NTFS 查询 + mkdir + 可写探针） | **2.764 ms/call**（300 次） | 只在启动/首次取数据根时发生 |
| 缓存命中 `portable_layout()` | **0.046 µs/call**（200,000 次） | 负结果同样缓存（回归用例锁定） |

- 稳态开销：启动后所有数据根调用走缓存，0.046 µs/次，相对配置读写可忽略。
- 新增路径成本：无标记 16.3 µs（一次）；便携 2.764 ms（一次，含建目录与写探针）。
- 新增系统调用/磁盘/线程/网络：便携启动新增 1 次卷信息查询、1 次 mkdir、1 次
  临时文件创建+删除；**无新线程、无网络**。安装态只新增 1 次 `exists()`。
- 内存：新模块只 import 标准库（`json/os/stat/sys/tempfile/dataclasses`），
  无第三方依赖、无模块级大对象；缓存只保存一个小 dataclass 或 `None`。
- 包体：便携 zip **666,767,089 bytes（635.9 MiB）/ 26,752 条目**，标记 48 bytes；Setup
  **587,036,763 bytes**，编译 **122.469 s**（lzma2 solid）。标记对体积无可见影响。

## 3. 实机运行记录

### 3.1 工具链安装

```text
winget install --id JRSoftware.InnoSetup --exact --silent ...
Found Inno Setup 6 [JRSoftware.InnoSetup] Version 6.7.3
Successfully installed
# 实际路径（用户级）：
C:\Users\26102\AppData\Local\Programs\Inno Setup 6\ISCC.exe
# 官方装不带 ChineseSimplified.isl；raw.githubusercontent.com 本机解析到 127.0.0.1，
# 改从 jsDelivr 镜像取同名文件（21516 bytes）放进 Languages\。
```

### 3.2 编译

```text
> "$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" packaging/dsh-pet.iss
Successful compile (122.469 sec). Resulting Setup program filename is:
E:\Work\dsh-pet\dsh-pet-indesktop\dist-onedir\dsh-pet-standalone-webm-chat-setup.exe
# 587,036,763 bytes
# 无 Warning/Error（IsTaskSelected 改名提示已消除）
```

日志：`.scratch/iscc-build-8.log`。

### 3.3 安装/卸载/升级矩阵（静默，隔离 APPDATA）

脚本：`.scratch/setup-gate.ps1`；日志：`.scratch/setup-gate-4.log`（最终 Setup）。
每个安装都用 `/DIR=<gate>\<case>` 隔离目录；`APPDATA` 指向 `<gate>\appdata`；
只备份/恢复了一个真实自启值（卸载清理会删 `dsh-pet-standalone-webm-chat` 的 Run 项）。

| 用例 | 结果 |
|---|---|
| 不选官方包 | install exit 0；exe 存在；`features` **不存在**；无 `portable.json`；回执 `ai_chat=false, screen=false` |
| 安装态数据根 | 隔离 APPDATA 下出现 `dsh-pet-standalone-webm-chat\settings.lock`；安装目录内 `data` **不存在** |
| 两个官方包都选 | install exit 0；`features\ai-chat\manifest.json`、`features\screen-understanding\manifest.json`、`worker\entry.exe` 均存在；回执 `true/true` |
| 卸载（两个包） | uninstall exit 0；**安装目录消失**（`dir_exists=False`） |
| 升级：先 AI，再仅识屏 | 第一次后 `ai=True screen=False`；第二次后 `ai=True screen=True`（**升级保留上一版装下的包**，与设计口径一致）；回执 `ai_chat=true, screen=true`（按盘上实际内容写） |
| 卸载（升级目录） | exit 0；目录消失 |
| 卸载（不选包目录） | exit 0；目录消失 |
| 卸载清理 | `uninstall-cleanup.log` 两次均 `exit=0`，`autostart/claude_hooks/dsh_bridge = ok` |
| 自启值恢复 | 脚本 finally 已把真实 Run 值写回 |

### 3.4 便携（冻结 onedir）

```text
# zip 根目录标记（26752 条目）
entries: 26752
has exe: True
has marker: True
marker: {"schema":"dsh-pet-portable/v1","data":"data"}
```

冻结产物实测（`.scratch/portable-gate.ps1`）：把 canonical `portable.json` 放到
`dist-onedir\dsh-pet-standalone-webm-chat\`，隔离 `APPDATA` 后启动 `--settings`：

```text
settings.lock exists: True
portable data contents:
  .config-write.lock 0
  settings.lock 79
isolated APPDATA entries:
  <empty>
process exited: True
```

即：数据写进 `<exe>\data\`，隔离的 `%APPDATA%` 完全为空。
测试后已删除该目录里的 `portable.json` 与 `data\`，构建树保持安装态。

### 3.5 自动化门

```text
.venv\Scripts\python.exe -m ruff check pet tests scripts
All checks passed!

.venv\Scripts\python.exe -m pytest -q \
  tests/test_runtime_layout.py tests/test_setup_optional_features.py \
  tests/test_overlay_settings_command.py tests/test_click_sound.py \
  tests/test_config_instance.py tests/test_music_lyric.py \
  tests/test_island_extension_host.py tests/test_harness_launcher.py \
  tests/test_mod_catalog.py
352 passed in 13.42s
```

全量分片门：`python scripts/ci_shards.py --include-isolated --jobs 6` →
**21/21 分片通过，墙钟 531.8 s**（主套件 433 文件 / 8965 用例；日志
`.scratch/final-full-shards-11.log`）。

**中途红过的两处（都是本次改动自伤，已修）**：

- `tests/test_final_cleanup_boundaries.py::test_iss_uninstall_runs_cleanup_before_removing_files`
  原来断言“任何 `[UninstallDelete]` 都不许有”。本轮新增了一条**只删自写回执**的
  定向条目，判据改为“恰好一条且内容必须是 `startup-receipt.json`，`_MEI*` 仍禁止”。
- `tests/test_packaging_keyring_notices.py::test_windows_build_script_keeps_its_utf8_bom`
  编辑 `scripts/build_onedir.ps1` 时丢了 UTF-8 BOM；已按原字节恢复（PowerShell 5.1
  在无 BOM 时按 ANSI 读中文脚本）。

**已知 flake（不是本次缺陷）**：`tests/test_proactive_worker_adapter.py::test_full_chain_watcher_through_the_real_worker_to_a_local_vision_endpoint`
在一次 6 路并发的隔离复跑里报 `worker_stopped`。该文件单独复跑 37 passed；
4 份**并发**复跑全部 exit 0。属交接文档已登记的 proactive/worker 握手时序族。

## 4. 边界与未验证

- **签名**：用户明确本轮不做；没有 Authenticode 证书，也没有 Ed25519 发布清单。
- **干净机器/新账户**：安装矩阵在本机当前用户下完成，未在新 Windows 账户或干净 VM 复跑。
- **向导 UI**：全部用 `/VERYSILENT` 安装；没有人工点击向导的 Task 页面做视觉验收
  （结构判据 + 静默装出的盘上状态已覆盖语义）。
- **其它变体**：只编译/验收了 `webm-chat`；`webm`/`gif-chat`/`gif` 未编译。
- **升级语义**：Inno 升级会保留上一版由 Setup 装下的官方包文件；Setup 没有"反选即卸载"
  的入口（卸载包走应用内 MOD 中心）。回执按盘上实际内容写，避免误报。
- **便携介质**：只在本机 NTFS 验证；exFAT/FAT 拒绝、只读介质、跨机器/换用户
  未实机验收（exFAT 判据由单测用 monkeypatch 覆盖）。
- **便携数据迁移**：不自动从 `%APPDATA%` 导入旧数据（显式模式的设计选择）。
- **`startup-receipt.json` 的产品侧消费**：本轮只保证安装器写出、卸载删除；
  Core 首次启动读取/确认回执属于 Phase 5B 的下一片（见交接文档）。
- **冻结 Worker 完整租约链**：仍未做端到端人工验收（沿用阶段 4 登记）。
