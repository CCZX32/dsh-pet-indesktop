# 上游对齐说明（2026-10-17）

> **读者**：上游插件化分支的作者与他的 AI 助手。
> **这份文件回答三件事**：本仓库把插件化移植到哪了、你现在按下 Phase 5B 会不会撞车、两边各自该做什么。
> 本文是**双向交接**，不是本仓库的内部状态表——内部状态表是
> [`modding/PORT-STATUS.md`](modding/PORT-STATUS.md)（§十一 未移植账本、§十二 主干减法）。

---

## 0. 一句话

本仓库已经把插件化**架到新架构上**了：Phase 1（换形）、Phase 2 底座、3B、4A、
4B-1/2/3/4、AI 对话与屏幕理解两个官方包全部落地，均已在 `dlc/mod-center-port` 分支上。
**没落的三块**是：内容硬门（`pet/content/` 那套版本指针与事务）、Phase 2 的四个具名内核
+ 节日提醒插件化、以及冻结/Setup/签名链。

---

## 1. 你问的三件事，直接回答

**「dlc 线现在拆完了吗」**——没有。已拆：屏幕理解（`features/screen-understanding/`）、
AI 对话（`features/ai-chat/`），两个都是官方包、走 Core 自有装配链。剩下的是本文件 §3 的账本。

**「就是你上次说的那两个模块」**——准确说是**三块**，而且前两块是前置、第三块是大头：

| 块 | 是什么 | 为什么卡路 |
|---|---|---|
| ① 内容硬门 | `pet/content/` 里与版本指针无关的那几项：逻辑 SHA-256、事务日志与崩溃恢复、激活后自检、manifest 严格契约 | 官方包"装不半成品"的机器保障；你的推进顺序里 4B-1.5 排在官方功能选装之前 |
| ② Phase 2 内核 | `PluginRegistry` / `PluginContext` / `PluginManifest` / `PluginConfigStore` + `builtin/festival_reminder` | "连节日提醒都是包"的直接前提；现在节日提醒仍硬绑 `AppShell` |
| ③ 冻结 / Setup / 签名 | `core_webm.iss` 选装、`build_screen_worker` / `build_feature_probe*` / `build_feature_release`、`feature_release_*` 与 `release_distribution` | 可以最后做，但依赖 ① 与 `pet/core_*` 一批模块 |

**「都写一下吧」**——见 §3（账本）、§4（你按 5B 拆解前必须知道的三件事）、§5（分工）。

---

## 2. 为什么只能移植、不能合并

本仓库走的是**另一条拓扑**，与上游分支的分支点是 2026-09-24、在 overlay 重构之前：

- **单进程 overlay 单合成窗多宠**：所有 sprite 在一个透明全屏窗里，多宠在进程内；
  每个被占用的显示器一张 `OverlayWindow`，由 `pet/screen_host.ScreenHost` 持有该屏的行为/碰撞/物理世界；
- **固定身份槽位 0..128**（`pet/pet_profiles.py`，`config-slot-N.json`）；
- **进程内碰撞世界** `SpriteCollisionWorld`（多进程碰撞 IPC 那一层在 2026-09 已退役）；
- **D12 单一指令通道**（`overlay_settings_command`）；
- 跨屏能力由全局 `allow_cross_screen` 闸门控制，默认关。

所以你的 `pet/content/` 版本化布局、`PluginRegistry`、冻结链这些东西**能搬的是能力，不能搬的是文件**。

---

## 3. 移植账本（按你的 phase 顺序）

判定口径：`git diff --name-status` 对基线逐文件比对（874 个改动文件，已排除素材与工作档案），
同名文件用 blob 比对判"逐字节相同"。

| 你的 phase | 你的产物 | 本仓库状态 | 具体差异 |
|---|---|---|---|
| Phase 1 | `pet/content/` 8 文件（ContentManager / CharacterRegistry / 版本化 `active.json`·`previous.json`） | ⚠️ **换形 + 6 项能力真缺** | 能对上：安装、staging、停用、删除、手动回滚、路径/可执行/ZIP 越界拒绝。**缺**：任意版本激活（`activate(id, version)`；本仓库 `rollback` 只能回保留版里 semver 最大那个）、逻辑 SHA-256（目录与 ZIP 同 digest、跳过 `manifest.json`）、事务日志 + 崩溃恢复、激活后自检 + 失败回退、manifest 严格契约（`kind`/`api_version`/`core_requires`/`platforms`/禁 entrypoint/派生 cache 必须在包外；本仓库版本不合法时回落 `0.0.0`）、bundled/Starter、结构化坏包诊断、`python -m pet.content` CLI |
| Phase 2 底座 | `events.py` / `capabilities.py` / `contributions.py` / `ports.py` / `package_binding.py` | ✅ **逐字节相同** | 五个文件 blob 完全一致；`feature_host.py` = 你的 +93 行（把 EventBus 接进启停/故障） |
| Phase 2 具名内核 | `pet/plugins/runtime.py`（`PluginRegistry`/`PluginContext`）、`manifest.py`、`config.py`、`builtin/festival_reminder/` | ❌ **未移植** | `PluginRegistry`/`PluginContext` 零命中；能力集由 `pet/feature_policy.py` + 签名包契约给，`FeatureHostContext` 靠 `feature_host_bindings.py` 手工注入，没有 manifest→capability 自动装配；节日提醒仍是内置服务（`festival_service.__init__(self, app)`，开关走 11 个扁平键） |
| Phase 3A | agent-link worker 3 文件 | ⛔ **拍板不移植** | 主线 `pet/agent_link.py` 是现行权威（多 DSH 分区语义与采集 worker 冲突） |
| Phase 3B | `worker/runtime.py` → `worker/vision.py` | ⚠️ **换形** | `worker/runtime.py` → `pet/workers/proactive_screen_worker.py`；`worker/vision.py` → `pet/vision.py`（函数面为超集）。执行位置是设置页显式二选一（子进程 / 进程内） |
| Phase 4A | `features/screen_understanding/` 26 文件 | ⚠️ **换形，3 个未移植** | **14 个逐字节相同**、6 个同名小改（`contributions.py` 菜单工厂改两参、`factory.py` 改交 `ScreenPackageRuntime` 并新增 `bind_lifecycle`、`limiter.py`/`memory.py` 的 `except` 加 `StateError`、`manual.py`/`runtime.py` 的 vision 来源改 `pet.vision`）、3 个换形（worker 入口 → `worker-src/entry.py` 带租约认领与 fail-closed 77、worker runtime、worker vision）。**未移植**：`host/migration.py`（内置识屏→包的配置迁移）、`manual_for` 这类从 Core 窗口直接拉起的入口、两个一行 docstring 的 `__init__.py`。本仓库另有 `mod.json` / `host/current.py` / `host/runtime_mount.py` 是本地新增 |
| Phase 4B-1/2/3 | 状态账本 / 跨进程租约 / 事务 | ✅ **换形移植** | `feature_install_state.py`、`feature_version_lease.py`、`feature_package_transactions.py`（1199 行）、`feature_state_io.py`、`feature_package_startup.py` 都在；`test_feature_install_state` / `test_feature_version_lease` 是你的 280 个测试改动里**仅有的两个**逐字节相同 |
| Phase 4B-4 | 管理 UI | ✅ | 设置页「扩展管理」域，功能扩展格已由 `LocalFeatureRuntime` 回填 |
| Phase 4B-5 | 真实构建端到端 | ❌ | 源码态全链路可跑；冻结 exe / host-worker 真实冻结构建未做 |
| Phase 5A | Setup 选装 / 便携 / Ed25519 签名 | ❌ | `scripts/` 你 57 个改动里 34 个没有对应物，`packaging/` 12 个里缺 9 个；依赖侧的 `pet/core_maintenance.py`、`core_code_gate.py`、`core_uninstall.py`、`runtime_layout.py`、`feature_probe_*.py`、libsodium license **一个都没有**。**唯一有对应物的是 `build_mod_example.py`**（换形移植，行为多于你的版本：退出码、装前子进程预检、`host/` 出现非 `.py` 直接中止） |
| Phase 5B | AI 对话整包 | ✅ **全量** | 你的 `features/ai_chat/` 30 个文件全在（目录名改连字符），本仓库多 `mod.json` + `host/contributions.py` + `host/runtime_mount.py`。**但形态是「共存」不是「替换」**：内置 `pet/chat/` 一个字节没动，包开自己的窗口、用自己那本配置与会话账 |
| 文档与示例 | `docs/modding/*` 10 篇、`docs/plugin-*` 28 篇、`examples/mods/` 11 个文件 | ✅ **逐字移植** | 死链已降级为「文字 + 反引号路径」 |

---

## 4. 你按 Phase 5B 继续拆解前，必须知道的三件事

**① 官方包安装没有你那套内容硬门的机器保障。** 本仓库的启用态用**目录位置**表达
（`characters/<id>/` vs `mod-disabled/<id>/`），没有 `active.json`/`previous.json`；
回滚依据是 `mod-versions/<id>/<version>/` 枚举。所以你的包如果在设计里假设
"激活 = 写指针 + 自检 + 失败回退"，在本仓库要换成"目录换入 + 失败还原"，
而**逻辑 SHA-256 与事务恢复这两条是缺的**（跟指针无关，是独立的洞）。

**② 没有 `PluginRegistry`/`PluginContext`，manifest→capability 自动装配不存在。**
你的包 manifest 在本仓库走的是**签名包契约**（`package_trust.py`：id/version/api_version/
core_requires/platforms/capabilities/factory/worker/files + 逐文件 sha256 + 祖先快照），
形状不同、**更严**。能力集由 `pet/feature_policy.py`（唯一真相源，零 Qt）给。
所以如果你 5B 的包里用到 `PluginContext` 的整套 scoped 端口，需要改成
`FeatureHostContext` + `bind_*` 的形式。

**③ 节日提醒还是内置。** `festival_service.__init__(self, app)` 这个签名就是不拆包的天花板。
你说"终态连节日提醒都是包"，本仓库这一刀还没切。

---

## 5. 分工建议（避免重复劳动）

- **你那边**：继续 Phase 5B 的**功能归属设计与包内实现**（F01–F11 的拆解批次、包内 UI/会话/
  专属依赖）。建议按功能域做，**不要依赖 `pet/content/` 的具体 API 形状**——那套在本仓库不存在。
- **这边**：新架构适配、Core 侧接线、三端发布与在线更新。
- **高危共享文件**（双方都可能改，动之前先打个招呼，否则每次都手工解冲突）：
  `pet/app.py`、`pet/modern_settings_dialog.py`、`pet/feature_host_bindings.py`、
  `pet/plugins/*`、`pet/settings_mod_domain.py`、`features/*/host/factory.py`。
- **不要同时做同一件事**：冻结/Setup/签名链、内容硬门、Phase 2 内核这三块，
  谁做先说一句，避免两头都改一半。

---

## 6. 需要你确认的五个问题

1. **5B 的拆解批次**：按 F01–F11 逐个出包，还是按「GUI 主进程组件 + Worker」合成几个包？
   这决定本仓库 `features/` 的最终布局。
2. **内容硬门**：按你的 `active.json`/`previous.json` 补进来，还是接受本仓库的
   「目录布局 + 回滚」并把逻辑 SHA-256 / 事务恢复单独补成两项能力？
3. **节日提醒插件化**的优先级：放 5B 拆解之前，还是之后？
4. **`host/migration.py`**（内置识屏 → 包的配置迁移）要不要做？本仓库当前选择是
   「包用独立新配置、不迁移」，代价是老用户的识屏配置不会自动带进包。
5. **冻结/Setup/签名链**要不要在 4.3.x 这条发布线上推？本仓库现有发布线是
   onedir + Inno Setup + 在线更新，签名口径是 `local_user`（不声称发布者认证）。

---

## 7. 路线规划（本仓库视角，按卡路顺序）

```text
① 内容硬门（逻辑 SHA-256 / 事务恢复 / 激活后自检 / manifest 严格契约 / 任意版本激活）
      ↓ 前置：官方功能选装不能没有它
② Phase 2 内核收口（四个具名件 + 节日提醒插件化）
      ↓ 前置：终态"一切都是包"
③ 冻结 / Setup / 签名链（依赖 ① + pet/core_* 一批模块）
      ↓
④ Phase 5B 其余功能域拆解（与上游分工推进）
```

三块目前**都未排期**——它们不是"没时间"，是"没定顺序"。§6 的五个问题答完，
顺序就能定下来。本文的账本与顺序都以 **2026-10-17 的上游分支快照**为准，
上游继续前进时要重跑核对命令，不要照抄结论。

---

导航：[移植状态对照](modding/PORT-STATUS.md) · [交接工作包](DLC-HANDOFF-2026-10-15.md) ·
[作者总路线图](plugin-roadmap/PLUGIN-DLC-ROADMAP-v5.md) ·
[功能交付总表](plugin-roadmap/PLUGIN-FEATURE-DELIVERY-MATRIX.md) · [全文档索引](INDEX.md)
