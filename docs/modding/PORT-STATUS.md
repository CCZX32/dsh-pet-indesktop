# DLC 设计移植状态对照（phase 1 / 2 / 3A / 3B / 3C / 4A / 4B / 5A / 5B / 6 / 7）

> **移植基线（2026-10-13，本仓库分支 `dlc/mod-center-port`）**：本文是本仓库自己的状态文档
> （不是移植件），分支名与基线 SHA 属仓库内工作档案，见 `.scratch/dlc-fusion/PLAN.md`。
> 对照对象是**上游 DLC 分支**的 `docs/plugin-roadmap/` 与 `docs/plugin-phase-01..07/`
> （本轮逐字移植进本仓库同路径，每篇带统一移植基线头）。本文正文不写外部工具名。

**这份文档解决什么问题**：上游作者的插件 / DLC 设计文档（phase 1 → 7）里到处写着「已实现」
「已完成基线」，但那些句子说的是**上游分支自己的进度**。本仓库是另一条拓扑上的移植线，
只落了其中一部分。读作者文档时对不上号，就来查这里：每个 phase 的**目标**（引用他的文档）、
**本仓库状态**（✅ 做到 / ⚠️ 半做 / ❌ 未做）、**证据落点**（文件:行号或测试名）、
**没做的原因与后续片归属**。

**先读的相邻文档**：[`README.md`](README.md) 的「移植基线与现状」表是本文的角色资源面摘要；
[`../PR-REPORT-DLC-MOD-CENTER-2026-10-13.md`](../PR-REPORT-DLC-MOD-CENTER-2026-10-13.md)
是六片移植的交付证据汇总。[`../INDEX.md`](../INDEX.md) 是全文档入口。

> **快照口径（重要）**：本文的 ✅ / ⚠️ / ❌ 判定以本仓库 **HEAD `7575572`** 为基准，证据由
> 文中列出的命令与测试当场核过（核验时点 2026-10-13 22:10）。
> **写作期间同一工作树内另有一片正在落地「宿主侧运行时」**——写作时它还是未提交状态。
> 那一片（D2）与随后的 D3 已分别提交，**本文 §二 的格子里凡与之冲突的，以 §六「D2 / D3 回写」
> 为准**；§二 正文按快照基线保留原样，不复写历史判定。引用前先复核一次
> `git ls-tree -r --name-only HEAD | grep <路径>`。

---

## 一、五条必须先知道的口径（2026-10-13）

1. **功能扩展包 ZIP 导入在本仓库是"显式用户信任 + 装前子进程预检"**，不是沙箱。本仓库
   **没有** LPAC 原生探针沙箱与其 `_internal/feature-probe` 密封 bundle——那条流水线要
   钉版 PyInstaller 源码 tarball + MSVC + 官方 libsodium + AppContainer canary，属**未排期的
   构建片**。默认装配因此仍然是 fail-closed：`FeaturePackageTransactionService` 见
   `self_checker.available is False` 即抛 `self_check_sandbox_unavailable`
   （`pet/feature_package_transactions.py:772`；守卫
   `tests/test_feature_package_transactions.py::test_default_selfcheck_fails_closed_without_os_sandbox`
   继续绿——**那条纪律一个字没改**）。
   本地用户自选包走的是**另一条明确的口子**：生产装配注入
   `pet/feature_management.LocalUserTrustSelfChecker`（`available=True`，Phase 5A 的
   "本地激活是用户明确选择的信任边界，不是发布者认证"），它做三件事——重新验签/指纹对账、
   host-worker 的 worker 路径边界断言、以及（D3 起的默认装配）把包交给
   `pet/feature_package_preflight` 在**子进程**里装前预检一次。探针只回答"包装载得起来吗、
   `create_host()` 说的 owner 与清单一致吗"，**只在拒绝方向有权威**：没有 OS 沙箱、环境清理
   与超时都不是安全边界，说行的那一半仍由宿主按完整验签链重新回答。
   作者文档里「目录可以、ZIP 不行」那个差异**在本仓库没有复现面**——ZIP 与目录在
   `preflight_*` 里都被归一成同一个已解包的 `staged_root`，探针看到的也只有那一份。
2. **`pet/plugins/` 在 HEAD 里只留了 `package_trust.py`**（705 行：验签 / 清单 / 指纹 /
   路径边界 / 祖先快照，零 Qt；`FeaturePackageVerifier:420`、`read_manifest_registration:343`、
   `SigningKeyPolicy:394`）。`git ls-tree -r --name-only HEAD | grep '^pet/plugins/'` 只有
   `__init__.py` 与它。**进程内的功能扩展宿主运行时未移植**——`pet/mod_api/`、
   `pet/feature_ports.py`、`pet/api_ports.py`、`pet/feature_management.py`、
   `pet/local_package_intents.py`、`pet/plugins/{ports,capabilities,contributions,feature_host,feature_packages,package_binding,worker_launch}.py`
   在 **HEAD** 里都不存在（**但工作树里已有一片未提交的宿主侧运行时正在落地**，见上文
   「快照口径」；`pet/plugins/runtime.py`、`pet/plugins/services.py` 至今仍不存在）；
   MOD 中心的 `extensions()` 注册表**当前仍恒空**（`pet/settings_mod_domain.py:147`
   → `return {}`，2026-10-13 22:10 复核），导入功能扩展包会拿到一句能照做的拒绝语
   （`pet/mod_center_controller.py:198/214`）。
3. **workers 底座在，识屏 worker 试点完成；agent-link worker 未移植**。
   `pet/workers/` 有 `protocol.py`（`pet-worker/v1`）、`supervisor.py`、`launch.py`、
   `proactive_screen_worker.py` + `proactive_screen_adapter.py`、`screen_entry.py`；
   **没有** agent-link worker——主线 `pet/agent_link.py`（6303 行）+ 多 DSH 分区是现行权威，
   PLAN.md 判定「暂不移植」。
4. **打包 / 分发链一个文件都没移植**。作者的 Setup 选装、旁置本地包、显式便携、
   `scripts/build_{mod_example,character_mod_example,screen_worker,feature_probe,feature_release}.py`
   在本仓库**全部不存在**；`packaging/` 与 `scripts/build_*` 里只有本站既有的 onedir / Inno
   Setup 构建。
5. **「热插拔」这个词在作者文档里是刻意避开的**。正确说法是**「可停用 / 可卸载 / 进程级卸载」**；
   **Python 模块热卸载不承诺**——`feature_host` 一旦进入解释器，`sys.modules`、Qt 对象、回调、
   定时器、线程和第三方库全局状态都可能仍留引用，用 `stop()`/`dispose()` 撤销菜单也不能严谨地
   说"模块已卸载"。完整论证与九条「真正无重启卸载」的充要条件见
   [`../plugin-roadmap/PLUGIN-DLC-OPENING-ORDER-AND-THIRD-PARTY-INTERFACES.md`](../plugin-roadmap/PLUGIN-DLC-OPENING-ORDER-AND-THIRD-PARTY-INTERFACES.md)
   §8（:442-526）。凡本仓库文档写「停用」「进程级卸载」都是这个口径，**不要**改写成"热插拔"。

---

## 二、逐 phase 对照

### Phase 1：资源型 DLC 架构基线

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PLUGIN-DLC-ARCHITECTURE.md`](../plugin-phase-01-foundation/PLUGIN-DLC-ARCHITECTURE.md)：`CharacterRegistry` 来源顺序、`ContentManager` 目录/ZIP 安装、manifest/`kind=content`/版本/Core/平台/路径安全/逻辑 SHA-256、staging + 多版本 + `active.json`/`previous.json` + 原子激活 + 自检回滚、Starter。§8 另列 P0 资源硬门（安装→Registry→播放、冲突清理、Starter/Core 更新保护、发布内容与派生 cache 隔离）。 |
| 本仓库状态 | ⚠️ **半做，且换了形**。本仓库**没有 `pet/content/`**（`ContentManager` + `CharacterRegistry` + `versions/<v>/active.json/previous.json` 这套版本化布局不存在，也没有 Starter 这个资源包概念）。角色包闭环由 **MOD 中心这条腿**交付：托管布局 `characters/` `mod-disabled/` `mod-versions/<id>/<version>/`、ZIP/目录导入归一、原子发布、符号链接/越界拒绝、占用未释放就拒绝破坏性操作。 |
| 证据落点 | `pet/mod_catalog.py`（102 行，目录枚举 + 跨进程失效令牌）、`pet/mod_management.py`（563 行，`_materialize:389`；模块 docstring 明写"本拓扑没有 `content/` 树"）、`pet/catalog.py:215 resolve_character_video_dir` / `:230 list_available_characters` / `:256 load_character_manifest`；测试 `tests/test_mod_catalog.py`、`tests/test_mod_management.py`。 |
| 没做的原因 / 后续归属 | 作者 §8 那组 P0 硬门（Starter 归属、安装后 Registry 解析、冲突安装保留旧 active）在本仓库**没有对应物**——不是没做，是本仓库没有那套版本指针与 Starter 概念，**不适用**。「资源回滚」有对应物（`mod-versions/` + `ResourceMods.rollback`）。后续片：无，这条腿在 S1b-1 / S1b-2 已收（见 S4 前作 `.scratch/dlc-fusion/S1b-1-HANDOFF.md`、`S1b-2-HANDOFF.md`）。 |

### Phase 2：Core 插件运行时（Registry / Context / EventBus / capability）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PLUGIN-RUNTIME-DESIGN.md`](../plugin-phase-02-runtime/PLUGIN-RUNTIME-DESIGN.md) + [`README.md`](../plugin-phase-02-runtime/README.md) + [`PLUGIN-RUNTIME-TEST-PLAN.md`](../plugin-phase-02-runtime/PLUGIN-RUNTIME-TEST-PLAN.md)：`PluginRegistry` / `PluginContext` / `CoreEventBus` / 配置命名空间隔离 / capability / 生命周期与错误隔离；官方节日提醒作为接口验证消费者；后续补菜单·设置·快捷键贡献的按包所有者注册与撤销。 |
| 本仓库状态 | ❌ **未移植**。仓库内 grep `PluginRegistry` / `PluginContext` / `CoreEventBus` **零命中**（2026-10-13 22:10 复核，含工作树里那片并发落地的新模块）。 |
| 证据落点 | HEAD 的 `pet/plugins/` 只有 `__init__.py`（13 行）+ `package_trust.py`。反向证据：`grep -rn "PluginRegistry\|CoreEventBus\|PluginContext" pet/` → 0 命中。节日提醒在本仓库是既有功能（`pet/festival*.py`），**不经插件运行时**。 |
| 没做的原因 / 后续归属 | Phase 2 的运行时是「官方功能包宿主」的内核，而本仓库的**功能扩展宿主整层**在 HEAD 里未移植（见 Phase 4A/4B；工作树里那片并发落地的是**端口与宿主骨架**，尚未出现 Registry/Context/EventBus 这三个具名内核）。单独搬一个没有消费者的 Registry/EventBus 只会多一层死架构。后续片：随功能扩展宿主接入片一起（**未排期**，前置是 MSVC 构建片）。 |

### Phase 3A：Agent Link 采集 Worker（作者已封存）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PHASE3A-STABILITY-CLOSEOUT.md`](../plugin-phase-03-worker/PHASE3A-STABILITY-CLOSEOUT.md)：Agent Link 事件采集拆进 QProcess worker（握手 / 心跳 / 关闭 / generation / 有限重启 / fallback / 背压 / 真实进程测试），并出一份三份证据齐备的稳定性封存报告。 |
| 本仓库状态 | ❌ **未移植，且是刻意不移植**。PLAN.md 的移植判定表里这一条写的是「暂不移植」。 |
| 证据落点 | 主线权威：`pet/agent_link.py`（**6303 行**）+ `pet/dsh_state.py`（957 行，8 态收敛器）+ `DshMonitor`（`pet/agent_link.py:2140`，DSH 桥目录的唯一读者，见根 `AGENTS.md`）。反向证据：`pet/workers/` 下**没有** agent-link worker，只有 `proactive_screen_worker.py`。 |
| 没做的原因 / 后续归属 | 主线的 agent_link 已经实现且是现行权威（多 DSH 分区、回合身份、呈现管线的修复批都在上面）；DLC 的采集 worker 与主线分区语义冲突，硬搬会把现行权威拆成两份。后续片：**无**（除非主线自己要重构 agent_link，那也不是 DLC 移植线的事）。 |

### Phase 3B：主动识屏 Worker（作者的样板）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PHASE3B-PROACTIVE-SCREEN-DESIGN.md`](../plugin-phase-03-worker/PHASE3B-PROACTIVE-SCREEN-DESIGN.md) + [`PHASE3B-STABILITY-CLOSEOUT.md`](../plugin-phase-03-worker/PHASE3B-STABILITY-CLOSEOUT.md)：自动识屏与手动「看看屏幕」的边界、控制协议与业务请求、截图/dHash/视觉请求的执行位置、上限与取消与回退、文件边界。 |
| 本仓库状态 | ✅ **试点完成**（这是本线唯一拆进子进程的真实功能）。`pet-worker/v1` 帧协议 + QProcess 监督器 + 启动租约 + 诊断白名单 + 宿主侧适配器齐备；执行位置在设置页**显式二选一**（`独立子进程（推荐）` / `进程内（旧路径）`）。 |
| 证据落点 | `pet/workers/protocol.py:20 PROTOCOL = "pet-worker/v1"`、`pet/workers/supervisor.py`（719 行）、`pet/workers/launch.py`、`pet/workers/proactive_screen_worker.py`（755 行）、`pet/workers/proactive_screen_adapter.py`（442 行）、`pet/workers/worker_entry.py`、`pet/workers/worker_diagnostics.py`；宿主侧 `pet/proactive.py:431/:537`（两处执行位置分支）、`pet/settings_proactive_worker.py:44`（下拉项）。测试：`tests/test_workers_protocol.py`、`tests/test_workers_lifecycle.py`、`tests/test_workers_entry.py`、`tests/test_workers_source.py`、`tests/test_proactive_worker.py`、`tests/test_proactive_worker_adapter.py`。 |
| 与作者的差异 | 本仓库多了一条作者原文没有、S3 才定的**硬纪律**：`worker` 模式下 `_worker_capture` **永不**被调用（故障时也不回退进程内管线），故障只写 `_worker_fault` 并停派发、**不改** `_execution_mode`，清故障只有「supervisor 重启阶梯把 worker 拉回 ready」或「用户显式改执行位置」两条路。三条规则机器可判，详见 [`../PR-REPORT-DLC-MOD-CENTER-2026-10-13.md`](../PR-REPORT-DLC-MOD-CENTER-2026-10-13.md) §三-5。 |
| 没做的原因 / 后续归属 | 作者的**人工验收门未关闭**（自动识屏、托盘退出未等用户手测；本仓库同样**未做人工验收**）。这不是故障判定。后续片：无新增代码；人工验收随下一次实机批次。 |

### Phase 3C：剩余执行风险与选装交付评估

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PHASE3C-ISOLATION-ASSESSMENT.md`](../plugin-phase-03-worker/PHASE3C-ISOLATION-ASSESSMENT.md)：逐项评估 AI 对话/文件理解、屏幕理解、音乐、语音报时、余额账户、Harness/bridge 各自该不该变 worker，并给候选决策总表与移交表。 |
| 本仓库状态 | ❌ **未做**（这一篇是纯评估，没有代码产物）。 |
| 证据落点 | —（无本仓库落点）。 |
| 没做的原因 / 后续归属 | 3C 评估的是**上游那套拓扑**下剩余能力的执行风险；本仓库拓扑不同（overlay 单合成窗、固定身份槽位 0..128、进程内碰撞世界、D12 单一指令通道），照抄结论无意义。后续片：真要拆 AI 网络执行时按本仓库拓扑重做一份（**未排期**）。 |

### Phase 4A：屏幕理解最小拆包设计（五组接口 + 自包含 Worker）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PHASE4A-SCREEN-DELIVERY-AUDIT.md`](../plugin-phase-04-updates/PHASE4A-SCREEN-DELIVERY-AUDIT.md) + [`PHASE4A-SCREEN-PACKAGE-DESIGN.md`](../plugin-phase-04-updates/PHASE4A-SCREEN-PACKAGE-DESIGN.md)：五组接口（`DesktopQueryPort`、独立视觉配置 + `CredentialVaultPort`、菜单/设置/搜索/快捷键贡献、可选识屏—聊天联动、自包含 Worker + 独立构建 + 可信加载）。 |
| 本仓库状态 | ⚠️ **半做——只落了"信任与契约"半，宿主侧接口半未落（以 HEAD `7575572` 判定）**。<br>✅ 已落：包验签与路径边界（`pet/plugins/package_trust.py`）、有界 `stage()` 与目录↔ZIP 归一（`pet/feature_package_files.py`）、探针契约（`pet/feature_package_probe.py`）、官方功能 id 与白名单（`pet/official_features.py:55 OFFICIAL_FEATURES`，含 `official.screen-understanding` / `official.ai-chat`）。<br>❌ 未落（HEAD）：`pet/desktop_query.py`、独立视觉配置与凭据端口、`pet/plugins/runtime.py`、`pet/plugins/services.py`、`pet/screen_understanding/` 整个包、owner 绑定的菜单/设置贡献注册面。<br>🔄 **正在落地（工作树未提交，非本文改动）**：`pet/api_ports.py`、`pet/feature_ports.py`、`pet/plugins/{ports,capabilities,contributions,feature_host,feature_packages,package_binding,worker_launch}.py` —— 这半**已不再是"没人做"**，但尚未提交、本文不据此改判；等它落盘后本格要回写。 |
| 证据落点 | 正向：上面四个模块 + `tests/test_plugins_package_trust.py`（含 `VerificationLimits` / `FileStamp` 指纹 / 祖先快照）。反向（拒绝路径）：`pet/feature_package_transactions.py:772`、`pet/mod_center_controller.py:198/214`、`pet/settings_mod_domain.py:147`（`extensions()` 当前仍 `return {}`）、`pet/mod_center_controller.py:366`（拒绝语装配点）。判定主机侧"在不在"用 `git ls-tree -r --name-only HEAD`。 |
| 没做的原因 / 后续归属 | 两条独立的阻塞：(a) 设计里的 host 侧接口是按上游的 `feature_host` + 跨进程 IPC 拓扑写的，本仓库的宿主面只有「设置页所属桌宠窗口」（`DialogModHost`），要按新拓扑重写；(b) **LPAC 原生探针沙箱未移植**——没有它，功能包连自检都过不去，接了宿主也是 fail-closed。后续片：**MSVC 构建片**（钉版 PyInstaller tarball + MSVC + libsodium + AppContainer canary）→ 然后才是宿主接入片。两片**均未排期**；触发条件是"要做功能扩展包的真安装"。 |

### Phase 4B：本地安装与管理闭环（4B-1 → 4B-1.5 → 4B-2 → 4B-3 → 4B-4 → 4B-5）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PHASE4B-LOCAL-MANAGEMENT-DESIGN.md`](../plugin-phase-04-updates/PHASE4B-LOCAL-MANAGEMENT-DESIGN.md) + [`PHASE4B-1.5-RESOURCE-HARD-GATE-DESIGN.md`](../plugin-phase-04-updates/PHASE4B-1.5-RESOURCE-HARD-GATE-DESIGN.md) + [`PHASE4B-2-CROSS-PROCESS-VERSION-LEASE-DESIGN.md`](../plugin-phase-04-updates/PHASE4B-2-CROSS-PROCESS-VERSION-LEASE-DESIGN.md) + [`PHASE4B-3-LOCAL-TRANSACTIONS-DESIGN.md`](../plugin-phase-04-updates/PHASE4B-3-LOCAL-TRANSACTIONS-DESIGN.md) + [`PLUGIN-UPDATE-PROTOCOL.md`](../plugin-phase-04-updates/PLUGIN-UPDATE-PROTOCOL.md)：唯一安装状态 → 资源硬门 → 跨进程版本租约 → staging/激活/previous/延迟 GC/Windows 文件占用与中断恢复 → 管理 UI → 真实构建端到端。 |
| 本仓库状态 | ⚠️ **半做：4B-1/4B-2/4B-3 的代码都在，4B-1.5 换了形，4B-4 只服务角色资源，4B-5 未做**。逐项：<br>• **4B-1 状态账本** ✅ — `pet/feature_install_state.py`（493 行，revision 乐观并发 + 崩溃恢复）、`pet/feature_state_io.py`（219 行，安全路径 / 原子写 / `KernelLock:133`）<br>• **4B-1.5 资源硬门** ⚠️ — 本仓库无 `content/` 版本化布局，等价物是 MOD 中心的 `mod-versions/<id>/<version>/` 回滚 + `prepare_removal` 占用释放（`pet/mod_management.py`）；作者的 Starter/Core 更新保护在本仓库无对应物<br>• **4B-2 跨进程版本租约** ✅（**未接宿主**）— `pet/feature_version_lease.py`（652 行）<br>• **4B-3 事务** ✅（**未接宿主**）— `pet/feature_package_transactions.py`（1199 行）、`pet/feature_lifecycle_contract.py`、`pet/feature_package_startup.py`、`pet/feature_startup_contract.py`<br>• **4B-4 管理 UI** ⚠️ — `pet/mod_center_controller.py`（660 行）+ `pet/mod_center_ui.py`（388 行）+ `pet/settings_mod_domain.py`（234 行）+ 设置页「扩展管理」域（`pet/modern_settings_dialog.py:1940-1963`）；**只服务角色资源**，「功能扩展」那一格因 `extensions()` 恒空而不出现<br>• **4B-5 真实构建端到端** ❌ — 未做 |
| 证据落点 | 本线聚焦测试族 **503 passed / 3 skipped**（18 个文件，`QT_QPA_PLATFORM=offscreen`，`-p no:randomly`，本机实测 165.34 s，2026-10-13）：`tests/test_feature_state_io.py`、`test_feature_install_state.py`、`test_feature_version_lease.py`、`test_feature_package_transactions.py`、`test_feature_package_startup.py`、`test_plugins_package_trust.py`、`test_mod_catalog.py`、`test_mod_management.py`、`test_mod_center_controller.py`、`test_mod_center_ui.py`、`test_settings_mod_domain.py`、`test_workers_protocol.py`、`test_workers_lifecycle.py`、`test_workers_source.py`、`test_workers_entry.py`、`test_frozen_runtime_paths.py`、`test_proactive_worker.py`、`test_proactive_worker_adapter.py`。同线的全量基线见 S4 日志：**7491 passed / 18 skipped**（`.scratch/dlc-fusion/_s4_full_suite.log`）。 |
| 没做的原因 / 后续归属 | **4B-5 与宿主接入同因**：没有 LPAC 沙箱就没有可安装的功能包，没有功能包就没有值得端到端验的构建。**4B-4 的"功能扩展"格**按 `pet/settings_mod_domain.py:147` 的注释，接回时把管理器填进 `extensions()` 即可，控制器侧不用改。后续片：MSVC 构建片 → 宿主接入片（**均未排期**）。 |

### Phase 5A：小 Core Setup 内嵌选装与 ZIP/便携

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PHASE5A-LOCAL-DISTRIBUTION-DESIGN.md`](../plugin-phase-05-distribution/PHASE5A-LOCAL-DISTRIBUTION-DESIGN.md) + [`README.md`](../plugin-phase-05-distribution/README.md) §1：小 Core Setup 提供官方组件选择（两个官方 ZIP 编译期嵌入、勾选后无界面 preflight/apply、首次启动确认 startup receipt）、ZIP/目录显式导入、显式便携模式、Setup/ZIP/应用内共用同一套 Phase 4 事务与权威安装状态。 |
| 本仓库状态 | ❌ **未移植——打包/分发链一个文件都没移植**。`packaging/`（`dsh-pet.iss`、`pet_entry.py`、`pet_entry_no_chat.py`）与 `scripts/build_{onedir.ps1,linux.sh,macos.sh,pyside6_fcitx_plugin.sh}` 是**本站既有**构建，不含 Setup 选装、旁置包、便携标记；作者的五个构建脚本（`build_mod_example.py` / `build_character_mod_example.py` / `build_screen_worker.py` / `build_feature_probe.py` / `build_feature_release.py`）在本仓库**全部不存在**。 |
| 证据落点 | 反向证据：`ls scripts/build_*` → 只有四个既有脚本；`ls packaging/` → 只有三个既有文件。 |
| 没做的原因 / 后续归属 | 依赖 Phase 4A/4B 的宿主闭环：Setup 选装要装的东西在本仓库还装不上（见 §一-1），先做安装器只会做出一个必然失败的入口。后续片：**打包 / 构建片**（在 MSVC 与宿主接入之后，未排期）。 |

### Phase 5B：官方功能推广（AI 对话与文件理解优先）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`README.md`](../plugin-phase-05-distribution/README.md) §2 + [`PLUGIN-FEATURE-DELIVERY-MATRIX.md`](../plugin-roadmap/PLUGIN-FEATURE-DELIVERY-MATRIX.md)：屏幕理解样板稳定后，**AI 对话与文件理解是下一项主要拆包目标**，随后 Agent 及其余领域；11 个逻辑领域不等于 11 个 ZIP。 |
| 本仓库状态 | ❌ **未做**。AI 对话在本仓库是**核心域**（`pet/chat/`：providers / session store / widgets / markdown_view / web_search / prompt …），未做端口化，也没有专属包边界。 |
| 证据落点 | 反向证据（按 HEAD `7575572`）：`pet/mod_api/`、`pet/feature_management.py`、`pet/local_package_intents.py`、`pet/feature_ports.py` 均不存在；`pet/chat/` 无包声明。**注**：工作树里那片并发落地的未提交改动已经新建了 `pet/mod_api/`（`v1.py` / `worker_v1.py`）与 `pet/feature_ports.py`，但它尚未接到 `pet/chat/` 上，`pet/chat/` 仍无包声明。 |
| 没做的原因 / 后续归属 | 依赖 Phase 4A/4B 的宿主与信任链闭环（同一根因链）。PLAN.md 也记了「`features/ai_chat` 整包**放弃**——主线 AI 已是核心域；只借用端口化手法」。后续片：**AI 端口化片**（未排期）。 |

### Phase 6：第三方 SDK 与社区生态（作者标注"条件阶段"）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`README.md`](../plugin-phase-06-ecosystem/README.md)：content DLC 格式文档 / 校验工具 / 示例 → 受控官方 Worker 包格式 → 第三方外部 Worker 预览 → 条件性社区目录。明确禁止任意第三方 `in_process` Python host、任意 `entrypoint`（本篇与 [`PLUGIN-DLC-OPENING-ORDER-AND-THIRD-PARTY-INTERFACES.md`](../plugin-roadmap/PLUGIN-DLC-OPENING-ORDER-AND-THIRD-PARTY-INTERFACES.md) 是同一条线）。 |
| 本仓库状态 | ❌ **未做**（作者自己也标"条件启用"，不阻塞官方交付）。<br>**本仓库唯一的数据型第三方入口是灵动岛段**：声明清单准入 + 采样护栏 + token/epoch 迟到丢弃，已在岛侧三轮验收。 |
| 证据落点 | `pet/island_segments.py:497 SegmentDeclaration` / `:619 register_segment` / `:722 oversize_segment_ids`、`pet/island_extension_host.py`；契约文档 [`../ISLAND-SEGMENTS-EXTENSION.md`](../ISLAND-SEGMENTS-EXTENSION.md)。 |
| 没做的原因 / 后续归属 | 条件阶段，且与 MOD 中心的取舍已拍板：岛段保留为**唯一数据型第三方入口**，MOD 中心做通用容器外壳——岛组件在 MOD 中心只做「一套列表」展示，**清单与采样宿主不合并**（强行统一清单的风险大于收益，见 `.scratch/dlc-fusion/PLAN.md`）。后续片：**不排**。 |

### Phase 7：最小 Core 与官方选装的正式发布验收

| 项 | 内容 |
|---|---|
| 目标（作者） | [`README.md`](../plugin-phase-07-release/README.md)：发布范围与状态必须真实、三平台与生命周期门、产物与性能门、可信发布与维护门，以及 §5/§6 的发布硬门（含 Phase 4B-1.5 的资源证据）。 |
| 本仓库状态 | ❌ **未做**（依赖 Phase 4/5/6，且「最小 Core + 官方选装」这个发布形态在本仓库不存在）。本仓库有**自己的**发布线：onedir + Inno Setup + 在线更新，见 [`../ONEDIR_PACKAGING.md`](../ONEDIR_PACKAGING.md)、[`../STABLE_BUILDS.md`](../STABLE_BUILDS.md)、[`../ONLINE-UPDATE.md`](../ONLINE-UPDATE.md)。 |
| 证据落点 | —（无本仓库落点）。 |
| 没做的原因 / 后续归属 | 上游 Phase 7 是"把已拆包的官方功能按三平台正式发布"的验收门；本仓库还没拆包，没有可验收对象。后续片：随 Phase 4/5 的实际交付推进，**未排期**。 |

---

## 三、本轮移植了哪些文档、改了什么

| 项 | 数字 |
|---|---|
| 移植文件 | **28 篇**（`docs/plugin-roadmap/` 4 篇 + `docs/plugin-phase-01..07/` 24 篇） |
| 写入总行数 | **5092 行** |
| 与旧快照的关系 | 其中 12 篇本仓库原本停在 **2026-09-24 的旧快照**（同名覆盖；旧内容最后一次提交是 `45619ce`），16 篇是**新增** |
| 统一移植基线头 | 28 篇各一段（H1 之后），口径同 [`README.md`](README.md) |
| 死链降级 | **70 处 / 48 个不同目标** → 改成「文字 + 反引号路径」，不留假链接 |
| 外部工具名擦除 | 源文档本身 0 命中；新增的基线头与本文也都规避（改用「上游 DLC 分支」+ `.scratch/dlc-fusion/PLAN.md` 指路） |

**死链降级的目标分三类**（都是上游分支独有、本仓库不存在的文件）：

1. **上游独有的 PR 报告与 grill 记录**（`docs/PR-REPORT-PLUGIN-PHASE3B-2026-09-26.md`、
   `docs/grill-2026-09-27-插件化中期对齐.md` 等）——本仓库没有这些档案。
2. **上游独有的代码与脚本**（`pet/plugins/{ports,runtime,feature_host}.py`、
   `pet/content/*`、`pet/screen_understanding/*`、`pet/desktop_query.py`、
   `scripts/verify_foreground_window.py`、`tests/test_plugin_runtime.py` 等）。
3. **上游独有的工作档案**（`.scratch/phase4b-local-management/*`、
   `.scratch/phase5a-local-distribution/*`；本仓库 `.gitignore` 忽略 `.scratch/`，
   链本地不成立、链远端又会编出不存在的路径）。

**逐字保留的边界**：正文里「本仓库 / 当前仓库 / 已实现」指的是**上游分支自己的进度**，
没有逐句改写成本仓库事实（那会把作者的验收记录改得面目全非）；这个口径由每篇的基线头
统一声明，本仓库事实一律以本文与 [`README.md`](README.md) 的「移植基线与现状」为准。

---

## 四、未做项汇总（按后续片归属）

| 未做项 | 归属片 | 前置阻塞 | 排期 |
|---|---|---|---|
| LPAC 原生探针沙箱 + 密封 probe bundle | MSVC 构建片 | 钉版 PyInstaller tarball + MSVC + libsodium + AppContainer canary | 未排期 |
| 功能扩展宿主运行时（`pet.mod_api.v1` 等）与宿主接入 | 宿主接入片 | 上一行 | **部分在飞**：同一工作树里已有一片未提交的宿主侧骨架（`pet/mod_api/`、`pet/feature_ports.py`、`pet/plugins/{ports,...}.py`，见上文「快照口径」）；剩下的接入与提交仍未排期 |
| 4A 的 host 侧五组接口（`DesktopQueryPort` / `CredentialVaultPort` / 贡献注册 / 识屏—聊天联动 / 自包含 Worker） | 宿主接入片 | 同上 | 同上（贡献注册与端口骨架在飞，`DesktopQueryPort` / 凭据端口 / `pet/screen_understanding/` 仍缺） |
| 4B-5 真实构建端到端 | 打包 / 构建片 | 宿主接入 + MSVC | 未排期 |
| 5A Setup 选装、旁置包、显式便携、ZIP 官方包 | 打包 / 构建片 | 同上 | 未排期 |
| 5B AI 对话与文件理解端口化 | AI 端口化片 | 宿主接入片 | 未排期 |
| 2 的 Registry / Context / EventBus | 随宿主接入片 | 需要有真实消费者 | 未排期 |
| 3C 风险评估（按本仓库拓扑重做） | 未定 | 真要拆 AI 网络执行时 | 未排期 |
| 3A agent-link worker | **不移植** | 主线 `agent_link.py` 是现行权威 | 不做 |
| 6 第三方 SDK / 社区生态 | **条件阶段** | 官方选装闭环 | 不排 |

---

## 五、本仓库**已经**能用的那条腿（避免误读）

怕上面满屏 ❌ 反让人以为"什么都没有"——本仓库实际已交付并可用的：

- **角色资源 MOD 全链路**：导入（ZIP / 目录）→ 启用 → 使用（换装）→ 更新 → 回滚 →
  停用 → 批量删除，设置页「扩展管理」域是入口。教程见
  [`USER-GUIDE.md`](USER-GUIDE.md)、[`CHARACTER-PACKS.md`](CHARACTER-PACKS.md)。
- **包信任链**：验签 / 清单 / 指纹 / 路径边界 / 祖先快照（`pet/plugins/package_trust.py`）。
- **安装事务 / 状态机 / 版本租约 / 探针契约**：代码完整、测试齐备，**已接宿主**（见 §六）。
- **第三方功能扩展全链路（D2/D3）**：导入（ZIP / 目录）→ 停用态落盘 → 启用（菜单贡献出现）
  → 停用（撤销贡献、旧句柄失效）→ 卸载（保留个人数据）→ 重装；装前有子进程预检
  （`pet/feature_package_preflight.py`）。
- **workers 子进程底座**：`pet-worker/v1` + QProcess 监督 + 启动租约 + 诊断白名单；主动识屏
  已真实跑在这条通道上。
- **冻结版长路径修复**：`pet/frozen_runtime_paths.py`（把执行文件密封 `_internal` 以 `\\?\`
  扩展拼写放进 `sys.path`，**就地替换**而非追加——依据是本机实测，追加无效）。

反面口径同样重要：**官方功能包（`official.*`）现在装不上**——那条链是 Core 自有的，
本仓库还没落地；本地 ZIP/目录也不许占用官方 owner 的名字（路由按闭集登记表判定，声明官方 ID
的本地包在 `unsupported_package_message` 处得到一句点名"保留 ID"的拒绝语）。
**第三方功能包（未知 owner）现在装得上**，能力与边界见 §一-1。

---

## 六、D2 / D3 回写（2026-10-13 之后）

上面 §二 的判定以 HEAD `7575572` 为基准。其后两片落地，下列格子按新事实回写（其余格子不变）：

| 项 | 新事实 | 证据落点 |
|---|---|---|
| Phase 4A「宿主侧接口半未落」 | ✅ 宿主运行时已落地：`pet/mod_api/{__init__,v1}.py`、`pet/plugins/{feature_host,feature_packages,package_binding,lifecycle,ports,capabilities,contributions,worker_launch}.py`、`pet/feature_ports.py`、`pet/api_ports.py`、`pet/mod_runtime.py`、`pet/mod_menu.py`、`pet/settings_mod_panel.py` | `git log --oneline` 的 `feat(plugins): D2` 两笔；`tests/test_mod_center_end_to_end.py` 的命题 1–7 |
| Phase 4B-4「功能扩展那一格因 `extensions()` 恒空而不出现」 | ✅ 已回填：`DialogModHost.extensions()` 由 `pet/feature_management.LocalFeatureRuntime` 提供，第一次导入就把管理器装上（`feature_route` 死锁修复） | `pet/settings_mod_domain.py::extensions/feature_route`、`tests/test_feature_package_import_zip.py` |
| Phase 4B-5「真实构建端到端未做」 | ⚠️ 半做：本地用户自选包（host-only）的 **ZIP/目录 → 导入 → 安装 → 装载 → 启停 → 卸载 → 重装** 端到端已可跑；**冻结 exe 与 host-worker 的真实构建仍未做** | `tests/test_feature_package_import_zip.py`、`tests/test_feature_management.py` |
| Phase 5A「ZIP/目录显式导入」 | ⚠️ 半做：第三方 owner 的 ZIP/目录显式导入已落地（按有界清单自动路由、未知 owner 按第三方 DLC 接受）；**Setup 选装 / 便携 / 官方 ZIP 仍未做** | `pet/local_package_intents.py`、`pet/feature_package_preflight.py` |
| §一-1 的"装不上"口径 | 已改写为"显式用户信任 + 装前子进程预检"，默认 fail-closed 那一半保持不变 | 本文件 §一-1 |

D3 的范围与验收口径（本地 ZIP 功能包导入链）与作者文档逐条对照：

| 作者口径（出处） | 本仓库落法 |
|---|---|
| 只预读受限大小的 `manifest.json`，按 `id`/`factory`/`execution_kind` 自动路由；**未知 owner 也作为第三方 DLC 接受**（`PHASE5A-LOCAL-DISTRIBUTION-DESIGN.md` §1） | `pet/local_package_intents.route_local_package` + `LocalFeatureRuntime.route`（官方 ID 例外：保留） |
| 拒绝路径穿越、链接、大小写冲突、重复 ZIP 条目、未登记文件及解压超限（`PHASE4B-LOCAL-MANAGEMENT-DESIGN.md`） | 既有 `pet/feature_package_files.stage` + `package_trust`（D3 未改，ZIP/目录同一处归一） |
| 「复制后的完整包先验证，才允许 factory 或自检执行」「自检用独立进程」（同上） | `FeaturePackageTransactionService._continue` 的次序未改；D3 把自检补成真子进程（`pet/feature_package_preflight.py`） |
| 「preflight 绝不执行候选；确认后完整复验、沙箱自检」（`PHASE5A` §5A-1） | 探针只在 `apply` 的候选检查处跑（`preflight_*` 不执行包代码） |
| LPAC 原生沙箱与 `probe bundle`（`PHASE4B` §probe） | **不移植**（已拍板）：D3 走务实路线，探针不声称隔离，文档逐字写明 |

---

导航：[MOD 文档入口](README.md) · [移植基线与现状](README.md#移植基线与现状2026-10-13) ·
[作者总路线图](../plugin-roadmap/PLUGIN-DLC-ROADMAP-v5.md) ·
[开放顺序与第三方接口](../plugin-roadmap/PLUGIN-DLC-OPENING-ORDER-AND-THIRD-PARTY-INTERFACES.md) ·
[移植交付证据](../PR-REPORT-DLC-MOD-CENTER-2026-10-13.md) · [全文档索引](../INDEX.md)
