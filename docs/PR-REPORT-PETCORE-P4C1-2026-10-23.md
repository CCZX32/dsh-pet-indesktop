# P4-c1 交付报告：窗口级抓屏 + `ai.chat` 主动识屏（2026-10-23）

> 分支 `feat/petcore-vpet-architecture`；批次 P4-c1（P4-c 的前半，c2 = `ai.agent`，
> c3 = 提醒域转正，均未开始）。契约与红线见 `docs/PETCORE-SPEC.md` §26、
> `docs/PETCORE-MOD-FORMAT.md` §14、`petcore/AGENTS.md`「窗口抓屏只在 core」段。

## 1. 修改文件说明

| 文件 | 增/删 | 做了什么 & 为什么 |
|---|---|---|
| `petcore/platform/foreground.py` | +98/−4 | 前台窗口元数据补 `hwnd` 与 `rect`（DWM 扩展边框优先、`GetWindowRect` 兜底），加 `DWMWA_CLOAKED` 过滤（UWP 幽灵窗口会抓到别的内容）；新增 `idle_seconds()`（`GetLastInputInfo`，非 Windows 返回 0）。主动识屏要「哪个窗口 + 在哪 + 用户是否离开」。 |
| `petcore/platform/image_hash.py` | 新增 60 | 64 位 dHash（9×8、相邻比较）+ `hamming_distance()`。先缩到 9×8 再转灰度：等价结果、成本从 9.87 ms 降到 1.58 ms（1200×800）。平滑重采样而非最近邻——最近邻会让相邻帧因采样位置抖动产生假「画面变化」，白花额度。 |
| `petcore/platform/screenshot.py` | +150/−1 | Windows 上用 GDI `BitBlt`/`StretchBlt` 按窗口**物理像素矩形**直接抓（`_grab_desktop_rect`），非 Windows 退回 Qt 抓屏裁剪。两段式：`sample_window()`（缩到 192 边只出指纹、不编码 PNG）与 `capture_window()`（长边 ≤768 + PNG + `dh_hash`）；窗口大半在屏外判 `outside_screen`；`grabber=` 只给测试注入。**这是本批最重要的返工**：初版按 `devicePixelRatio` 对物理矩形再乘一次，在本机 150% 缩放下裁剪只剩 24%，功能 100% 不工作。 |
| `petcore/contracts/screen.py` | +55 | `ScreenCapture` 追加 `hwnd/dh_hash`（带默认值，按位置构造的旧代码不受影响）；新 `WindowInfo` 与 `WindowSample`（轻量指纹，无 PNG）；`ScreenPort` 增 `foreground_window()`、`sample_foreground()`、`capture_foreground(expected_hwnd=)`，docstring 写明「双复核 + 只存内存 + 日志不记标题正文」。 |
| `petcore/contracts/host.py` | +11/−1 | `SystemPort.idle_seconds()`；`ConfigPort.set()`（注释限定：只给菜单勾选/命令切换这类显式用户动作）。 |
| `petcore/ui/ports.py` | +110/−1 | `QtScreenPort` 实现三个窗口方法（前后各查一次前台 `hwnd`，切走返回 `None`）；新 `SystemAdapter`（屏幕枚举/平台名/闲置秒数）并接进 `build_ports(system=...)`——此前 `HostPorts.system` 从未装配；`QtConfigPort.set()` 写全局配置并立即落盘。 |
| `petcore/config.py` | +64 | 12 个 `ai_proactive_*` 键：默认值、范围钳制、白名单清洗（去空行、截 120 字、最多 50 条），全部进 `GLOBAL_CONFIG_KEYS`（全局面，子宠不覆盖）。 |
| `petcore/menu_templates/petcore-default-v1.json` | +1 | 在「看看屏幕」后插入 `ai.chat:proactive` 节点。 |
| `petcore/ui/menu_layout.py` | +1 | `BUILTIN_DEFAULT_LAYOUT` 同步。旧布局**不需要**新的迁移函数：`_merge_template_actions()` 会按模板把已注册项补到锚点并写回（诊断 `default-action-added:ai.chat:proactive`），重复执行幂等。 |
| `examples/petcore-mods/ai.chat/host/proactive.py` | 新增 450 | 纯逻辑 + 看门狗：`match_whitelist`（大小写不敏感 fnmatch，`title:` 只匹配标题）、`dwell_satisfied`、`ProactiveLimiter`（状态文件原子写；日上限/最小间隔/冷却/3 次失败当日熔断）、`ProactiveWatcher`（`call_every(8000)`；每 tick 现读配置；稳态只 `sample_foreground()`、变化后才 `capture_foreground()`；基线固定用采样指纹；代次作废迟到回调；dry-run 只记 `process/hwnd/dhash`；关掉开关后迟到的答复也不再冒泡；请求 180 秒不回调则自愈清忙碌）。 |
| `examples/petcore-mods/ai.chat/host/runtime.py` | +71/−17 | 新命令 `proactive_toggle`；`proactive_cue/ask/answer`；`_start_vision()` 增加 `on_fail`；`_record_look()` 从 `_look_done` 抽出复用（保证主动识屏与「看看屏幕」同一会话口径）；`start/stop` 接管看门狗。 |
| `examples/petcore-mods/ai.chat/host/settings_page.py` | +327/−1 | 「主动识屏」H3 分节：启用、白名单编辑器 +「从当前前台窗口添加…」（3 秒采样，按软件/按标题关键词二选一）、停留、变化阈值、日上限、冷却、最小间隔、仅闲置 + 闲置门槛（未勾选时该行置灰）、dry-run、先兆气泡、同步会话；`_sync_proactive()` 让「取消」把控件拉回快照；搜索关键词补 12 个。 |
| `examples/petcore-mods/ai.chat/host/__init__.py` | +22/−1 | 菜单贡献 `proactive`（`checked` 读配置，勾选态可见）。 |
| `tests/test_petcore_proactive.py` | 新增 470 | 20 条：白名单 6 种、停留、Hamming、限额（日上限/间隔/冷却/跨日/熔断/持久化）、看门狗（停留、窗口切换、相似帧、真实变化、dry-run 不抓大图、免打扰、闲置门槛、白名单空、采样丢帧、迟到回调、失败计数、关闭后静默、请求卡死 180 秒自愈）。 |
| `tests/test_petcore_screenshot.py` | +120 | dHash 平坦图/条纹位序、Hamming；窗口抓图改为验证「物理矩形原样交给 grabber」「空矩形/空画面/桌面外」「越界裁剪」；Windows-only 真机用例：GDI `_grab_desktop_rect` 取 64×48 像素、`sample_window` 输出 ≤192 边的指纹。 |
| `tests/test_petcore_ai_mod.py` | +126/−2 | 视觉请求带窗口帧、答复只冒泡 + 静默入会话、不开窗、开关写配置（含白名单条数提示）、设置页 12 键写入与闲置行置灰、旧「三个命令」断言更新为四个。 |
| `tests/test_petcore_config_scope.py` | +46 | 12 键默认值/钳制/全局面不写子宠；白名单 80 条截到 50。 |
| `tests/test_petcore_ocr_mod.py` | +31 | 真实 OCR 引擎用例在被 Smart App Control 拦截时按「候选 pyd 的 `ctypes.WinDLL` 明确返回 WinError 4551」跳过（本机 16:49 起命中）；其它 ImportError 仍然失败，不放宽。 |
| `tests/test_petcore_menu_layout.py` | +39/−1 | 模板顺序纳入 `ai.chat:proactive`；旧布局合并补入且幂等；有 `look_screen` 时紧跟其后。 |
| 文档 | 见 §4 | SPEC §26、MOD-FORMAT §14、ROADMAP §25.2、PARITY §13、`petcore/AGENTS.md` 红线、LOG L050 + index。 |

## 2. 性能分析
环境：Windows 11，本机显示器 150% 缩放（逻辑 1280×800 / 物理 1920×1200）；
`QT_QPA_PLATFORM=offscreen`；每样本独立计时，取中位数与最差值。

| 路径 | 样本 | 实测 |
|---|---|---|
| `sample_window` 1200×800（GDI `StretchBlt` → 192 边 + dHash） | 15 | 中位 **33.8 ms**，最差 36.3 ms |
| `capture_window` 1200×800（768 边 + PNG + dHash，仅画面变化时） | 15 | 中位 **66.3 ms**（GDI 35 + PNG 30 + 哈希 0.3） |
| GDI 抓 1200×800（不含编码） | 15 | 中位 33.3 ms |
| `dhash` 1920×1080 / 800×600 | 30 | 中位 3.2 ms / 0.74 ms |
| 关闭态 tick 的配置读 | 200 | 中位 **0.0002 ms** |

- **稳态开销**：功能默认关闭；关闭时只有 8 s 一次定时器 + 一次配置读。开启且白名单
  命中后，每 tick 一次 192 边采样 ≈34 ms（占空 0.42%），画面没变就结束，**不抓大图、
  不编码 PNG**。只有「停留够、画面确实变了、额度够」的那一次才走 66 ms 的全量抓取。
- **新增路径成本**：真正发请求的 tick 多一次视觉调用（网络 + 模型），受日上限 15、
  最小间隔 60 s、冷却 300 s 三道闸；失败也计入间隔，连续 3 次失败当日熔断。
- **新系统调用/线程/磁盘**：每 tick 一次 `GetForegroundWindow` + 两个 DWM 属性 +
  一次 GDI 抓取（系统 API，无新线程）；请求复用 `ai.chat` 既有 daemon 线程；磁盘
  只有状态文件（每次盖章一次原子写）。
- **内存**：稳态只有缩略图（192×144×4 ≈ 110 KB，函数返回即释放）与一个 64 位基线；
  大图只在请求期间存在，不缓存历史帧，日志不写画面内容。

## 3. 实机运行记录

环境：本机 Windows 11 桌面，显示器 150% 缩放（逻辑 1280×800 / 物理 1920×1200）。

### 3.1 窗口抓图（真实前台窗口）

`.scratch/probe_window_capture.py`（源码树 + 真实桌面，前台窗口为微信）：

```
info: {"pid": 16812, "process": "Weixin.exe", "title": "...", "hwnd": 132596,
       "rect": [960, 0, 960, 1128]}
capture: 960 1128 239289 0x8181318131717191
```

- 960×1128 = 窗口物理矩形原样；239,289 字节 PNG；指纹非 0。
- **同一条探针在初版实现上是 `outside_screen` 失败**（按 DPR 二次缩放的裁剪只剩
  24%），这条实测就是改成 GDI 的直接依据。

### 3.2 主动识屏 dry-run（源码树，隔离 APPDATA）

`.scratch/verify_p4c1_source.ps1`：隔离 `%APPDATA%` → 只把 `ai.chat` 放进隔离
`mods/` → 配置 `enabled=true, dry_run=true, whitelist=[notepad.exe, title:*记事本*],
dwell=15s` → 启动 `pythonw -m petcore` → 打开记事本并保持前台 75 秒。

日志（`<隔离数据根>/logs/petcore.log`）：

```
2026-10-23 16:54:29,139 INFO petcore.mod.ai.chat.proactive: proactive dry-run:
process=Notepad.exe hwnd=5508806 dhash=e4e8c01115814998
```

- 只有**一条**：第一次满足「停留 15 s + 白名单命中」后采样并记日志，之后基线生效、
  同一画面不再刷日志——与设计一致。
- 同一轮 75 秒里没有 Traceback / ERROR；到 75 秒结束时进程仍在运行（脚本主动结束）。

### 3.3 门禁

```
ruff check pet/ tests/ petcore/ examples/petcore-mods   → All checks passed
pytest tests/test_petcore_*.py tests/test_architecture.py        tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
                                                        → 1345 passed, 1 skipped
python -m petcore --check                               → exit 0, diagnostics []
```

skip 的一条是 `tool.ocr` 的真实引擎用例：本机 Smart App Control 在 16:49 起以
WinError 4551 拦截 `shapely/_geos*.pyd`（`VerifiedAndReputablePolicyState=1`）。
测试用「候选 pyd 的 `ctypes.WinDLL` 明确返回 4551」作为跳过条件，其它 ImportError
仍然会红。

### 3.4 打包与安装（如实登记）

- 首次构建（17:00 前后）的冒烟被拦：`dsh-pet-core.exe --check` 返回
  `Permission denied`，CodeIntegrity 3077；同一时刻 16:39 的旧 exe 仍可运行。
  **用户关闭火绒相关监测后复测，同一份新构建可以直接运行**（`--check` exit 0），
  说明拦截来自第三方安全软件的驱动层，不是 SAC 对开发证书的硬性拒绝；
  `VerifiedAndReputablePolicyState` 仍为 1。
- 最终构建（19:39）：`dist/dsh-pet-core/dsh-pet-core.exe` 14,969,376 B，
  SHA-256 `0d3169b2f87482d992d4356b2377248f2c147501d83c957ad2bd991bfe3cbc1f`；
  `dist/dsh-pet-core-setup.exe` 261,554,392 B，
  SHA-256 `37366e58ceaa9b4e95e90f06624237cd569a7de983c1316132119583e3e4cf31`，
  签名 `Valid`（`CN=DSH Pet Core Dev`）。
- **安装验证（19:40）**：静默升级安装到 `E:\dsh-pet-core`（`PrivilegesRequired=lowest`），
  安装后的 exe 与上面同尺寸（19:37）；同步最终 `ai.chat` 到 `mods/ai.chat` 后
  `--check` 在隔离 `%APPDATA%` 下 exit 0、`diagnostics: []`、9 个 mod。
  随后以 `dry_run=true / whitelist=[notepad.exe]` 启动安装版 70 秒，日志两条：
  `proactive dry-run: process=Notepad.exe hwnd=1247576 dhash=e4e8c01195814998` 与
  随后画面变化后的 `dhash=2428201115814998`——**冻结后的 exe 里窗口采样链路可用**。

## 4. 文档同步

- `docs/PETCORE-SPEC.md` §26：行为口径、12 键、隐私与限额。
- `docs/PETCORE-MOD-FORMAT.md` §14：`ScreenPort` 窗口采样、`SystemPort.idle_seconds()`、
  `ConfigPort.set()` 的使用边界、`ai.chat` 参考实现。
- `docs/PETCORE-ROADMAP.md` §25.2：c1 完成，c2（`ai.agent`）/c3（提醒域转正）保留。
- `docs/PETCORE-MAIN-PARITY-BACKLOG.md` §13：已对齐/未移植（陪伴记忆、免费视觉
  provider、HDR 抓屏）。
- `petcore/AGENTS.md`：窗口抓屏只在 core、双复核、主动识屏四道门、配置写入端口、
  闲置端口五条红线。
- `docs/PETCORE-LOG.md` L050 + `docs/PETCORE-LOG-INDEX.md` 一行。

## 5. 未验证 / 风险

1. offscreen 下 Qt 的 `grabWindow` 返回空图；窗口抓图用注入的 `grabber` 验证
   矩形/裁剪/越界，另有 Windows-only 的 GDI 真机用例与 §3.1 的真实窗口探针。
2. 多屏：GDI 抓的是「虚拟桌面物理矩形」，负坐标副屏在数学上成立；但本机只有一块
   屏，混合 DPI 双屏未实机复核。窗口大半在屏外（裁剪不足一半）会判失败，不截错屏。
3. 抓图在 GUI 线程执行（Qt / GDI 的抓屏都不保证跨线程安全）：稳态单次 ≈34 ms、
   请求时 ≈66 ms；若后续发现拖动卡顿，需要 core 侧专用线程或 `PrintWindow` 方案。
4. HDR 屏幕可能偏色（主分支的 DXGI FP16 抓屏未移植，与本分支此前口径一致）。
5. 陪伴记忆、免费视觉 provider 未移植，已记入 parity backlog。
6. 本机一度被安全软件驱动层拦截新构建（CodeIntegrity 3077）；用户关闭火绒相关
   监测后已恢复，最终构建已完成静默安装与 dry-run 验证（§3.4）。

### 3.5 旧菜单布局迁移（真实用户配置副本）

读取本机现有 `%APPDATA%\dsh-pet-core\config.json` 的 `menu_layout`（只读），用
`merge_user_layout()` 跑一遍合并：

```
added: ['default-action-added:ai.chat:proactive']
neighbours: ['ai_chat', 'look_screen', 'ai.chat:proactive', 'screen_capture', 'playback_speed']
```

即：旧布局会在「看看屏幕」之后补上「主动识屏」，顺序与模板一致；重复合并幂等
（单测 `test_merge_adds_the_proactive_action_to_existing_layouts`）。
