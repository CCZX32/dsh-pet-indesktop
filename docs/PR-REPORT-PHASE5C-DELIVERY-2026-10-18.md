# Phase 5C：Core / DLC 架构重构（2026-10-18）

> 基线：`dlc/mod-center-port`，Phase 5B 收尾（`a76bf94`）之后。
> 本轮把可拆领域做成官方功能包，并把 Core 需要提供的能力固化成端口；
> core-bound 领域给出可复核的保持理由。签名仍按既定决定不做。

## 0. 结论

- 新增 5 个官方 host-only 包：账户用量、音乐启动器、语音报时、日常台词、快捷启动；
  连同既有的 AI 对话、屏幕理解（文件理解随 AI 包）共 **7 个可安装包**。
- 新增四个公共能力：`presentation`（气泡/通知）、`scheduler`（owner 作用域定时器）、
  `audio`（Core 唯一音频通道提交面）、显式凭据操作集；另加声明式 `process.spawn`。
- 每个新包都有结构 / 构建 / 绑定 / 生命周期测试；Setup 选装、首启回执、
  冻结 probe 名单同步接线。
- **保持 Core**：Agent / 外部工具、灵动岛、趣味互动、Harness；生活提醒保持
  Phase-2 进程内插件。理由与证据见
  [`DLC-ARCHITECTURE-AUDIT-2026-10-18.md`](DLC-ARCHITECTURE-AUDIT-2026-10-18.md)。

## 1. 修改文件说明

相对 `a76bf94`：**80 个文件，+4715 / −27**（不含本报告与索引回写）。

### 5C-1 能力端口

| 文件 | +/− | 改了什么 + 为什么 |
|---|---|---|
| `pet/feature_ports.py` | +53 | 新增 `FeaturePresentationPort` / `FeatureSchedulerPort` / `FeatureAudioPort`，并挂到 `FeatureHostContext`；host-only 包此前只能弹设置页，无法把结果说给用户或按时间动作。 |
| `pet/feature_host_bindings.py` | +434 | 新增 `register_feature_presentation` / `register_feature_audio`、`_BoundPresentation`、`_BoundScheduler`、`_BoundAudio`，以及账户/音乐/语音/台词/快捷启动五个 owner 的绑定函数；每个绑定只给该 owner 自己的数据根与端口。 |
| `pet/credentials.py` | +14/−2 | `CredentialVaultPort(..., operations=...)`：新 owner 显式声明操作集（账户用量只有 `balance.query`），默认值保持识屏/AI 口径。 |
| `pet/feature_management.py` | +29/−2 | `_official_binder` 增五行 owner → 绑定路由；新增官方包只改这一张表。 |
| `pet/app.py` | +20/−4 | AppShell 注册/摘除呈现面与音频通道提供方；都是惰性工厂，没有可见窗时端口安全降级。 |

### 5C-2～5C-5 官方包

| 文件 | +/− | 改了什么 + 为什么 |
|---|---|---|
| `pet/official_features.py` | +35 | 闭集新增 5 个 owner（factory / execution_kind / capabilities）；`process.spawn`、`audio.speak` 进入官方能力声明。 |
| `pet/official_package_source.py` | +25/−1 | 显示名 / 短名 / 构建器三张表补齐五个包，源码态按需构建。 |
| `pet/startup_receipt.py` | +14/−1 | 回执键 `account_usage` / `music` / `voice_chime` / `persona_phrases` / `quick_launch` 映射到 owner 与 `features/<dir>`。 |
| `packaging/dsh-pet.iss` | +51/−3 | 五个新可选 Task、基础复制 Excludes、Task-scoped Source、未选清空目录、回执按盘上 manifest 写。 |
| `scripts/build_host_package.py` | +74 | 通用 host-only 构建器：`mod.json` + `host/` → 目录 + ZIP + 官方验签。 |
| `scripts/build_{account_usage,music,voice_chime,persona_phrases,quick_launch}_package.py` | +93/+92/+92/+38/+38 | 各包薄封装；账户/音乐/语音保留各自的清单文案与自检入口。 |
| `features/account-usage/` | 8 文件 | 查询、缓存、周期刷新、设置面板、凭据库操作集。 |
| `features/music/` | 8 文件 | 四个播放器的有界发现与启动、手动路径设置。 |
| `features/voice-chime/` | 9 文件 | 调度/台词/气泡在包内；合成与播放只提交给 Core 音频通道。 |
| `features/persona-phrases/` | 8 文件 | 按日期轮换台词、自定义台词、可选朗读。 |
| `features/quick-launch/` | 8 文件 | 五个用户指定程序入口，路径必须真实存在。 |
| `scripts/verify_frozen_mod_api.py` | +14/−1 | 冻结 probe 名单补五个包。 |
| 测试 | 12 文件 | 端口、结构、构建、绑定、设置、安装/启停/卸载/重装闭环。 |

## 2. 性能分析

环境：Windows 本机，`.venv` Python 3.12，`QT_QPA_PLATFORM=offscreen`，共享
`QApplication`。命令与样本量写在每行括号里。

| 路径 | 实测 | 触发频率 | 结论 |
|---|---|---|---|
| `bind_persona_context`（代表任一 host-only 绑定） | **224.9 µs/call**（500 次，含 mkdir/配置绑定） | 每个 owner 挂载一次 | 一次性成本；不进入菜单/命令热路径。 |
| `scheduler.call_later` + `cancel` | **15.0 µs/op**（1000 次） | 定时器重排（语音报时每次触发一次、账户刷新每次一次） | 亚毫秒级；最低触发间隔 1 分钟，稳态可忽略。 |
| `seconds_until_next` | **6.41 µs/call**（20000 次） | 每次报时触发一次 | 纯函数，无 I/O。 |
| `pick_phrase` | **0.31 µs/call**（20000 次） | 每次台词命令一次 | 纯函数，无 I/O。 |
| `import pet.feature_ports` | **24.54 ms**（独立进程冷导入） | 宿主启动/预检子进程 | 只依赖标准库，不拉 Qt；`pet.mod_api.v1` 43.26 ms、`pet.official_features` 17.61 ms 是既有导入。 |

逐条回答交付纪律要求：

- **稳态开销**：没有新包安装/启用时，Core 不创建定时器、线程或缓存；AppShell 只
  注册三个惰性工厂（不解析目标）。
- **新增路径成本**：绑定 0.22 ms/owner（挂载一次）；命令入口现读一次偏好
  （小 JSON 一次读）；账户查询成功写一次 `balance_cache.json`（原子替换）。
- **新的系统调用/网络/磁盘/线程**：账户包在手动/周期查询时起一个 daemon 线程并发
  一次 HTTPS；音乐/快捷启动在点击时起一个 daemon 线程做路径检查与启动；语音包
  不自行合成/播放，只调用 Core 通道。没有常驻线程。
- **内存**：每个启用 owner 一份 `FeatureHostContext` + 一个活动 `QTimer`；账户包最多
  一份 30 秒 TTL 的缓存文件；没有进程级字典缓存增长。

## 3. 实机运行记录

### 3.1 包构建与预检（真实产物）

```text
python scripts/build_account_usage_package.py ...
python scripts/build_music_package.py ...
python scripts/build_voice_chime_package.py ...
python scripts/build_persona_phrases_package.py ...
python scripts/build_quick_launch_package.py ...
python scripts/verify_feature_package.py --bundle-root <root> --official --target-platform win32
```

输出（节选）：五个包均为 `host-only`，`装前预检：通过`；账户/音乐/语音/台词/快捷
启动的贡献数分别为 1 / 4 / 1 / 1 / 5。

### 3.2 自动化门

```text
QT_QPA_PLATFORM=offscreen pytest \
  tests/test_package_capability_ports.py \
  tests/test_account_usage_package_*.py \
  tests/test_music_package.py \
  tests/test_voice_chime_package.py \
  tests/test_persona_package.py \
  tests/test_quick_launch_package.py
→ 新增聚焦用例全绿
ruff check pet features tests scripts → All checks passed
```

（`tests/test_pr_report_discipline.py` 与全量分片门结果见 §3.6。）

### 3.3 冻结构建与 Setup

```text
pwsh scripts/build_onedir.ps1 -Variant webm-chat \
    -FeaturePackages .scratch/phase5c-packages -OfficialFeaturePackages
→ [frozen-probe] ai-chat (official.ai-chat): ok
  [frozen-probe] screen-understanding (official.screen-understanding): ok
  [frozen-probe] account-usage (official.account-usage): ok
  [frozen-probe] music (official.music): ok
  [frozen-probe] voice-chime (official.voice-chime): ok
  [frozen-probe] persona-phrases (official.persona-phrases): ok
  [frozen-probe] quick-launch (official.quick-launch): ok
  [frozen-probe] 7 package(s) passed
  [features] bundle carries verified feature packages under features\

ISCC.exe packaging/dsh-pet.iss
→ Successful compile (158.109 sec)
  E:\Work\dsh-pet\dsh-pet-indesktop\dist-onedir\dsh-pet-standalone-webm-chat-setup.exe
```

### 3.4 七包 Setup + 首启回执实测（隔离 APPDATA）

```text
install exit=0
receipt before launch: True
process exited early: False
receipt after launch: False
owner official.ai-chat: versions=True            enabled=true
owner official.screen-understanding: versions=True enabled=true
owner official.account-usage: versions=True      enabled=true
owner official.music: versions=True              enabled=true
owner official.voice-chime: versions=True        enabled=true
owner official.persona-phrases: versions=True    enabled=true
owner official.quick-launch: versions=True       enabled=true
log: 启动回执处理完成 requested=(7 个 owner) installed=(7 个 owner) skipped=() missing=() failed=()
uninstall exit=0 dir_exists=False
autostart restored
```

即：Setup 勾选七个包 → 首启消费回执并**逐个启用** → 回执删除 → 卸载目录清空。
脚本 `.scratch/receipt-gate-5c.ps1`，原始输出 `.scratch/receipt-gate-5c.log`。

### 3.5 七包同装（源码态事务链）

```text
LocalFeatureRuntime(role="core") → 依次 official_source + install_official(enabled=True)
menu owners: 7
  official.account-usage, official.ai-chat, official.music,
  official.persona-phrases, official.quick-launch,
  official.screen-understanding, official.voice-chime
ALL-SEVEN-OK
```

七个包在同一宿主内可同时挂载，没有命令名/贡献 id 冲突；随后 `runtime.close()`
正常收口。

### 3.6 全量分片门

并发全量门先后暴露两个**短预算时序前提**（不是产品失败）：

- `tests/test_overlay_hidden_polling.py::test_hidden_overlay_polls_nothing`：
  400 ms 内要求光标轮询 ≥2 次，4 路负载下只跑到 1 次；单跑绿。
- `tests/test_context_menu_lifecycle.py::test_delete_when_idle_timer_drops_after_menu_destroyed`：
  把 50 ms 轮询的调用次数钉死为 1，主线程被调度走一个周期后变成 2；单跑绿。

按 `AGENTS.md` 的时序测试纪律，两处改为宽预算/「至少一次」判据（不改变产品断言），
然后重跑标准门。最终结果与日志回写如下。

`python scripts/ci_shards.py --include-isolated --jobs 4`：

```text
shard 01: ok  496.1s  2563 passed, 4 skipped
shard 02: ok  642.6s  2200 passed
shard 03: ok  663.2s  2123 passed, 10 skipped
shard 04: ok  607.3s  2136 passed, 6 skipped
isolated 01..15: ok（19 个隔离分片全过）
总耗时 855.8s（墙钟）；全部 19 个分片通过
```

即 **9022 passed / 20 skipped，0 failed**。日志 `.scratch/final-full-shards-5c-4.log`。

## 4. 边界与未验证

- 包菜单只落在「扩展」子菜单；没有注入内置「音乐」「余额」等主位置。
- 音乐包只做启动器；歌词富气泡、正在播放控制仍在 Core（需要更富的 presentation 契约）。
- 语音包只拆调度/台词；TTS provider、缓存、播放、免打扰仍由 Core 唯一通道承担。
- 趣味互动没有拆：需要窗口/素材端口，气泡版会伪装成该领域。
- 生活提醒保持 Phase-2 插件（默认切换是产品决策）。
- 没有做签名；没有人工点击向导 UI / 干净机器 / 其它变体验收。
- 冻结产物的七包安装/首启回执已用隔离 APPDATA 的 Setup 实测覆盖（§3.4）；
  未做的是人工点击菜单/设置面板的观感验收。

## 5. 后续入口

1. `island.contribute`：灵动岛主槽/段贡献协议。
2. `window.popup` + 素材授权：趣味互动拆包。
3. 歌词富气泡：音乐包第二阶段。
4. 生活提醒默认切换：先做 11 个 legacy 键与 2.95 MB 数据的归属决定。
