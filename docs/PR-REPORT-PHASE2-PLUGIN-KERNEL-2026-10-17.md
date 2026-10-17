# Phase 2 内核收口：PluginRegistry / Context / Manifest / ConfigStore + 节日提醒插件化（共存）

> 分支：`dlc/mod-center-port`；阶段 1 报告：[`PR-REPORT-RESOURCE-HARD-GATE-2026-10-17.md`](PR-REPORT-RESOURCE-HARD-GATE-2026-10-17.md)。
> 上游参照：上游 DLC 实现分支（只读、不合并；分支名与基线 SHA 属仓库内工作档案）。
> 口径：**默认仍走内置 `FestivalReminderService`**；`PET_FESTIVAL_PLUGIN=1` 时由
> `PluginRegistry` 装配插件。插件与内置服务行为等价性由同一批用例覆盖，默认切换
> 留待维护者拍板（见文末决策点）。

## 一、修改文件说明

### 新增文件（`wc -l`）

| 文件 | 行数 | 改了什么 / 为什么 |
|---|---:|---|
| `pet/plugins/manifest.py` | 147 | `PluginManifest` / `version_satisfies` / `PluginDiagnostic`。只服务 Core 自己 `register_builtin` 的 in-process 插件；**不是**签名功能包清单（后者仍是 `package_trust`）。拒绝任意 `entrypoint`、非 `in_process` kind、非法 id/版本。 |
| `pet/plugins/config.py` | 307 | `PluginConfigStore` + `FESTIVAL_LEGACY_CONFIG_MAP` + `JsonConfig`。命名空间与旧扁平键**两本账**：插件命名空间写独立的 `plugins.json`，节日提醒的 11 个旧键仍读写 Core `Config`；不新增 Core 顶层配置键。 |
| `pet/plugins/runtime.py` | 571 | `PluginRegistry` / `PluginContext` / 生命周期 / 依赖拓扑 / 故障隔离 / 诊断。只接受显式 `register_builtin`；能力集由 manifest 声明、端口按 capability 收口。新增 `host_app` 注入点，供共存期插件复用 AppShell 的旧呈现策略。 |
| `pet/plugins/builtin/__init__.py` | 6 | 内置插件包入口。 |
| `pet/plugins/builtin/festival_reminder/__init__.py` | 20 | 轻量包入口：清单/ID 直接可用，插件类惰性导出（导入本包不拉起 `festival_service` 与五份文案表）。 |
| `pet/plugins/builtin/festival_reminder/manifest.py` | 32 | 节日提醒插件清单（`official.festival-reminder`、`in_process`、6 项 capability、旧键映射）。 |
| `pet/plugins/builtin/festival_reminder/plugin.py` | 103 | 插件本体：把 `FestivalReminderService` 接到 `PluginContext` 的 scheduler/presentation/audio/config 端口；`toggle` 写旧键并保存两本账。 |
| `tests/test_plugin_runtime.py` | 327 | manifest 校验、事件故障隔离、依赖拓扑、capability 拒绝、命名空间隔离、旧键双向映射、两本账保存。 |
| `tests/test_festival_plugin.py` | 163 | 插件启停、提醒、`toggle`、与签名功能包宿主隔离、`stop_all` 收口。 |

### 修改文件（`git diff --numstat`）

| 文件 | +/− | 改了什么 / 为什么 |
|---|---:|---|
| `pet/festival_service.py` | +47/−4 | 新增可选端口参数（`scheduler/presentation/audio/config_source`）；不传时沿用旧 AppShell 路径。调度可用 `SchedulerPort`，展示/语音可注入；旧路径的免打扰、飞行期、系统通知回退**一个未动**。 |
| `pet/app.py` | +100/−1 | 装配 `plugin_registry`（`JsonConfig(<data>/plugins.json)` + Core `Config` 作为 legacy 源）；`PET_FESTIVAL_PLUGIN=1` 时 `_ensure_festival_service` / `_sync_festival_service` 走插件，失败回退内置；新增插件呈现/语音端口兜底。**启动路径不导入 `festival_service`**（实测 `import pet.app` 后 `pet.festival_service` 与 `pet.festival` 都不在 `sys.modules`）。 |
| `tests/test_festival.py` | +31/−0 | 真 AppShell + `PET_FESTIVAL_PLUGIN=1`：插件装配、运行、关闭后回到 stopped。 |
| `tests/test_architecture.py` | +5/−0 | 三个 Phase 2 纯逻辑模块与轻量清单加入零 Qt 名单。 |

## 二、性能分析

环境：Windows 11，Python 3.12.10，16 核，`QT_QPA_PLATFORM=offscreen`。

```text
registry build+discover (50 次平均): 0.03 ms
JsonConfig save:                    1.94 ms
import pet.app:                    pet.festival_service 未导入；pet.festival 未导入
```

- **稳态开销**：AppShell 构造期多建一个 `PluginRegistry`（0.03 ms，无可执行插件时不起定时器、不读文件）；`plugins.json` 只在插件真正保存配置时写一次（1.94 ms）。
- **新增路径成本与频率**：`PET_FESTIVAL_PLUGIN=1` 时插件启动一次、每 30 s 一次既有 tick；`toggle` 触发一次两本账保存。默认路径（内置服务）成本不变。
- **新的系统调用 / 网络 / 磁盘 / 线程**：只新增插件配置的原子写；无网络、无线程、无常驻定时器增量（tick 仍是原来那一个）。
- **内存**：插件注册本身不导入 `festival_service`；只有插件被启动时才付那 2.95MB 文案表。默认路径与现状相同。
- **导入成本纪律**：`festival_reminder/__init__.py` 与 `manifest.py` 不导入重服务，`app._build_plugin_registry` 用惰性工厂；实测 `import pet.app` 后两个重模块都不在 `sys.modules`。

## 三、实机运行记录

```text
$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q -p no:randomly \
    tests/test_plugin_runtime.py tests/test_festival_plugin.py \
    tests/test_festival.py::test_the_festival_service_can_be_assembled_from_the_phase2_plugin
22 passed in 2.40s

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q -p no:randomly tests/test_festival.py
73 passed in 3.89s

$ .venv/Scripts/python.exe -m ruff check pet tests scripts
All checks passed!
```

- **真 AppShell**：`test_the_festival_service_can_be_assembled_from_the_phase2_plugin` 用真实 `AppShell` + 临时 `Config`，验证插件实例、`is_running()`、关闭后 `plugin.state == "stopped"` 且 `festival_service is None`。
- **行为等价**：`tests/test_festival.py` 的 73 条内置路径用例全绿；`test_festival_plugin.py` 在端口路径覆盖启停/提醒/旧键映射。
- **未做人工桌面验收**：本会话没有可交互桌面；「右键提醒一次 / 到点弹气泡」的人工观感仍列为本片未验证项。机器判据覆盖真实 `FestivalReminderService` 与真实 Qt 控件。
- **全量分片门（最终）**：`python scripts/ci_shards.py --include-isolated --jobs 6` → **21/21 分片通过**（6 主分片 + 15 个隔离文件串行；墙钟 554.0s）。日志 `.scratch/final-full-shards-5.log`。

## 四、边界与未做

- **默认装配未切换**：`PET_FESTIVAL_PLUGIN=1` 是开发期对照开关；用插件替代内置构造需要维护者拍板（涉及回退策略与旧配置键的长期归属）。
- 不新增 Core 顶层 `plugins` 配置键；命名空间在 `plugins.json`，旧键原样保留。
- 不把签名功能包（`FeatureHost` / `feature_install_state`）接进 `PluginRegistry`；两条链保持独立（前者是磁盘验签包，后者是 Core 自己注册的 in-process 插件）。
- 不支持任意第三方 in-process Python 插件；`register_builtin` 只给 Core 自己的代码用。
- 不迁移旧配置键、不删除旧服务。

## 五、决策点（需维护者拍板）

1. 是否把默认装配切到插件（以及在切换后保留多久的内置回退）。
2. 旧 11 个扁平配置键是否长期保留为唯一真相，还是迁进插件命名空间并做一次迁移。
3. 插件的 `presentation` 端口与 AppShell 旧呈现策略的最终边界（当前共存期复用旧策略，避免分叉免打扰/飞行期语义）。
