# PR 报告：`tool.ai-browser` 轻量 AI 浏览器扩展 + mod 接口文档可行性实测（2026-10-27）

> **基线**：`b88059dd`（feat(petcore): 落库分支上待提交的灵动岛、音乐识别与磁盘段工作）
> **分支**：工作区（未提交）　**日期**：2026-10-27
> **范围**：14 个文件（新增扩展 9、测试 1、测试门禁 1、安装器 1、文档 2+）
>
> **提交范围**：本次只提交 `docs/` 下的文档。扩展包 `examples/petcore-mods/tool.ai-browser/`、
> `tests/test_petcore_ai_browser_mod.py`、`tests/test_petcore_example_mods.py` 的 IDS 与
> `packaging/petcore.iss` 的 opt-in 行是**本地验证产物**，未随本次提交推送。
> **关联**：`dist-mod-kit/petcore-mod-kit-2026-10-27`（扩展开发资料包，2026-10-27 快照）

## 一、核心特性

一个可导入的 feature 扩展 `tool.ai-browser` 1.0.0：右键桌宠 →「扩展 → AI 浏览器 →
打开浏览器」，弹出一个只允许访问国模 AI 对话站的浏览器窗口（DeepSeek / 豆包 / 千问 /
Kimi / 文心一言 / 智谱清言 / 腾讯元宝 / 讯飞星火）。地址栏、站点按钮、主框架跳转三处
共用同一张白名单；窗口内登录态持久化到扩展自己的数据目录。

同时，这个包被当作**接口文档探针**：报告最后一节逐条给出「文档说的」与「真机跑出来的」
差异（窗口能力、宿主内核差异、capabilities 语义等）。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 站点白名单 | 8 个国模 AI 站；`sites.py` 是纯函数（关键词/URL 解析、后缀边界判定），地址栏与 `acceptNavigationRequest` 共用 |
| 2 | 内嵌浏览器 | `QWebEngineView` + 命名 profile（持久 cookie/缓存 + Chrome UA + zh-CN），单例窗口，几何落 `feature-data` |
| 3 | 三级降级 | 内嵌 Chromium → Edge `--app` 窗口（复用用户登录态）→ 系统默认浏览器；每级都给气泡说明，不静默 |
| 4 | 菜单/设置接线 | 1 个 menu contribution（命令声明 `slot` 形参）+ 1 个 settings_page（开关 / 默认站点 / 额外白名单 / 当前内核状态） |

**红线 / 不变量**：不修改 `petcore/`、`pet/`、打包 spec；运行时模块（`runtime/sites/engine/external`）
不 import PySide6、不 import `petcore.net/api/account/platform`；白名单之外的输入永不发导航；
配置只写 `extra` 三个键，窗口几何不写配置。

## 二、修改文件说明

### 实现（新扩展 `examples/petcore-mods/tool.ai-browser/`）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `mod.json` | +14 | id `tool.ai-browser`、`kind: feature`、`execution: host-only`、`entrypoint: host/__init__.py:create_host`、capabilities 五项 |
| `host/__init__.py` | +3 | 包入口转发 `create_host`（loader 支持相对 import） |
| `host/factory.py` | +38 | `FeatureDefinition`：菜单 `open` + 设置页 `browser`；holder 把 runtime 注入设置页（`hello.timer` 同款） |
| `host/sites.py` | +208 | 站点表（8 站、每站 hosts+别名）、`normalize_domain/normalize_extra/allowed_domains/host_allowed/is_allowed/site_for_url/resolve_site/resolve_target/default_site`；纯函数、零 Qt、零网络 |
| `host/engine.py` | +28 | `importlib.util.find_spec` 探测宿主是否有 `PySide6.QtWebEngineWidgets/Core`；结果缓存；`ImportError` 兜底为 False |
| `host/external.py` | +83 | 纯标准库：Edge 路径发现（三处环境变量 + 两处固定路径 + PATH）、`--app` 启动、`os.startfile`/`webbrowser` 系统兜底；`open_external` 返回实际通道 |
| `host/runtime.py` | +96 | `commands={"open": open}`；开关闸门 → 引擎探测 → 惰性导入窗口 / 走外部通道；气泡反馈 `force=True`；storage 端口取 `feature-data/tool.ai-browser` |
| `host/browser_window.py` | +439 | `QMainWindow`：工具栏（前进/后退/刷新/回/地址栏/系统浏览器/置顶）、8 个站点按钮、状态条、拦截横幅；`BrowserPage` 重写 `acceptNavigationRequest`（只放行主框架白名单）与 `createWindow`（target=_blank 回落本页）；命名 profile + 持久 cookie；几何读写 `window.json` 并按屏幕可用区钳制 |
| `host/settings_page.py` | +164 | `SettingsPage`：启用开关、默认站点下拉、额外白名单、内核状态行、打开按钮；`dirty/confirm_save/discard_changes` 与 `changed.emit()` 按契约实现 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_petcore_ai_browser_mod.py` | +206 | 站点表/关键词/URL 解析、白名单后缀边界与域名伪装、`extra` 归一化、非 http(s) 拒绝、清单与 `FeatureManager` 加载、menu+settings 配对、运行时代码无 Qt/无私有包导入、关闭闸门、无内核→Edge→失败三条降级分支 |
| `tests/test_petcore_example_mods.py` | +1 / −0 | `IDS` 加入 `tool.ai-browser`，让通用 validate/load/install 门禁覆盖新包 |

### 打包

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `packaging/petcore.iss` | +3 / −0 | 新增 opt-in 任务 `mod_aibrowser`（默认不勾选）+ 源目录与 `.trusted` 两行：`test_petcore_installer_mods_opt_in.py` 要求每个 example 包都有安装入口，且不勾选完全不落盘 |

### 文档

| 文件 | 改动意图 |
|---|---|
| `docs/PETCORE-MOD-DEVELOPMENT.md` | 新增 §3.5「宿主能力与窗口：2026-10-27 实测边界」 |
| `docs/PETCORE-MOD-FORMAT.md` | §7「能力与边界」补 6 行实测口径 |
| `examples/petcore-mods/README.md` | 包说明 + 安装命令 |
| `docs/PETCORE-LOG.md` / `docs/PETCORE-LOG-INDEX.md` | L110 条目与索引行 |
| `docs/INDEX.md` | 本报告登记 |

### 未改动

`petcore/`、`pet/`、`packaging/`、`.venv` 依赖清单一律未动；`dist-mod-kit/` 是冻结快照，未改。

## 三、实现要点

- **白名单三层同源**：`sites.resolve_target` 管地址栏/菜单入口，`sites.is_allowed` 管主框架导航，
  `host_allowed` 用 `host == domain or host.endswith("." + domain)` 做后缀边界（`evil-deepseek.com`、
  `deepseek.com.evil.cn` 都不放行）。子资源不进这个钩子，所以不会误伤 CDN。
- **单例窗口**：`_WINDOW` 存活就 `raise/activate`，不重复建 profile；`QWebEngineProfile` 进程内只建一次，
  持久化目录在 `storage.data_dir("tool.ai-browser")/profile`。
- **几何不写配置**：按 `petcore/AGENTS.md`「运行时不许把配置当状态存储」，窗口几何写
  `feature-data/tool.ai-browser/window.json`，并按 `availableGeometry` 同时钳宽高与位置
  （本机 1280×800 + 150% 缩放下，默认 1180×820 会出屏，实测发现后修）。
- **降级按能力探测而不是按平台**：`engine.find_spec` 决定内嵌与否；安装包没打 QtWebEngine 时
  同一份代码自动走 Edge `--app`（已是 Chromium 118+，复用用户配置与登录态）。
- **UI 模块与 runtime 分家**：`runtime.py` 只在确认有内核时才 `from .browser_window import open_browser`；
  `browser_window.py` 不 import `petcore.ui.*`（外观用 `QPalette` 生成极简 QSS），比官方样板
  `fun.divination/host/panel.py` 更严格。

## 四、性能分析

环境：本机 Windows 11 / Python 3.12 / PySide6 6.12 / 屏幕 1280×800@150%；
`QT_QPA_PLATFORM` 未设置（真实窗口），数据来自 `.scratch/ai_browser_perf.py` 与
`.scratch/ai_browser_driver.py` 的真实运行（命令与首屏 2–3 次样本；内存与 8 站探针各 1 次采样）。

| 指标 | 实测 |
|---|---|
| 命令返回（建窗口 + 起导航） | **1360 / 1593 / 1985 ms**（三次样本） |
| 首屏可读（DeepSeek 登录页 title+host 就绪） | **4891 ms** |
| 首屏可读（Kimi） | **2188 / 2328 ms**（两次样本） |
| 进程树 RSS（开窗前） | **72.6 MB**（1 进程） |
| 进程树 RSS（DeepSeek 加载后） | **409.9 MB**（主进程 350.0 + `QtWebEngineProcess.exe` 59.8） |
| 进程树 RSS（关窗 3 s 后） | **390.5 MB**（主进程 325.7 + 64.8，**未释放**） |
| 8 站探针加载耗时 | 7.7 / 2.2 / 4.2 / 5.7 / 4.4 / 8.5 / 6.7 / 8.8 s（DeepSeek/豆包/千问/Kimi/文心/智谱/元宝/星火） |

逐条回答：

- **稳态开销**：窗口关闭前，Chromium 常驻 ≈ 330–340 MB（主进程涨 + 浏览器子进程）；
  关窗后进程与内存**都不回收**（QtWebEngine 进程复用是设计使然）。没有窗口时扩展零开销：
  无定时器、无轮询线程、无网络，只有菜单点击那一次调用。
- **新增路径成本与频率**：每次点「打开浏览器」= 1 次窗口创建（首次还要建 profile）；
  再次点击只 `raise/activate`（毫秒级）。Edge 降级路径 = 1 次 `subprocess.Popen`（外部进程开销不在本进程）。
- **新增系统调用/网络/磁盘/线程**：新增 1 个 Chromium 多进程组（GUI/IO/渲染/GPU），
  读页面时产生正常网络请求；首次运行写 `profile/`、`cache/`，关窗写 1 个 `window.json`；
  不新增自建线程。
- **内存有无增长**：有，且是最大代价 —— 开过一个浏览器窗口后，即使关掉，进程树仍比基线高
  ≈318 MB（390.5 vs 72.6）。这是"内嵌 Chromium"的固有成本，**不是**本扩展的泄漏；
  Edge 降级路径不开 Chromium，本进程无增长。

## 五、实机运行记录

全部在本机真实环境执行（非 CI、非 mock），命令与真实输出：

1. **校验与安装（目录）**

```text
> .venv/Scripts/python -m petcore mods validate examples/petcore-mods/tool.ai-browser
ok: examples\petcore-mods\tool.ai-browser

> .venv/Scripts/python -m petcore --root .scratch/ai-browser-root mods install <同上目录>
installed tool.ai-browser 1.0.0 -> .scratch\ai-browser-root\mods\tool.ai-browser

> .venv/Scripts/python -m petcore --root .scratch/ai-browser-root mods list
enabled  feature tool.ai-browser 1.0.0 E:\Work\dsh-pet-0\.scratch\ai-browser-root\mods\tool.ai-browser
```

2. **ZIP 打包与 ZIP 安装**（验证"打包一个 zip 导入"这条路径）

```text
> .venv/Scripts/python scripts/build_petcore_extensions.py --packs tool.ai-browser
[build] tool.ai-browser 1.0.0 -> tool.ai-browser-1.0.0.zip (9 files, 14756 bytes, sha256 701969107fd4)
[build] tool.ai-browser excluded: blocked=0 generated=0 unknown=0

> .venv/Scripts/python -m petcore --root .scratch/ai-browser-ziproot mods install dist-extensions/tool.ai-browser-1.0.0.zip
installed tool.ai-browser 1.0.0 -> .scratch\ai-browser-ziproot\mods\tool.ai-browser
enabled  feature tool.ai-browser 1.0.0 ...
```

3. **进程级集成（真 CoreHost + 真 FeatureManager + 真 WebEngine + 真网络）**
   `.scratch/ai_browser_driver.py` 的输出（`.scratch/ai-browser-driver.json`）：

```json
{"features": ["core.feature-demo","fun.click-talk","fun.self-talk","tool.ai-browser",
              "tool.links","tool.memory-trim","tool.network-info","tool.quick-launch","tool.quiet-mode"],
 "mod_loaded": true, "diagnostics": [], "commands": ["open"], "command_returned": true,
 "open_command_ms": 1985, "window_created": true,
 "first_load": {"elapsed_ms": 2328, "url": "https://www.kimi.com/", "host": "www.kimi.com"},
 "blocked_navigation": {"before": "https://chat.deepseek.com/sign_in",
                        "after": "https://chat.deepseek.com/sign_in",
                        "banner_visible": true,
                        "banner_text": "已阻止跳转到 example.com：它不在 AI 站点白名单里。"},
 "address_gate": {"url": "https://chat.deepseek.com/sign_in",
                  "status": "只允许打开 AI 站点白名单内的地址：example.org"},
 "fallback": {"calls": ["https://chat.deepseek.com"]}}
```

   窗口截图（真窗口，按窗口几何裁剪）：`.scratch/ai-browser-window.png`
   —— 工具栏、地址栏 `https://chat.deepseek.com/sign_in`、8 个站点按钮、DeepSeek 登录页、
   底部状态"加载完成"。

4. **设置页（真 SettingsDialog → 扩展管理 → 加装扩展 → AI 浏览器）**
   截图 `.scratch/ai-browser-settings.png`；读写实测：

```json
{"entry_keys": ["extension:browser","market","mods"], "ai_browser_page": true,
 "memory_after_uncheck": false, "disk_after_commit_unchecked": false, "disk_after_commit_checked": true,
 "engine_text": "内嵌 Chromium（源码运行环境）：窗口内直接加载站点，白名单严格生效。"}
```

5. **降级路径（把 QtWebEngine 从 import 系统里摘掉，模拟安装包）**
   `.scratch/ai_browser_fallback.py`：

```json
{"engine_spec_none": true, "engine_available": false, "mod_loaded": true,
 "command_returned": true, "browser_window_imported": false,
 "edge_path": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
 "edge_app_after": [{"pid": 36172, "app_arg": "--app=https://chat.deepseek.com"}],
 "edge_app_closed": [36172]}
```

   即：没有内核时不 import 窗口模块、不抛异常，真的拉起了 Edge 应用窗口（实测后关闭该测试窗口）。

6. **站点可达性探针**（真 WebEngine，逐站 30 s 上限）：8/8 加载成功。两处重定向实测为
   千问 `tongyi.com/qianwen/ → www.qianwen.com`、文心 `yiyan.baidu.com → wenxin.baidu.com`，
   站点表据此把 `qianwen.com`、`baidu.com` 收进白名单。

7. **门禁**：`ruff check tests/test_petcore_ai_browser_mod.py examples/petcore-mods/tool.ai-browser`
   → `All checks passed!`；`pytest tests/test_petcore_ai_browser_mod.py tests/test_petcore_example_mods.py
   tests/test_petcore_extension_build.py tests/test_petcore_extension_candidates.py -q` → `35 passed`。
   相关套件 `pytest tests/test_petcore_*.py tests/test_architecture.py -q` → **2207 passed in 262.51s**
   （首轮曾因新 example 包没写进 `packaging/petcore.iss` 红 1 条，补 opt-in 安装入口后全绿）。

## 六、接口文档可行性结论（本次实测的直接产出）

对照 `dist-mod-kit/petcore-mod-kit-2026-10-27/给AI的说明.md` 与 `docs/PETCORE-MOD-*.md`：

| # | 文档说法 | 实测 | 结论 |
|---|---|---|---|
| 1 | §7「自定义 Qt 窗口/托盘/全局热键：core 不提供这类端口 → 做不到」 | 官方样板 `fun.divination/host/runtime.py:182` 就在命令里造 `QDialog`；本扩展造 `QMainWindow` + WebEngine 窗口也能跑 | **说法不成立**：窗口不是端口能力，而是"进程里有 Qt 就能造"。真正缺的是端口级治理（置顶/多宠归属/生命周期），文档该改写而不是写"做不到" |
| 2 | 内嵌浏览器/原生控件 | 安装包 `_internal/PySide6` 没有 `QtWebEngine*`，同一份 mod 在源码环境内嵌、在安装包只能外部打开 | **文档完全没提"宿主打包决定 mod 能力"**；建议在 FORMAT §7 加"能力探测 + 降级"约定（本包 `engine.py` 是参考实现） |
| 3 | §1.9「import petcore.ui.\* 只允许出现在 settings_page.py」 | 官方样板 `panel.py` 也 import 了 `petcore.ui.settings.style`，且被 runtime 使用 | 文档与样板不一致；本包刻意不 import `petcore.ui.*`，只留 `settings_page` 一处 |
| 4 | capabilities「只是声明，运行期不强制」 | `network.request`/`process.spawn` 不产生端口、不产生闸门；本包用 `subprocess` 直接开 Edge 完全不受控 | 语义正确但**容易误读为授权**；建议明确写"无运行期强制，也不构成沙箱" |
| 5 | 菜单 `slot` 形参可拿到发起菜单的桌宠 | 命令声明 `slot=None` 后正常收到 `None`/`0`；`host.run_feature_command(..., slot=)` 直传也生效 | 成立 |
| 6 | 「有 menu 就必须有 settings_page」 | 本包两项都有，扩展管理里出现「加装扩展 → AI 浏览器」 | 成立（第三方无强制，仅官方有测试） |
| 7 | 设置页「改动实时写 config，保存/取消负责落盘/回滚」 | 取消勾选 → 内存 false → `_commit()` → 磁盘 false → 勾回 → 磁盘 true | 成立 |
| 8 | 安装：GUI 导入 ZIP/目录；CLI `mods install <目录或.zip>`（FORMAT §6 / DEVELOPMENT §8 已写） | 目录与 `.zip` 两种来源都实测 enabled | 仓库文档正确；分发的《给AI的说明》§5 只列了目录，资料包漏写 ZIP |
| 9 | 第三方配置键落 `extra`、单值 ≤4KB | `ai_browser_enabled/default_site/extra_domains` 三键正常读写 | 成立 |

## 七、未验证与风险

- **登录态没走完**：只到 DeepSeek 扫码/短信登录页，没有账号可做真实登录；Kimi/豆包等登录跳转
  可能落到未收录的 SSO 域，届时用设置页「额外白名单」补，报告中不宣称已覆盖。
- **Edge 应用窗口模式拦不住窗口内跳转**：只保证入口 URL；白名单严格性只在内嵌路径成立。
- **内存代价**：开窗后 ≈+330 MB 且关窗不释放（见 §四）。"轻量"只体现在 UI 与站点范围，
  不体现在引擎；要真轻量需要在宿主侧换 WebView2（未做，超出"只做这个 mod"）。
- **平台**：仅 Windows 11 本机验证；`external.py` 的非 Windows 分支（`webbrowser`）未测。
- **CI**：QtWebEngine 相关只在本机跑，未进 CI（测试文件本身无 Qt、无网络，可进 CI）。

## 八、给使用者的三条路

1. 设置 →「扩展管理」→「导入 ZIP」选 `dist-extensions/tool.ai-browser-1.0.0.zip`；
2. 设置 →「扩展管理」→「导入目录」选 `examples/petcore-mods/tool.ai-browser`；
3. 命令行：

```bash
.venv/Scripts/python -m petcore mods install examples/petcore-mods/tool.ai-browser
```

> 现有安装包 `E:\dsh-pet-core` 没有内嵌 Chromium：装进去后点「打开浏览器」会走 Edge
> 应用窗口（设置页「内核」一行会明确写出来）。想要窗口内嵌，只能用源码环境
> （`.venv/Scripts/python -m petcore`）或另做带 QtWebEngine 的安装包。
