# 官方功能领域交付矩阵（Phase 5B-4 起，2026-10-18 更新）

> 基线：`dlc/mod-center-port`，Phase 5C 完成后。
> 本文回答"11 个逻辑领域里，哪些已经是可安装的官方包、哪些继续留在 Core、为什么"。
> **不把设计当已交付**：「结论」列的"已交付"必须有包源码、构建器、生命周期测试；
> "保持 Core"必须有文件/探针证据。

## 判定口径

- **可拆性**：`host-only`（主进程内，无 Worker）／`host-worker`（包自带独立进程）／
  `core-bound`（与桌宠窗口、碰撞、托盘生命周期强绑定，拆出只会把 Core 掏空）。
- **依赖**：包声明需要的能力（`network.http` / `screen.capture` / `settings.contribute`
  / `menu.contribute` / `audio.speak` / `process.spawn` 等）。能力不在 v1 闭集里的，
  先扩能力模型再谈拆包。
- **数据边界**：用户数据必须在 `feature-data/<owner>/` 下；凭据走 OS 安全存储；
  卸载默认留数据、重装恢复。

## 矩阵（2026-10-18 最终口径）

| # | 领域 | 本仓库现状（证据） | 可拆性 | 关键依赖 / 边界 | 结论 |
|---|---|---|---|---|---|
| 1 | **AI 对话** | 内置 `pet/chat/` 与官方包 `features/ai-chat/` **共存**；包走 `LocalFeatureRuntime.attach_official`，装/启用/停用/卸载/重装 E2E 齐全 | `host-only` | `network.http`、`settings.contribute`、`menu.contribute`、`chat.contribute`、`files.user-selected.read`；凭据由 Core 端口注入 | **已交付（5B）**：Setup 回执 → 首启自动可用；生命周期闭环 |
| 2 | **文件理解** | 投喂接缝 `pet/file_interpret_router.py`：包窗开着走包，否则内置；停用/卸载回落 | 随 AI 包（`host-only`） | 不单独发 ZIP；不得绕过路由另建第二条投喂链 | **已交付（5B）**：卸载/停用无残留 |
| 3 | **屏幕理解** | 官方包 `features/screen-understanding/`（host + Worker + 冻结 exe），Phase 4 样板 | `host-worker` | `screen.capture`、`network.http`、`settings/menu.contribute`、Worker 管道与租约 | **已交付（4B/5A）**：后续只随 Core 升级 |
| 4 | **Agent / 外部工具** | `pet/agent_link.py` + DSH 桥接目录；进程内监控与钩子安装 | `core-bound` | 桥接目录是外部契约；v1 无 `os.hooks` / 进程枚举端口 | **保持 Core**：见 [`DLC-ARCHITECTURE-AUDIT-2026-10-18.md`](DLC-ARCHITECTURE-AUDIT-2026-10-18.md) §2 |
| 5 | **账户用量** | 官方包 `features/account-usage/`：查询、缓存、周期刷新、设置面板 | `host-only` | `network.http`、`menu.contribute`、`settings.contribute`、`balance.query` 凭据操作集 | **已交付（5C）**：安装/启停/卸载/重装闭环 |
| 6 | **音乐** | 官方包 `features/music/`：四个播放器发现与启动；歌词仍在内置 `pet/music_lyric*.py` | `host-only`（启动器）；歌词待续 | `process.spawn`、`menu.contribute`、`settings.contribute` | **已交付（5C，启动器）**；歌词富气泡另立片 |
| 7 | **语音报时** | 官方包 `features/voice-chime/`：调度/台词/气泡；合成与播放走 Core 唯一音频通道 | `host-only` | `audio.speak`、`menu.contribute`、`settings.contribute` | **已交付（5C）**：停用不残留定时器 |
| 8 | **生活提醒** | Phase 2 进程内插件 `pet/plugins/builtin/festival_reminder/`（`PET_FESTIVAL_PLUGIN=1`），行为等价 | `host-only` 可拆 | 2.95 MB 节日数据、11 个 legacy 配置键；拆包会复制数据与配置真相 | **保持 Phase-2 插件**：默认切换属产品决策，本轮不改 |
| 9 | **日常台词** | 官方包 `features/persona-phrases/`：按日期轮换、自定义台词、可选朗读 | `host-only` | `audio.speak`、`menu.contribute`、`settings.contribute` | **已交付（5C）** |
| 10 | **灵动岛** | `pet/dynamic_island.py`、每屏 `ScreenHost`、`info_mode` 主槽 | `core-bound` | 与窗口/屏幕拓扑强绑定；v1 无主信息槽贡献端口 | **保持 Core**：第三方只能加 `island_metrics` 段 |
| 11 | **趣味互动** | `pet/fun_image_popup.py`；本地素材 + 窗口行为 | `core-bound`（当前） | 需要 `window.popup` / 素材授权端口；气泡版会伪装成该领域 | **保持 Core（暂不拆）** |
| 12 | **快捷启动 / Harness** | 官方包 `features/quick-launch/`：五个用户指定程序入口；Harness 本体仍在 Core | `host-only`（用户入口） | `process.spawn`、`menu.contribute`、`settings.contribute`；Harness 走托盘/进程清理生命周期 | **已交付（5C，用户快捷启动）**；Harness 保持 Core |

> 注：12 行对应上游"11 个逻辑领域 + 文件理解作为 AI 的伴随能力"的口径差异；
> 领域数量不决定 ZIP 数量，允许共享受管理依赖或合包。

## 已确认的批次边界

- **5B**：AI 对话 + 文件理解 + Setup 回执 + 生命周期闭环；屏幕理解沿用样板。
- **5C**：账户用量、音乐启动器、语音报时、日常台词、快捷启动；补 presentation /
  scheduler / audio / 凭据操作集 / `process.spawn` 能力。
- **保持 Core 并留证据**：Agent、灵动岛、趣味互动、Harness；生活提醒保持 Phase-2 插件。
- **暂不排期**：歌词富气泡、社区生态（Phase 6 条件阶段）。

## 出口

每个领域进入实施前必须补齐：能力声明、数据/凭据边界、无包可用、装后入口、
停用不执行、卸载留数据、重装恢复、失败回滚。只有把这几条写成测试并过全量门，
才允许把矩阵里的「结论」写成"已交付"。
