# petcore AI 边界收口：mod 拆分 / 线程调度 / 配置端口 / 外观跟随（2026-10-22）

> 分支：`feat/petcore-vpet-architecture`；基线：`0e936ef`（P3 对话/识屏效果对齐）。
> 本文记录把 L039 留下的边界缺口全部收口的改动：`ai.chat` 运行时代码去 Qt、
> 设置页与运行时配置访问分层、线程安全 scheduler、聊天窗外观/跟随、截图历史语义。
> 规格见 [`PETCORE-SPEC.md`](PETCORE-SPEC.md) §19，改动史见 L040。

## 1. 修改文件说明

### 1.1 核心契约与运行时

| 文件 | 改动（+ / −） | 为什么 |
|---|---:|---|
| `petcore/contracts/host.py` | +13 / −5 | 新增只读 `ConfigPort` 与 `HostPorts.config`；删除从未实现的 `SettingsPort`/`HostPorts.settings`；`SchedulerPort` 明确「任意线程可调、回调在 GUI 线程」。 |
| `petcore/ui/ports.py` | +66 / −29 | `QtScheduler` 改成 queued 的 `_SchedulerBridge`，worker 线程不再直接创建 `QTimer`；新增 `QtConfigPort`；`build_ports` 注入 `config`。定时器不挂 Qt parent，避免 bridge 析构时悬空 DeferredDelete 触发进程 abort。 |
| `petcore/mods/feature.py` | +39 / −7 | 新增包入口加载：`host/__init__.py:create_host` 用 `submodule_search_locations` 加载并注册 `sys.modules`，支持相对 import；异常时清理；普通 `.py` 入口不变。 |

### 1.2 `ai.chat` 拆分

| 文件 | 改动（+ / −） | 为什么 |
|---|---:|---|
| `examples/petcore-mods/ai.chat/host/factory.py` | −689（删除） | 原单体：路由、prompt、设置页、线程桥混在一起。 |
| `host/__init__.py` | +27（新） | 只做 `FeatureDefinition` 组装与 `create_host`。 |
| `host/constants.py` | +11（新） | `OWNER`、历史条数、识屏冷却。 |
| `host/prompts.py` | +126（新） | 默认人格、识屏/截图话术、`chat_messages`/`ask_messages` 纯函数；可单测历史形状。 |
| `host/runtime.py` | +430（新） | `AiChatRuntime`：三条命令与回调；只经 `ports.chat/screen/screen_ask/api/config/scheduler/presentation`，无 PySide6、无 `petcore.net/api`。 |
| `host/settings_page.py` | +313（新） | `AiChatPage`：模型/人格/视觉 + 新增「对话窗外观」；受信 UI 允许 QtWidgets。 |
| `mod.json` | 版本 1.1.0→1.2.0，入口改包 | 行为与结构变化。 |

### 1.3 聊天窗外观与跟随

| 文件 | 改动（+ / −） | 为什么 |
|---|---:|---|
| `petcore/ui/pet_window.py` | +6 / −1 | 新增 `pet_moved` 信号，`moveEvent` 末尾 emit。 |
| `petcore/ui/chat/window.py` | +128 / −1 | 新增 `pet_window`/`follow_pet`、`position_near_pet()`、40ms 合并定位；右侧优先→左侧→下方→钳制；`showEvent` 首次定位。顺带修复 `set_accent()` 只改 `_base_accent`、`_style()` 读 `accent_color` 导致实时换色无效的既有 bug。 |
| `petcore/ui/chat/controller.py` | +83 | `apply_appearance()` 实时推送背景/强调色/置顶/跟随，不建窗不唤窗；创建窗口时接当前宠。 |
| `petcore/ui/app.py` | +7 | `apply_live_settings()` 刷新聊天窗外观。 |
| `petcore/ui/screen/controller.py` | +4 | docstring 明确截图问答历史每次采集独立、不落盘。 |
| `petcore/config.py` | 沿用 L039 的 `chat_*` 键 | 本次把键接到设置 UI 与行为。 |

### 1.4 测试与文档

| 文件 | 改动 | 为什么 |
|---|---:|---|
| `tests/test_petcore_scheduler.py` | 新 126 行 | worker 线程调度、重复/取消、异常存活、ConfigPort 回退。 |
| `tests/test_petcore_feature.py` | +54 | 包入口 + 相对 import + 异常清理。 |
| `tests/test_petcore_ai_mod.py` | +129 / −11 | 包入口、runtime 无 Qt/无 host.config 静态守卫、prompt 形状、设置页外观/预览。 |
| `tests/test_petcore_chat_ui.py` | +178 / −2 | follow 开/关、边缘钳制、下方回退、配置接线、`apply_appearance`。 |
| `tests/test_petcore_live_settings.py` | +33 | `apply_live_settings` 刷新 chat。 |
| `tests/test_petcore_screen_ask.py` | +5 / −2 | 新采集清空历史 + 不写盘。 |
| `petcore/AGENTS.md` | +13 | 运行时无 Qt、配置两层、包入口、聊天窗外观、截图历史五条红线。 |
| `docs/PETCORE-SPEC.md` / `ROADMAP.md` / `ARCHITECTURE.md` / `MOD-FORMAT.md` / `MAIN-PARITY-BACKLOG.md` | 见 L040 | 契约、批次、端口清单、包入口、parity 同步。 |

## 2. 性能分析

环境：Windows，`QT_QPA_PLATFORM=offscreen`，`.venv/Scripts/python`（Python 3.12）。
探针脚本 `.scratch/ui/bench_boundaries.py`（临时，不入库）：

```text
scheduler call_later(0) 端到端       ：median 0.027 ms / p95 0.061 ms（n=50）
ConfigPort.get                        ：< 0.001 ms（n=200）
首次打开对话窗                        ：24.7 ms（单次）
ChatController.apply_appearance() 无变化：median 0.003 ms / p95 0.004 ms（n=50）
ChatWindow.position_near_pet()        ：< 0.001 ms（n=100）
```

- **稳态开销**：scheduler 只多了一次 queued signal；没有新增常驻线程或轮询。
  外观刷新在值未变化时直接短路（`apply_appearance` 的 0.003ms 即此路径）。
- **新增路径成本与频率**：`call_later` 每次一个信号 + 一个 `QTimer`，发生在
  worker 回包时（每条流式回复一次收尾）；`apply_appearance` 在设置页每次改动
  （16ms 合并后的 live apply）触发一次，窗口数量 ≤16；`position_near_pet` 在
  follow 开启时每次宠物移动合并到 40ms 一次。
- **系统调用 / 网络 / 磁盘 / 线程**：本次不新增网络/磁盘；`runtime.py` 不再创建
  Qt 对象，线程仍是原有的对话/识屏短线程；`ConfigPort.get` 是纯内存读取。
- **内存**：scheduler 每个活动定时器一个 `QTimer` + 字典项；聊天窗多持有宠物
  引用与一个 40ms 单发定时器；无缓存增长。
- **回归风险**：`cancel()` 变 queued 后，已到点的定时器可能在 stop 前多触发一次；
  现有 self-talk/chime 调用方不依赖该同步性，测试全绿。

## 3. 实机运行记录

本机真实环境（Windows，1280×800 @1.5）：

1. **门禁**

```text
$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
    tests/test_petcore_*.py tests/test_architecture.py \
    tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
1083 passed in 52.62s

$ .venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods/ai.chat
All checks passed!

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m petcore --check
exit 0
```

2. **真实 mod 安装/加载**

```text
$ petcore --root .scratch/ai-boundary mods install examples/petcore-mods/ai.chat
installed ai.chat 1.2.0 -> .scratch\ai-boundary\mods\ai.chat

$ petcore --root .scratch/ai-boundary --allow-feature-mods --check
"mods": [{"id": "ai.chat", "version": "1.2.0", "enabled": true, ...}]
"diagnostics": []
```

证明包入口 `host/__init__.py:create_host` 在真实 loader 路径下可用，相对 import
（runtime/prompts/settings_page）正常。

3. **静态守卫**

```text
runtime.py 不含 PySide6 / petcore.net / petcore.api / host.config
settings_page.py 允许 PySide6
```

由 `tests/test_petcore_ai_mod.py::test_runtime_module_is_qt_and_network_free` 固化。

4. **视觉/交互**

- offscreen `grab()` 渲染对话窗：960×700 双栏、侧栏会话、Markdown 气泡、
  底部浮动输入框，与 L039 一致。
- 设置页外观分区：背景 combo 含 9 个内置主题与“自定义图片…”；强调色 hex 校验、
  颜色选择、恢复默认；跟随/置顶复选框；改动调用 `apply_appearance`。
- follow 测试：宠物右移 → 聊天窗跟到右侧；贴近屏幕右缘 → 切左侧/钳制；
  两侧都放不下 → 下方；关闭 follow 后不再移动。

**未做的实机验证**：真实桌面拖选、真实双屏/混合 DPI 下的 follow 定位、真实
DeepSeek 端到端（无可用密钥）。`chat_background` 仍不含取景裁切/透明度/填充键。
