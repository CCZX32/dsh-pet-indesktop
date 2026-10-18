# 官方功能领域交付矩阵（Phase 5B-4，2026-10-18）

> 基线：`dlc/mod-center-port`，5A Setup + 便携完成后。
> 本文回答"11 个逻辑领域里，下一个拆谁、为什么、依赖什么"。**不把设计当已交付**：
> 「现状」列只写本仓库真实存在的实现与文档证据；「建议批次」是排期建议，不是承诺。

## 判定口径

- **可拆性**：`host-only`（主进程内，无 Worker）／`host-worker`（包自带独立进程）／
  `core-bound`（与桌宠窗口、碰撞、托盘生命周期强绑定，拆出只会把 Core 掏空）。
- **依赖**：包声明需要的能力（`network.http` / `screen.capture` / `settings.contribute`
  / `menu.contribute` / `files.user-selected.read` / Worker 管道）。能力不在 v1 闭集里的，
  先扩能力模型再谈拆包。
- **数据边界**：用户数据必须在 `feature-data/<owner>/` 下；凭据走 OS 安全存储；
  卸载默认留数据、重装恢复。

## 矩阵

| # | 领域 | 本仓库现状（证据） | 可拆性 | 关键依赖 / 边界 | 建议批次 |
|---|---|---|---|---|---|
| 1 | **AI 对话** | 内置 `pet/chat/` 与官方包 `features/ai-chat/` **共存**（PORT-STATUS §九）；包走 `LocalFeatureRuntime.attach_official`，有装/启用/停用/卸载/重装 E2E（`tests/test_ai_package_e2e.py`） | `host-only` | `network.http`、`settings.contribute`、`menu.contribute`、`chat.contribute`、`files.user-selected.read`；凭据由 Core 端口注入 | **5B（本轮）**：Setup 回执 → 首启自动可用；生命周期闭环 |
| 2 | **文件理解** | 仅一个投喂接缝 `pet/file_interpret_router.py`：包窗开着走包，否则内置；包停用/卸载回落内置（`tests/test_file_interpret_router.py`、`test_ai_package_host.py`） | 随 AI 包（`host-only`） | 不单独发 ZIP；不得绕过路由另建第二条投喂链；模拟投喂不改真实文件 | **5B（本轮）**：卸载/停用无残留 |
| 3 | **屏幕理解** | 官方包 `features/screen-understanding/`（host + Worker + 冻结 exe），Phase 4 样板；Setup 选装与 MOD 中心安装都已验收（5A/4B） | `host-worker` | `screen.capture`、`network.http`、`settings/menu.contribute`、Worker 管道与租约 | 已完成样板，后续只随 Core 升级 |
| 4 | **Agent / 外部工具** | `pet/agent_link.py` + DSH 桥接目录 `%APPDATA%/dsh-pet-bridge`；进程内监控与钩子安装（`pet/agent_link.py`、`pet/uninstall_cleanup.py`） | `core-bound`（桥接目录是外部契约） | 需要 OS 级钩子/进程能力；包内执行外部命令会越过 v1 能力模型 | 5B 之后单独立项；先做能力模型审计 |
| 5 | **账户用量** | `pet/balance.py` + 灵动岛 `balance` 段；网络请求与凭据读取在 Core | `host-only` 可试 | `network.http`、凭据端口；状态要能被灵动岛消费（贡献面） | 5B-5 候选（第 2 批） |
| 6 | **音乐** | `pet/music_lyric*.py`、`pet/music_players.py`、播放器注册表；系统代理回退有专门文档 | `host-only`（歌词/识别） | `network.http`、用户选择的播放器路径、系统代理语义；不随包任何播放器 | 第 2 批 |
| 7 | **语音报时** | `pet/voice_chime_service.py`、`pet/tts/`、edge-tts 与多 provider（凭据在 OS 存储） | `host-only` | `network.http`、凭据端口、音频输出；包缺失时设置页不应崩 | 第 2 批 |
| 8 | **生活提醒** | Phase 2 已落进程内插件 `pet/plugins/builtin/festival_reminder/`（`PET_FESTIVAL_PLUGIN=1` 启用，默认内置）；`pet/festival_service.py` 端口化 | `host-only` | 调度器/呈现/音频/配置四个端口；默认仍走内置，插件化属行为等价 | 5B 后段（默认切换需产品决定） |
| 9 | **日常台词** | `pet/persona_phrases.py`、`pet/persona_presets/*.json`、气泡样式；纯本地 | `host-only` | 预设文件与用户台词分层；不得把内置预设当用户数据迁移 | 第 3 批（低风险） |
| 10 | **灵动岛** | `pet/dynamic_island.py`、`island_segments`、每屏 Host、扩展宿主 `island_extension_host.py` | `core-bound` | 与窗口/屏幕拓扑强绑定；拆包会让多屏宿主失去唯一真相 | 最后一批（或保持 Core） |
| 11 | **趣味互动** | `pet/fun_image_popup.py` 等；本地素材 + 窗口行为 | `host-only` 可试 | 素材授权、窗口生命周期；依赖 Core 的窗口面 | 第 3 批 |
| 12 | **快捷启动 / Harness** | `pet/harness_launcher.py` + `pet/quick_chat.py`；拉起外部进程、探测缓存 | `core-bound`（进程派生） | 需要进程派生能力与目录权限；v1 能力闭集不含 `process.spawn` | 需先扩能力模型 |

> 注：上表 12 行对应上游"11 个逻辑领域 + 文件理解作为 AI 的伴随能力"的口径差异；
> 领域数量不决定 ZIP 数量，允许共享受管理依赖或合包，但不得让独立能力变成强制全家桶。

## 已确认的批次边界

- **5B（本轮）**：AI 对话 + 文件理解 + Setup 回执消费 + 生命周期闭环；屏幕理解沿用样板。
- **5B 后段候选**：账户用量、音乐、语音报时（都是 `host-only`、网络/凭据面清晰）。
- **需要产品决策**：生活提醒是否切默认插件；灵动岛/Agent 是否保持 Core。
- **暂不排期**：快捷启动（先扩能力模型）、社区生态（Phase 6 条件阶段）。

## 出口

每个领域进入实施前必须补齐：能力声明、数据/凭据边界、无包可用、装后入口、
停用不执行、卸载留数据、重装恢复、失败回滚。只有把这几条写成测试并过全量门，
才允许把矩阵里的「建议批次」改成「已交付」。
