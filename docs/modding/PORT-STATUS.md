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
> 那一片（D2）与随后的 D3/D4 已分别提交，**本文 §一/§二 里凡与之冲突的旧判定，以 §六
> 「D2 / D3 回写」与 §七「D4 回写」为准**（§一-2 的「宿主运行时未移植、工作树未提交」
> 已被 D2 覆盖：`pet/mod_api/` 等在 HEAD 且已接入）；§二 正文按快照基线保留原样，
> 不复写历史判定。引用前先复核一次 `git ls-tree -r --name-only HEAD | grep <路径>`。
> **又：本文全部判定与测试数字都描述 DLC 分支合并进 main 之前的状态**（2026-10-14
> 并入，合并提交 `b2767d0`）；合并后的复验结论以 main 上的交付记录为准，别把本文的
> 数字读成合并态的实测。

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
4. **打包 / 分发链大部分未移植（2026-10-17 复核修正）**。作者的 Setup 选装、旁置本地包、
   显式便携、Ed25519 发布签名、冻结 worker / 原生探针构建链在本仓库**不存在**：
   `scripts/` 里作者 57 个改动中 **34 个**没有对应物（`build_core_webm_setup.py`、
   `validate_phase5a_{setup,delivery}.py`、`feature_release_{cli,materials,signing}.py`、
   `release_distribution.py`、`build_screen_worker.py`、`build_feature_probe{,_native}.py`、
   `build_feature_release.py`、`check.py` / `check_docs.py` 等），`packaging/` 12 个里缺 9 个
   （`core_webm.iss`、两个 `*.iss.inc` 门、5 个验收 fixture 入口）。
   **不是"少几个脚本"**：这些脚本依赖的 `pet/core_maintenance.py`、`pet/core_code_gate.py`、
   `pet/core_uninstall.py`、`pet/runtime_layout.py`、`pet/content/`、`pet/feature_probe_*.py`、
   `packaging/licenses/LIBSODIUM-LICENSE.txt` 在本仓库**一个都没有**——整条 Setup / 冻结 /
   签名链的内核缺失（账本见 §十一）。
   **已经补上的那一段**：D4 的打包入口 `scripts/build_mod_example.py` **存在**（换形移植，
   行为多于作者版：退出码、装前子进程预检、`host/` 出现非 `.py` 直接中止）、发布/构建门
   `scripts/verify_feature_package.py`、三端构建脚本的两道门与 `<app>/features/`；另外
   `build_{screen,ai_chat}_package.py` 是本仓库新增的源码态包打包入口。现状见 §七。
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
| 没做的原因 / 后续归属 | 作者 §8 那组 P0 硬门里，**只有"版本指针与 Starter"可以判为不适用**（本仓库没有 `content/versions/<v>+active.json` 那套布局，启用态用目录位置表达）。**其余能力不是不适用，是真缺**（2026-10-17 逐文件复核）：<br>• 任意版本激活——作者 `pet/content/manager.py:417 activate(plugin_id, version)` 可切到任一已装版本；本仓库 `pet/mod_management.py:531 rollback` 只能回"保留版里 semver 最大那个"<br>• 逻辑 SHA-256（同一内容目录与 ZIP 同 digest、跳过 `manifest.json`）——`pet/content/hashing.py:39/49/80/95`；本仓库 `pet/mod_management.py` / `mod_catalog.py` / `mod_center_controller.py` 里 `sha256` **零命中**<br>• 事务日志 + 崩溃恢复（三阶段 prepared→version_removed→pointers_committed）——`pet/content/manager.py:119/490-546`；本仓库 `transaction|journal|recover` 零命中<br>• 激活后自检 + 失败自动回退——`pet/content/manager.py:431 _self_check_active`；本仓库 `_publish` 只在换入前校验，换入后不复验<br>• manifest 严格契约（`kind`/`api_version`/`core_requires`/`platforms`/禁 entrypoint/派生 cache 必须在包外）——本仓库 `_manifest_of` 只读 id/name/version/description，版本不合法时**回落 `0.0.0` 而不是拒绝**<br>• bundled 资源包 / Starter、结构化坏包诊断、`python -m pet.content` 运维 CLI——均无对应物<br>**能对上的是**：安装与 staging、停用、删除、手动回滚、路径/可执行/符号链接/ZIP 越界拒绝。「资源回滚」有对应物（`mod-versions/` + `ResourceMods.rollback`）。后续片：这 6 条缺口归**内容硬门片**（未排期，但它是官方功能选装的前置，见 §十一）。**2026-10-17 补齐（阶段 1，见 [`PR-REPORT-RESOURCE-HARD-GATE-2026-10-17.md`](../PR-REPORT-RESOURCE-HARD-GATE-2026-10-17.md)）**：逻辑 SHA-256（目录/ZIP 同 digest、跳过 `manifest.json`）、严格 manifest 契约、事务日志 + 四阶段崩溃恢复、激活后自检 + 失败回退、任意版本激活五项已落地，位置是 `pet/mod_hashing.py` / `pet/mod_manifest.py` / `pet/mod_transactions.py` + `pet/mod_management.py`；启用态仍是目录位置，**不引入** `active.json` / `previous.json` / `versions/<v>`。Starter/bundled 与 `python -m pet.content` CLI 仍判不适用（本仓库无 `content/` 树）。 |

### Phase 2：Core 插件运行时（Registry / Context / EventBus / capability）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PLUGIN-RUNTIME-DESIGN.md`](../plugin-phase-02-runtime/PLUGIN-RUNTIME-DESIGN.md) + [`README.md`](../plugin-phase-02-runtime/README.md) + [`PLUGIN-RUNTIME-TEST-PLAN.md`](../plugin-phase-02-runtime/PLUGIN-RUNTIME-TEST-PLAN.md)：`PluginRegistry` / `PluginContext` / `CoreEventBus` / 配置命名空间隔离 / capability / 生命周期与错误隔离；官方节日提醒作为接口验证消费者；后续补菜单·设置·快捷键贡献的按包所有者注册与撤销。 |
| 本仓库状态 | ⚠️ **半做（2026-10-17 复核修正：原判定是往悲观方向的过期结论）**。<br>✅ 底座已移植，其中 5 个文件与作者**逐字节相同**：`pet/plugins/events.py`（`CoreEventBus`/`ScopedEventBus`/`CoreEvent`/`Subscription`，154 行）、`capabilities.py`、`contributions.py`（`ContributionRegistry`/`ContributionHandle`）、`ports.py`（`CommandRegistry`/`PresentationPort`/`SchedulerPort`/`StructuredLogger`/`ContentProviderRegistry`）、`package_binding.py`；`feature_host.py` = 作者的 +93 行（把 EventBus 接进启停与故障路径）。宿主状态机 / 依赖顺序 / owner 隔离 / `fault()` / 贡献撤销由 `pet/plugins/feature_host.py:41 FeatureHost` + `lifecycle.py:FeatureHostLifecycle` 承载，实装于 `pet/feature_management.py`。<br>❌ 未移植的**四个具名件**：`PluginRegistry`、`PluginContext`（`pet/plugins/runtime.py`，530 行）、`PluginManifest`/`version_satisfies`/`PluginDiagnostic`（`pet/plugins/manifest.py`，129 行）、`PluginConfigStore` + `FESTIVAL_LEGACY_CONFIG_MAP`（`pet/plugins/config.py`，247 行）。**并且**作者 Phase 2 的唯一消费者——节日提醒插件化包装（`pet/plugins/builtin/festival_reminder/`）也未移植。 |
| 证据落点 | `pet/plugins/` 现有 **12 个模块**（`__init__`、`capabilities`、`contributions`、`events`、`feature_host`、`feature_packages`、`lifecycle`、`package_binding`、`package_trust`、`ports`、`services`、`worker_launch`）。反向证据：`grep -rn "PluginRegistry\|PluginContext" pet/` → **0 命中**；`git cat-file -e <HEAD>:pet/plugins/{runtime,config,manifest}.py` → 全部 MISSING；`pet/plugins/builtin/` 目录不存在。节日提醒在本仓库仍是既有功能——**铁证**是作者为插件化给 `FestivalReminderService.__init__` 加了 `scheduler/presentation/audio/config_source` 四个端口参数（作者 `pet/festival_service.py:38-46`），本仓库签名仍是 `def __init__(self, app)`（`pet/festival_service.py:36`），装配点是 `pet/app.py:1841-1843` 直接构造，开关走 `pet/config.py:1271-1281` 的 11 个扁平键。 |
| 没做的原因 / 后续归属 | 缺的是"manifest → capability → 注入"那套**自动装配**：本仓库的 `FeatureHostContext` 由 `feature_host_bindings.py` 手工注入，能力集由 `pet/feature_policy.py` 与 `package_trust` 的签名包契约给（形状是 `features/` 签名包，不是作者的 `kind=in_process` 插件）。**这不是能力倒退**——签名/TOCTOU/逐文件 sha256 比作者那套更严——但终态要求"连节日提醒都是包"，而节日提醒现在硬绑在 `AppShell` 上、`festival_service.__init__(self, app)` 这个签名就是不拆包的天花板。后续片：**Phase 2 内核收口片**（未排期；它与 §十一 的"内容硬门片"并列，都是"一切都是包"的前置）。**2026-10-17 已落地（阶段 2，见 [`PR-REPORT-PHASE2-PLUGIN-KERNEL-2026-10-17.md`](../PR-REPORT-PHASE2-PLUGIN-KERNEL-2026-10-17.md)）**：`PluginRegistry` / `PluginContext` / `PluginManifest` / `PluginConfigStore` 四个具名件与节日提醒 in-process 插件（`official.festival-reminder`）已实现；默认仍走内置服务，`PET_FESTIVAL_PLUGIN=1` 才由 Registry 装配（共存 + 可回退），默认切换待维护者拍板。 |

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
| 本仓库状态 | ⚠️→✅ **识屏包线已落地（DLC 第三片，`bd3d10d` 之前一串 `feat(screen-pkg)`/`feat(plugins)` 提交）**。<br>✅ 已落：包验签与路径边界（`pet/plugins/package_trust.py`）、有界 `stage()` 与目录↔ZIP 归一（`pet/feature_package_files.py`）、探针契约（`pet/feature_package_probe.py`）、官方功能 id 与白名单（`pet/official_features.py`）；宿主骨架（`pet/plugins/*`、`pet/mod_api/`）；`pet/desktop_query.py` 与 `pet/credentials.py` 端口本体；**识屏整包 `features/screen-understanding/`（host 18 + common 4 + `mod.json` + `worker-src/entry.py` = 24 个文件，上游 `features/screen_understanding` 移植）、两端口的宿主注入（`bind_screen_context`：凭据/偏好/窗口/桌面）、独立视觉配置（包内 `host/config.py` + owner 作用域 vault + journal 侧车）、官方验签策略 `official_package_verifier` 与 Core 自有装配 `LocalFeatureRuntime.attach_official`、识屏—聊天联动（`sync_text`→`on_look_synced`→`AppShell.sync_look_to_chat`，聊天不变包）、源码态打包 `scripts/build_screen_package.py`**。<br>**逐文件对照（2026-10-17，作者 26 个文件）**：14 个与作者逐字节相同（`common/*` 4 个、`host/{config,contribution_settings,presentation,runtime_context,settings,settings_context,strategy_settings,worker_adapter,worker_diagnostics}.py`）；6 个同名小改（`contributions.py` 菜单工厂改两参 + 文案加"（识屏包）"、`factory.py` 改交 `ScreenPackageRuntime` 并新增 `bind_lifecycle`、`limiter.py`/`memory.py` 的 `except` 加 `StateError`、`manual.py`/`runtime.py` 的 `from ..worker import vision` → `from pet import vision`，`runtime.py` 1204 行其余逐字节相同）；3 个换形（`worker/__main__.py` → `worker-src/entry.py` 带租约认领与 fail-closed 77、`worker/runtime.py` → `pet/workers/proactive_screen_worker.py`、`worker/vision.py` → `pet/vision.py`）；3 个未移植（两个一行 docstring 的 `__init__.py` + 下一格的 `migration.py`）。作者那层 `pet/screen_understanding/` 兼容接缝（11 个 legacy 薄壳）整层去掉，语义改由「Core 端口注入 + `bind_screen_context`」承载——其中 `presentation.py` / `window_actions.py` 两个壳在作者分支本身就是零消费者。<br>❌ 未落：`host/migration.py`（`VisionMigration` / `MigrationPreview` / `source_revision` / `repair_missing_credentials` 在 DLC 全库 grep **零命中**；连带配置端口没有 `migration_source`，`features/.../host/config.py:155` 那行 `source_guard(self.config.migration_source())` 是**不可达残留**——全仓无调用方传 `source_guard`）、`manual_for` 这类"从 Core 窗口代码直接拉起手动识屏"的入口（等价能力改由包命令 `handle.invoke("look")`）、冻结 worker 打包与 Setup 投递（属打包/构建片）、MOD 中心 UI 的「安装官方包」入口（当前由 Core 入口 `attach_official` + 管理器驱动，UI 按钮属后续片）。**另有一处本仓库独有的重复**：`pet/workers/proactive_screen_adapter.py`（472 行，Core 内置识屏路径）与包内 `host/worker_adapter.py`（378 行）两份适配器并存，作者分支只有后者的别名。 |
| 证据落点 | 正向：上面四个模块 + `tests/test_plugins_package_trust.py`（含 `VerificationLimits` / `FileStamp` 指纹 / 祖先快照）。反向（拒绝路径）：`pet/feature_package_transactions.py:772`、`pet/mod_center_controller.py:198/214`、`pet/settings_mod_domain.py:147`（`extensions()` 当前仍 `return {}`）、`pet/mod_center_controller.py:366`（拒绝语装配点）。判定主机侧"在不在"用 `git ls-tree -r --name-only HEAD`。 |
| 没做的原因 / 后续归属 | 两条独立的阻塞：(a) 设计里的 host 侧接口是按上游的 `feature_host` + 跨进程 IPC 拓扑写的，本仓库的宿主面只有「设置页所属桌宠窗口」（`DialogModHost`），要按新拓扑重写；(b) **LPAC 原生探针沙箱未移植**——没有它，功能包连自检都过不去，接了宿主也是 fail-closed。后续片：**MSVC 构建片**（钉版 PyInstaller tarball + MSVC + libsodium + AppContainer canary）→ 然后才是宿主接入片。两片**均未排期**；触发条件是"要做功能扩展包的真安装"。 |

### Phase 4B：本地安装与管理闭环（4B-1 → 4B-1.5 → 4B-2 → 4B-3 → 4B-4 → 4B-5）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PHASE4B-LOCAL-MANAGEMENT-DESIGN.md`](../plugin-phase-04-updates/PHASE4B-LOCAL-MANAGEMENT-DESIGN.md) + [`PHASE4B-1.5-RESOURCE-HARD-GATE-DESIGN.md`](../plugin-phase-04-updates/PHASE4B-1.5-RESOURCE-HARD-GATE-DESIGN.md) + [`PHASE4B-2-CROSS-PROCESS-VERSION-LEASE-DESIGN.md`](../plugin-phase-04-updates/PHASE4B-2-CROSS-PROCESS-VERSION-LEASE-DESIGN.md) + [`PHASE4B-3-LOCAL-TRANSACTIONS-DESIGN.md`](../plugin-phase-04-updates/PHASE4B-3-LOCAL-TRANSACTIONS-DESIGN.md) + [`PLUGIN-UPDATE-PROTOCOL.md`](../plugin-phase-04-updates/PLUGIN-UPDATE-PROTOCOL.md)：唯一安装状态 → 资源硬门 → 跨进程版本租约 → staging/激活/previous/延迟 GC/Windows 文件占用与中断恢复 → 管理 UI → 真实构建端到端。 |
| 本仓库状态 | ⚠️ **半做：4B-1/4B-2/4B-3 的代码都在，4B-1.5 换了形，4B-4 只服务角色资源，4B-5 未做**。逐项：<br>• **4B-1 状态账本** ✅ — `pet/feature_install_state.py`（493 行，revision 乐观并发 + 崩溃恢复）、`pet/feature_state_io.py`（219 行，安全路径 / 原子写 / `KernelLock:133`）<br>• **4B-1.5 资源硬门** ⚠️ — 本仓库无 `content/` 版本化布局，等价物是 MOD 中心的 `mod-versions/<id>/<version>/` 回滚 + `prepare_removal` 占用释放（`pet/mod_management.py`）；作者的 Starter/Core 更新保护在本仓库无对应物<br>• **4B-2 跨进程版本租约** ✅（**未接宿主**）— `pet/feature_version_lease.py`（652 行）<br>• **4B-3 事务** ✅（**未接宿主**）— `pet/feature_package_transactions.py`（1199 行）、`pet/feature_lifecycle_contract.py`、`pet/feature_package_startup.py`、`pet/feature_startup_contract.py`<br>• **4B-4 管理 UI** ⚠️ — `pet/mod_center_controller.py`（660 行）+ `pet/mod_center_ui.py`（388 行）+ `pet/settings_mod_domain.py`（234 行）+ 设置页「扩展管理」域（`pet/modern_settings_dialog.py:1940-1963`）；**只服务角色资源**，「功能扩展」那一格因 `extensions()` 恒空而不出现<br>• **4B-5 真实构建端到端** ⚠️ **半做（2026-10-17 阶段 4）** — 官方识屏包的 Worker 已能冻成单文件 exe（`scripts/build_screen_worker.py`），`build_screen_package.py --worker-exe` 写入 `worker.path`；`verify_feature_package.py --official` + `build_onedir.ps1 -OfficialFeaturePackages` 让 onedir 真实携带 `<app>/features/{ai-chat,screen-understanding}`。冻结 Worker 裸跑 fail-closed 77、冻结入口 `--worker` 未知 id exit 2 已实测。**未做**：完整租约交接链路（需已安装包 + 真宿主）与 Setup。 |
| 证据落点 | 本线聚焦测试族 **503 passed / 3 skipped**（18 个文件，`QT_QPA_PLATFORM=offscreen`，`-p no:randomly`，本机实测 165.34 s，2026-10-13）：`tests/test_feature_state_io.py`、`test_feature_install_state.py`、`test_feature_version_lease.py`、`test_feature_package_transactions.py`、`test_feature_package_startup.py`、`test_plugins_package_trust.py`、`test_mod_catalog.py`、`test_mod_management.py`、`test_mod_center_controller.py`、`test_mod_center_ui.py`、`test_settings_mod_domain.py`、`test_workers_protocol.py`、`test_workers_lifecycle.py`、`test_workers_source.py`、`test_workers_entry.py`、`test_frozen_runtime_paths.py`、`test_proactive_worker.py`、`test_proactive_worker_adapter.py`。同线的全量基线见 S4 日志：**7491 passed / 18 skipped**（`.scratch/dlc-fusion/_s4_full_suite.log`）。 |
| 没做的原因 / 后续归属 | **4B-5 与宿主接入同因**：没有 LPAC 沙箱就没有可安装的功能包，没有功能包就没有值得端到端验的构建。**4B-4 的"功能扩展"格**按 `pet/settings_mod_domain.py:147` 的注释，接回时把管理器填进 `extensions()` 即可，控制器侧不用改。后续片：MSVC 构建片 → 宿主接入片（**均未排期**）。 |

### Phase 5A：小 Core Setup 内嵌选装与 ZIP/便携

| 项 | 内容 |
|---|---|
| 目标（作者） | [`PHASE5A-LOCAL-DISTRIBUTION-DESIGN.md`](../plugin-phase-05-distribution/PHASE5A-LOCAL-DISTRIBUTION-DESIGN.md) + [`README.md`](../plugin-phase-05-distribution/README.md) §1：小 Core Setup 提供官方组件选择（两个官方 ZIP 编译期嵌入、勾选后无界面 preflight/apply、首次启动确认 startup receipt）、ZIP/目录显式导入、显式便携模式、Setup/ZIP/应用内共用同一套 Phase 4 事务与权威安装状态。 |
| 本仓库状态 | ❌ **未移植（2026-10-17 复核修正一处：作者五个构建脚本里 `build_mod_example.py` 是存在的换形移植，不是"全部不存在"）**。`packaging/`（`dsh-pet.iss`、`pet_entry.py`、`pet_entry_no_chat.py`）与 `scripts/build_{onedir.ps1,linux.sh,macos.sh,pyside6_fcitx_plugin.sh}` 是**本站既有**构建，不含 Setup 选装、旁置包、便携标记；作者的 `build_character_mod_example.py` / `build_screen_worker.py` / `build_feature_probe{,_native}.py` / `build_feature_release.py` 在本仓库**不存在**，`build_mod_example.py` **存在**（`scripts/`，换形移植，行为多于作者版）。另外作者那条链里 DLC 完全没有的还有：`core_webm.iss`（两个 `ai`/`screen` 选装 task、编译期嵌入官方 ZIP、`portable.json` 便携标记、`--core-maintenance install-packages`）、两个 `*.iss.inc` 构建门、`validate_phase5a_{setup,delivery}.py`、`feature_release_{cli,materials,signing}.py`（离线 Ed25519，掩码对话框，禁 argv/env 传密码）、`release_distribution.py`（五产物签名清单）。依赖侧决定性的旁证：`pet/core_maintenance.py`、`pet/core_code_gate.py`、`pet/core_uninstall.py`、`pet/core_registration_cleanup.py`、`pet/feature_probe_*.py`、`packaging/licenses/LIBSODIUM-LICENSE.txt` 在本仓库**一个都没有**（`pet/runtime_layout.py` 已由 2026-10-18 便携切片补上，但不含上游的凭据/AppContainer 语义）。**2026-10-17 阶段 4 状态**：构建侧可把官方包随 onedir 携带并双门校验；`packaging/dsh-pet.iss` 已加两个官方包可选 Task（默认不勾）、基础复制 `Excludes`、Task-scoped `Source` 与 `startup-receipt.json` 回执（结构判据 5 条绿）。**2026-10-18 状态（已编译并验收）**：Inno Setup 6.7.3 装好后真实编译 Setup（122.5 s / 587,036,763 bytes）；静默矩阵覆盖不选包/两包都选/升级/卸载——未选不留空 `features\`、回执按盘上 `manifest.json` 写、卸载目录清空、安装态数据写隔离 APPDATA 且不进安装目录；**显式便携**由 `pet/runtime_layout.py` + `portable.json` 落地（zip 根带 canonical 标记，冻结 onedir 实测 `<exe>\data\`，隔离 APPDATA 为空）。**签名按用户决定本轮不做**，无 Authenticode/Ed25519 产物；干净机器、其它变体、向导 UI 人工点击、便携跨机/只读介质仍未验收。详见 [`PR-REPORT-PORTABLE-SETUP-2026-10-18.md`](../PR-REPORT-PORTABLE-SETUP-2026-10-18.md) 与合同 [`PORTABLE-MODE-2026-10-18.md`](../PORTABLE-MODE-2026-10-18.md)。 |
| 证据落点 | 反向证据：`ls scripts/build_*` → 6 个（`build_mod_example.py`、`build_screen_package.py`、`build_ai_chat_package.py` + 三端既有脚本），其中只有第一个是作者脚本的移植；`ls packaging/` → 3 个既有文件。作者侧 `tests/` 里这些链的 43 个用例族在本仓库**零命中**（小 Core Setup/卸载 15、Phase 5A 验收 6、发布签名分发 7、LPAC 探针 6、运行时数据导入 5，其余零散）。 |
| 没做的原因 / 后续归属 | 依赖 Phase 4A/4B 的宿主闭环：Setup 选装要装的东西在本仓库还装不上（见 §一-1），先做安装器只会做出一个必然失败的入口。后续片：**打包 / 构建片**（在 MSVC 与宿主接入之后，未排期）。 |

### Phase 5B：官方功能推广（AI 对话与文件理解优先）

| 项 | 内容 |
|---|---|
| 目标（作者） | [`README.md`](../plugin-phase-05-distribution/README.md) §2 + [`PLUGIN-FEATURE-DELIVERY-MATRIX.md`](../plugin-roadmap/PLUGIN-FEATURE-DELIVERY-MATRIX.md)：屏幕理解样板稳定后，**AI 对话与文件理解是下一项主要拆包目标**，随后 Agent 及其余领域；11 个逻辑领域不等于 11 个 ZIP。 |
| 本仓库状态 | ⚠️ **包线已落地（DLC 第四片），但落地形态与作者文档不同**。作者要的是"AI 与文件理解端口化后拆包，11 个逻辑领域不等于 11 个 ZIP"；本仓库落的是**共存**形态：`features/ai-chat/` 是官方 `host-only` 包（上游 `features/ai_chat` 整包移植，自带 provider / 会话 / 窗口 / 文件解读），与**未动过**的内置域 `pet/chat/` 并存，两套各持一本配置与会话账。逐项见 §九。**2026-10-18 Phase 5B 前四片**：✅ 5B-1 Setup 回执消费（`pet/startup_receipt.py`，首启按盘上 manifest 幂等安装，单包失败不阻塞）；✅ 5B-2 AI 包补「无包无入口 / 重装保留偏好」；✅ 5B-3 文件理解补「卸载当场摘路由 / 停用不建解读器」；✅ 5B-4 十二领域交付矩阵 [`PLUGIN-DOMAIN-DELIVERY-MATRIX-2026-10-18.md`](../PLUGIN-DOMAIN-DELIVERY-MATRIX-2026-10-18.md)。**同时修掉冻结交付阻塞**：PyInstaller 漏收 `pet.mod_api` 导致官方包 probe 全部 `import_failed`，已加 hidden-import + 构建期用产物 exe 跑真实 probe 门。 |
| 证据落点 | `features/ai-chat/`（30 文件）、`pet/feature_host_bindings.py::bind_ai_context`、`pet/ai_bindings.py`、`scripts/build_ai_chat_package.py`；用例 `tests/test_ai_package_e2e.py`（装卸链 + 无包/重装偏好）、`tests/test_ai_package_host.py`（包侧核 + 卸载摘路由/停用不建解读器）、`tests/test_ai_host_binding.py`、`tests/test_ai_bindings.py`、`tests/test_startup_receipt.py`、`tests/test_bundle_official_probe.py`、`scripts/verify_frozen_mod_api.py`。反向证据：`pet/chat/` 无包声明（内置聊天仍是核心域），包目录里不出现 `from pet.chat` 的引用。 |
| 没做的原因 / 后续归属 | 上游把 AI **整包化**（Core 里不再有内置聊天），本仓库选择**并存**——内置聊天是现行权威且带着后续产品修复，整包化会把那些修复又一次分叉。代价写进 §九的"未做"表：包的 UI 落后于内置 UI（后续片）。 |

### Phase 5C：Core / DLC 架构重构（2026-10-18）

| 项 | 内容 |
|---|---|
| 目标 | 按交付矩阵让可拆领域成为官方包，Core 只保留宿主能力；core-bound 领域给出保持证据 |
| 本仓库状态 | ✅ **7 个官方包**：AI 对话、文件理解（随 AI）、屏幕理解、账户用量、音乐启动器、语音报时、日常台词、快捷启动（其中文件理解随 AI 包）。新增 `presentation` / `scheduler` / `audio` 三个包端口与显式凭据操作集、`process.spawn` 声明式能力；每个包都有结构 / 构建 / 绑定 / 安装闭环测试。**保持 Core**：Agent（外部桥接契约 + 无 OS 钩子端口）、灵动岛（多屏拓扑 + 无主槽贡献端口）、趣味互动（无窗口/素材端口）、Harness（托盘与进程清理生命周期）；生活提醒保持 Phase-2 进程内插件（默认切换属产品决策）。 |
| 证据落点 | `features/{account-usage,music,voice-chime,persona-phrases,quick-launch}/`、`pet/feature_ports.py`（新端口）、`pet/feature_host_bindings.py`（`bind_account/music/voice/persona/quick_launch_context`）、`scripts/build_host_package.py` 与各包构建器、`tests/test_*_package*.py`、矩阵 [`PLUGIN-DOMAIN-DELIVERY-MATRIX-2026-10-18.md`](../PLUGIN-DOMAIN-DELIVERY-MATRIX-2026-10-18.md)、审计 [`DLC-ARCHITECTURE-AUDIT-2026-10-18.md`](../DLC-ARCHITECTURE-AUDIT-2026-10-18.md)。 |
| 没做的原因 / 后续归属 | 包菜单仍只落在「扩展」子菜单；歌词富气泡、灵动岛主槽贡献、趣味互动窗口端口均需新能力模型，见审计 §3。 |

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
| 4A 的 host 侧五组接口（`DesktopQueryPort` / `CredentialVaultPort` / 贡献注册 / 识屏—聊天联动 / 自包含 Worker） | 宿主接入片 | 同上 | ✅ 识屏包线已落（见 §二 Phase 4A 格）：五组接口都有真实消费者（官方识屏包）；Worker 为「包薄入口 + Core 运行时」形态，冻结自包含 exe 属打包/构建片 |
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

## 七、D4 回写：分发 / 打包链（packaging / scripts 侧）最小可用子集

作者 Phase 5A 的分发链文件（`core_webm.iss`、`build_core_webm_setup.py`、`validate_phase5a_*`、
`feature_release_*`、`release_distribution.py` 等）在本仓库**一个都没有**，D4 补的是其中
**与本站拓扑对得上**的那一段。
> **2026-10-17 修正**：原文把 `build_variant.py` 也列进了"一个都没有"——它不是源文件，作者
> `.gitignore` 与本仓库三端构建脚本都把它当**生成物**写出来（`VARIANT = '<variant>'`，无 BOM
> UTF-8），变体注入这段行为两边等价，所以它不是缺失项。

范围划分与文档口径的对照：

| 作者口径（出处） | D4 落法（本仓库） |
|---|---|
| 官方包链：官方 ZIP 编译期嵌入 Setup、勾选后无界面 preflight/apply 与 startup receipt（`PHASE5A` §1） | **不做**（官方包安装链本身未落地，见 §二 Phase 4A/5A 两格）；D4 不含 Inno Setup 选装器 |
| 显式便携模式与 `portable.json`（`PHASE5A` §4） | **不做**（本仓库拓扑是 `%APPDATA%\<变体>`；便携属未排期的打包片） |
| 旁置包根（`PHASE5A` 的 Setup 旁 `packages` 根；卸载/重装边界） | ⚠️ **半做**：构建脚本可**明确要求**随包携带一个包根，落到产物 `<app>/features/`（macOS 在 `.app/Contents/Resources/features/`）并两道门校验；**产品运行期还没有读这个目录的地方**，安装器侧那条链也没做——不带 `-FeaturePackages` 的构建是正常构建 |
| 本地分发签名与体积门（`PHASE5A` §5 的五产物总签名） | **不做**（正式签名基线与官方产物都不在本仓库） |
| 4B-5「真实构建端到端」 | ⚠️ 前进一步：作者侧**打包入口 + 发布前自检 + 三端构建门**已落地；**冻结 exe 与 host-worker 的真实构建仍未做** |
| 作者要「一条命令产出可导入包」（`AUTHORING-HANDBOOK` §4） | ✅ `scripts/build_mod_example.py` 从测试材料级升级为**正式入口**：源码树不合格/`host/` 里有打不进包的文件/输出已存在都在写任何字节之前报错，`--check` 升级为「清单完整性 + 摘要校验 + 装前子进程预检」 |
| 社区作者需要打包自检工具（作者 Phase 6 的「校验工具」） | ✅ `scripts/verify_feature_package.py`：单份/包根/`--json`/`--target-platform`，退出码与原因码是闭集，只读、零 Qt |

**D4 新增/改动的文件**：新增 `scripts/verify_feature_package.py`（发布/构建门）、
`pet/feature_policy.py`（能力上限 / API 版本 / 验签器装配的**唯一真相源**，零 Qt，
宿主与 scripts 两侧共用）、`tests/test_feature_package_gate.py`、
`tests/test_feature_packaging_wiring.py`；改 `scripts/build_mod_example.py`（正式入口）、
`scripts/build_{onedir.ps1,linux.sh,macos.sh}`（两道门 + `<app>/features/`）、
`pet/feature_management.py`（改从 `feature_policy` 取策略，删掉那份重复字面量）、
`tests/test_architecture.py`（零 Qt 名单加 `feature_policy.py`）与 §六/§七 涉及的文档。

**明确未做（后续片边界）**：Setup 选装器与官方包链、便携模式迁移、产品侧读
`<app>/features/` 的那条链、host-worker 的真实冻结构建（`build_mod_echo` /
`build_feature_probe_native`）、官方包构件脚本（`build_character_mod_example.py`）、
LPAC 相关一切。**`official.ai-chat` / `official.screen-understanding` 已经拆了**（2026-10-17
修正：原文写"D5 才拆"，实际两个包都在 `features/` 下，源码态打包入口
`build_{ai_chat,screen}_package.py` 齐备；AI 包还比作者多 `mod.json`、
`host/contributions.py`、`host/runtime_mount.py` 三个文件，见 §九 与 §十）。

---

## 八、盲审修复回写（2026-10-14）

对 `dlc/mod-center-port` 分支 D2–D4 落地面的**一轮独立盲审**提出的问题与处置。每条都
留了红→绿证据（先写会红的用例，改后转绿）；"缓"的写明缓的理由与归属片。

| 编号 | 问题 | 处置 |
|---|---|---|
| B1 | 冻结入口（`packaging/pet_entry*.py`）不分流 `--worker` / `--feature-package-probe`：冻结包里这两种子进程会 import `pet.app`，把整只桌宠拉起来并撞主进程的单实例门 | ✅ 修：两条分流补在 `import pet.app` 之前，转发给 `pet/__main__.py` 里那一份实现（不抄第二份路由）。守卫 `tests/test_frozen_entry_routing.py`：源码顺序断言 + **真进程**边界探针（入口一旦走进桌面 UI 图就抛），并真跑一次 worker 握手与预检回执 |
| M1 | `is_valid_feature_id` 允许大写与末尾点、放过设备名：`Official.Screen-Understanding` 绕过官方闭集，`foo`/`Foo`/`foo.` 在 NTFS 上共用同一份 `feature-data/` | ✅ 修：ID 规范形收口为 `[a-z0-9][a-z0-9_.-]*` + 禁末尾 `.`/`-` + 禁设备名首段（`nul`、`con.package`），官方闭集按规范形比较。用例：`tests/test_official_features.py`（14 条变体）、`tests/test_feature_package_import_zip.py`（声明官方 ID 变体的 ZIP 在路由层被拒、不落任何目录）。**无迁移负担**：没有任何 tag 包含本分支（`git tag --contains HEAD` 为空），仓库里也不存在大写 ID 的字面量或落盘写法 |
| M2 | 升级/回滚/卸载的第二段失败时，第一段交还的宿主绑定没了：菜单与会话消失到重启 | ✅ 修：记 `_released_for_apply`，第二段非 settled 时把**当前落盘**的版本重新装回宿主；用户看到的只是这次操作失败。用例：`tests/test_feature_management.py::test_a_failed_apply_puts_the_old_version_back_in_the_host`（改前 `host.state == "absent"`，改后回 `enabled` 且菜单在） |
| M3 | 发布门自称"验签"，而 `local_user` 口径下 `manifest.sig` 被静默忽略 | ✅ 修：门 / 三端构建脚本 / 作者侧打包入口 / 作者文档的口径统一为「清单完整性 + 摘要校验 + 装前子进程预检」；报告新增 `trust_status`（`local_user`、未做发布者认证）与 `warnings`，包里带 `manifest.sig` 时给 `signature_ignored` 告警（放行但说出来）。守卫：`tests/test_feature_packaging_wiring.py::TestTheChainDoesNotClaimPublisherAuthentication`（五个文件的文案一起钉）+ 门的三条行为用例 |
| M4 | 主动识屏 worker 在关闭 / 清空白名单 / tick 发现已关闭 / 窗口隐藏时只停表、不停子进程 | ✅ 修：四处补 `_stop_worker_process()`（幂等）；`pause` 的代价（恢复要重新握手，空载实测约 135 ms、满载数百毫秒，这段时间不截图）写进方法 docstring。用例：`tests/test_proactive_worker_adapter.py` 四条 |
| m3 | 构建门的复制范围大于验证范围（门只验非点目录与 `*.zip`，脚本整目录复制） | ✅ 修：判据收在**门**里——包根出现非候选条目（`bundle_stray_entry`）或同一 owner 多份包（`bundle_duplicate_id`）就在**复制之前**中止构建（三端脚本只看退出码，不必各自枚举候选，避免第二份候选判据）。`docs/ONEDIR_PACKAGING.md` 同步 |
| m5 | supervisor `STOPPING` 重入重计关闭预算并重发 shutdown；STOPPING 期间的 `start` 被静默丢弃 | ✅ 修：`stop()` 在 STOPPING 期间是幂等空操作；适配器把 STOPPING 期间的 start 记成待补拉、进程停定后自己再起（"隐藏→恢复"正好落在这个窗口里，此前恢复后识屏再也不开工且无任何报错） |
| n1 | `stop()` 的"进程已不在"分支不停 `_io_timer` | ✅ 修 + 不变式用例：不论从哪个分支收口，`stop()` 之后不留活动定时器 |
| n2 | 预检回执的 `child_pid` 采信子进程自述 | ✅ 修：pid 由父侧 `Popen` 给出（runner 由 `subprocess.run` 换成 `Popen` + `wait`，超时仍只杀这一次直接起的进程）；回执里那一栏既不采信也不对质 |

**缓做（本轮不改，登记在此）**：

| 编号 | 问题 | 缓的理由 / 归属 |
|---|---|---|
| m1 | 预检回执没有 nonce，理论上可被同名旧文件顶替 | 回执路径在每次新建的私有临时目录里（`tempfile.TemporaryDirectory`），顶替要先拿到那个目录；收益低于改动面（回执 schema 升版）。归属：探针硬化片 |
| m2 | 预检不可取消（父侧不持有句柄），只能等 `timeout` | 30 s 单次上限已经有界；取消要父侧留句柄 + 事务层接口，与"装前预检要不要并发"一起做。归属：Phase 4B-5 |
| m4 | 构建机在预检阶段执行包代码（`create_host()`），构建机上没有告警/文档 | 门与产品口径一致地**不声称隔离**（`pet/feature_package_preflight.py` 模块 docstring 已写死"不是沙箱"）；缺的是构建脚本侧一句告警。归属：构建脚本文案批次 |

### 八之二、修复轮：复审提出的三条 + M3 补漏（同日）

上面那批的**复审判**又提了三条（N1/N2/N3）与一处 M3 漏改；N1/N2 是同一处代码（M2 的
"装回"）在两段式**不同阶段**上的两种伤害，N3 是 m5 那条修复的收口缺口。

| 编号 | 问题 | 处置 |
|---|---|---|
| N1 | M2 的装回把控制器的 apply 重试阶梯打断了：装回重新占上本进程的版本 pin，而重试阶梯（`ModCenterController._retry_apply`：`management_lock_busy` 等可重试 reason）恰好要在**已交还**状态下才走得通——重试被自己挡在 `version_in_use` 上（`feature_package_transactions.py:838-845`），重试到超时也解不开，用户拿到"等待相关程序自然退出后完成操作"而挡路的正是他自己这只桌宠 | ✅ 修：`submit("apply", …)`（只有控制器的重试走这条入口）先把宿主**重新交还**再进事务（`FeatureManagementManager._rearm_apply`），交还后 `_released_for_apply` 照旧置位，这一趟再失败就再装回一次。用例：`tests/test_feature_apply_retry_ladder.py::test_the_retry_ladder_finishes_the_delete_after_releasing_the_restored_binding`（真事务层 + 真宿主 + 真控制器；先持住操作锁制造可重试失败，再放开。改前：删除永远做不完；改后：阶梯做完删除，且失败当场装回那一半仍成立） |
| N2 | M2 只覆盖"接受前失败"：事务在 `state_pending` **之后**失败时（`:827-845`、`:902-916`），落盘 active 已经指向候选版本，装回会走进 `load_pending` 的启动确认路，而本进程不是启动方（`startup_permit` 以 `not_awaiting_startup` 拒绝）——"装回"于是变成一次带假理由的 `host.fault("startup_load_failed")` | ✅ 修：只在事务**未被接受**时装回（`FeatureManagementManager._transaction_accepted`：`service.inspect().pending_transaction` 是唯一权威；读不出状态时按"已接受"处理，宁可少做不许做错）。用例：`tests/test_feature_apply_retry_ladder.py::test_an_accepted_transaction_is_never_loaded_back_into_the_host`（同一条真链路；另一个占用者全程不放租约，事务先接受再卡住。改前 `last_result == recovery_required/startup_load_failed` 且 `host.state == "fault"`，改后如实回报事务结论） |
| N3 | m5 的"待补拉"只在 `ProactiveScreenAdapter.stop()` 里作废，而退出收口两条路径（`WorkerSupervisor.finish_app_shutdown`、`WorkerSupervisor._shutdown_live_for_tests`）**直接**调 `supervisor.stop()`：进程停定后适配器照常补拉，在整只桌宠正在退出的当口又拉起一个 worker 子进程 | ✅ 修：作废挂在 supervisor 的通知上而不是某个调用方上——新增 `WorkerSupervisor.stop_requested` 信号（在重入闸**之前**广播），适配器连上它清 `_pending_start`；`finish_app_shutdown` 收口时对每个 supervisor 一律调一次 `stop()`（本身幂等，这一次是为了把作废广播出去）。用例：`tests/test_proactive_worker_adapter.py::test_an_exit_drain_never_takes_up_a_pending_start`（两条路径各一条参数，真子进程；改前收口后又拉起一个 worker，改后 `state == "stopped"` 且进程为空），m5 那条"隐藏→恢复要补拉"的用例同时保持绿 |
| M3 补漏 | 作者面文案只改了一部分：`docs/modding/README.md` 仍写着"清单 + 验签 + 装前子进程预检"与"宿主按完整验签链重新回答" | ✅ 修：两处都改成与门一致的口径（"清单完整性 + 摘要校验 + 装前子进程预检"／"宿主按同一套完整校验链（清单完整性 + 摘要 + 版本与身份核对）自己重新回答——同样是显式用户信任，不是发布者认证"）。守卫扩到这份 README：`tests/test_feature_packaging_wiring.py::TestTheChainDoesNotClaimPublisherAuthentication::test_the_author_facing_readme_never_says_the_chain_verifies_signatures`（定向规则：只钉作者面 README；`PORT-STATUS.md` 与 `pet/plugins/package_trust.py` 里描述那条链自己做什么的"验签/指纹对账"措辞是对的，不误伤） |

**缓做（复审第二轮的 N4/N5/N6，本轮不改，登记在此）**：

| 编号 | 问题 | 缓的理由 / 归属 |
|---|---|---|
| N4 | `build_mod_example.py` 的标准产出是"同名目录 + 同名 ZIP"，两份一起放进同一个发布根会被门判 `bundle_duplicate_id`（这是 m3 的设计意图），缺的是作者文档一句 | ✅ 文档这一半本轮补了：`docs/modding/AUTHORING-HANDBOOK.md` §打包与自检 加"发布根里每个 owner 只放一种形态"（并写明门在复制之前就中止）。行为不改——判据本身正确，只是要作者别把两份都拷进发布根 |
| N5 | 补拉（STOPPING 窗口里那一半）会让 `state_changed` 出现乱序：订阅者若按"每一次状态变化"做增量推断会看到 `stopping → stopped → starting → handshaking → ready` 里夹着一次迟到的事件 | 订阅者读的是快照（`status_snapshot()` / `state`），乱序不影响它们；要修得给补拉一条"代次"语义（迟到的旧代次事件直接丢），属状态机精修。归属：proactive worker 状态机片 |
| N6 | B1 的守卫在**源码解释器**下跑入口，覆盖不到 windowed 冻结包的 stdio（冻结版 `--worker` / `--feature-package-probe` 的管道行为只在 onedir 产物里才真实） | 需要一份真冻结产物（`build_onedir` 的 windowed exe）才能测；本机没有随包分发的探针 bundle，属"冻结包实测待办"。归属：Phase 4B-5 冻结构建片（与 host-worker 真实冻结构建同批） |

**本轮顺带发现的既有问题（不在盲审清单里，本轮未修）**：`tests/test_proactive.py` +
`tests/test_proactive_worker.py` + `tests/test_proactive_worker_adapter.py` **三个文件一起**跑，
会在 `test_adapter_drives_the_real_worker_over_the_default_command` 处触发 Windows 访问违规
（进程直接段错误，没有汇总行）。**与本轮改动无关**：把 `pet/` 与 `tests/` 整体退回 `6e2f723`
后同样 3/3 复现（去掉 `test_proactive.py` 或去掉后两个中的任一个即不崩，2/2 通过）。
全量套件会经过这段，归属与
[`docs/QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md`](../QT-LIFECYCLE-FULL-SUITE-STABILIZATION-2026-09.md)
那一族同源（泄漏的 worker supervisor / QProcess 在后续用例的事件循环里被拆除）。
**复审轮补记（同日）**：这条组合本轮跑了两遍（修 N3 前 / 修 N3 后各一次）都**正常退出**
（`125 passed + 2 failed`（那 2 条是本轮新用例，未修时红）/ `127 passed`），没有复现那个访问
违规。登记保留（它是时序相关的），但"本轮全绿"不等于它已消失。

---

## 九、DLC 第四片回写：AI 对话官方包（`official.ai-chat`）

上面 §二 Phase 5B 那格写的是「AI 对话整包未做，PLAN.md 记了『放弃』」。本片把
**包**这一半落了地，但**没有**改内置聊天——两条腿并存，这也是本片与前几片最大的口径
差别：内置 AI 对话（`pet/chat/` + `pet/app.py` 的 `open_chat*`）**一个字节没动**，
包是它的可插拔形态，开自己的窗口、用自己那本配置与自己的会话目录。

| 项 | 新事实 | 证据落点 |
|---|---|---|
| 包本体 | ✅ `features/ai-chat/`（`mod.json` + `host/` 30 个文件，上游 `features/ai_chat` 整包移植） | `git ls-tree -r --name-only HEAD \| grep '^features/ai-chat/'` |
| 宿主绑定 | ✅ `bind_ai_context`：配置命名空间 / 偏好面 / 凭据库 / `FeatureUserDataPort`；**不给**桌面查询、窗口操作面与 Core API 端口 | `pet/feature_host_bindings.py`、`tests/test_ai_host_binding.py` |
| 呈现面 | ✅ `pet/ai_bindings.py`（`AiPetView` / `AiFileView` + 进程级提供方），AppShell 注册主实例的聊天宿主 | `pet/app.py::_build_feature_runtime`/`_ai_pet_view`、`tests/test_ai_bindings.py` |
| 装卸链 | ✅ 与识屏包同一条 Core 自有链：真打包 → 清单完整性 + 摘要校验 + 装前子进程预检 → 真事务 → 真宿主 → 真菜单 | `scripts/build_ai_chat_package.py`、`tests/test_ai_package_e2e.py` |
| 识屏↔聊天联动 | ✅ 包侧接收端（`ExternalTurnReceiver` + `pet.plugins.services` 服务路由）：识屏包投结构化结果 → 写进**包自己的**会话存储 | `features/ai-chat/host/chat/external_turns.py`、`tests/test_ai_package_host.py`、`tests/test_plugins_services.py` |
| Core 缺口补齐 | ✅ `pet/async_exit.py`（owner 退出闸门）、`pet/plugins/services.py`（owner 服务路由）、`FeatureUserDataPort` | 各自同名用例文件 |

**四处有意的分歧（都是本仓库拓扑决定的，不是没做）**：

1. **命令归包**：上游的 `chat`/`quick_chat` 菜单命令由 Core 的 `pet/ai_bindings.py`
   经 `host.attach` 挂 Core 回调（`instance.open_chat`）——那条路的前提是上游 Core 里
   已经没有内置聊天。本仓库内置聊天不动，包开自己的窗口，命令跟着包 Runtime 走
   （`AiPackageRuntime.commands`），菜单文案带「（包）」后缀与内置项区分。
2. **包不进配置树**：上游把包的偏好绑在 app 配置树的 `chat` 节点上（包与内置共用一份
   provider 配置）。本仓库把包的配置与偏好收在 `feature-data/official.ai-chat/` 下，
   两套聊天各持一本账（机器判据：`test_the_package_never_touches_the_builtin_chat_configuration`）。
3. **不引第二份摘要**：上游 `host/config.py` 从 `pet.feature_config.namespace_revision`
   现算命名空间摘要；本仓库直接用配置端口自己的 `revision()`（同一算法），
   于是 `pet/feature_config.py` 这个模块**不需要移植**。
4. **退出闸门显式退订**（这是修上游的一处缺陷）：上游 `AiRuntime.close()` 不把
   参与者从 Core 退出闸门里摘出来，只靠闸门轮询 `drain_status` 回收——于是
   "停用/卸载后到下一次退出事件之间"闸门里登记的是一份已死的参与者，每装一次包多
   一份。用例族跑出 14 份残留（`tests/test_async_exit.py::test_a_quit_passes_through_when_nothing_is_registered`
   被挤红），已改为 `close()` 里显式 `unregister`。

**未做（第四片交付时的边界；后续接线见 §十）**：

| 未做项 | 归属 | 说明 |
|---|---|---|
| 包内 UI 与内置聊天的功能对齐 | 后续片（**未排期**） | 上游包是内置聊天某个较早时间点的**分叉**：缺 markdown 渲染、思考链展示、`#191` 的布局修复、联网检索等后续产品修复（`host/chat/widgets.py` 上游 2219 行 vs 内置 2532 行）。本片按"整包移植上游形态"落地，**没有**把两套实现合并（本片口径明确禁止），因此包的聊天窗在功能上落后于内置聊天窗。要对齐就得把内置那份 UI 再分叉进包（或反过来让包复用内置实现），两者都是新决策。 |
| 包的 `notifier` / `auth_callback` 接线 | 同上 | `AiRuntime.create_window` 的这两个参数本片传 `None`（上游由 `bind_ai_window` 从 Core 取）。缺失的效果是"未配 Key 时不能一键跳到 API 设置页"，包自己的设置面板不受影响。 |
| 文件解读的触发接线（拖文件 → 包的解读器） | ✅ 阶段 3（2026-10-17） | 已落地 `pet/file_interpret_router.py`：包聊天窗开着走包的 `FileInterpretController`，否则回落内置；legacy/overlay 两条投喂链共用同一路由。见 [`PR-REPORT-PACKAGE-WIRING-2026-10-17.md`](../PR-REPORT-PACKAGE-WIRING-2026-10-17.md)。 |
| MOD 中心 UI 的「装官方包」按钮 | ✅ 阶段 3（2026-10-17） | 未安装官方包显示「安装」行；`LocalFeatureRuntime.install_official` 复用 Core 自有事务链，来源支持冻结态 `<exe>/features/`、源码态构建缓存与 `PET_OFFICIAL_PACKAGE_ROOT`。 |
| 冻结包投递（随发行版携带预构建包） | 打包/构建片 | 与识屏包同：只有源码态打包入口。 |

## 十、AI 包窗口回调接线（2026-10-15 已合入；2026-10-17 复审三条修复）

交接 §6.2 第 1 项已实现：Core 注册通知和固定 AI owner 设置导航，包挂载传入
`AiRuntime.create_window`。缺 Key 时保留输入并提供鼠标/键盘入口；认证失败通知
进入同一 owner 设置；停用/关闭后旧通知失效。同 owner 导航复用草稿，独立设置
宿主使用全局配置视图，凭据作用域与进程级运行时一致。已有独立设置窗口通过
固定 AI owner 的局部导航端点复用，保留最大化状态及草稿；通知派发读取最新已保存
开关，未保存草稿不改变通知行为。复审两项 P2 已有红绿回归。内置聊天保持原样。

真实 Cocoa 窗口、真实包生命周期、独立设置子进程与 loopback HTTP 401 已覆盖；
本机基线另有 Windows 平台假设等失败，全量发布门的最终结论以报告为准。
文件解读投喂、官方安装按钮、UI 终态对齐与 5A 均未包含在本片。
详见 [回调接线报告](../PR-REPORT-AI-WINDOW-CALLBACKS-2026-10-15.md)。

**2026-10-17 复审**：PR #282 已合入本分支（`e5788b0`）。复审出的三条缺陷已修——①带
`extension:` 深链接冷启动时搜索索引不再收扩展面板的行（此前面板收走后每次按键抛
`libshiboken: Internal C++ object (SettingRow) already deleted`）；②请求通过后表头还原成
provider/model（此前配好 Key 回来仍挂着「打开 API 设置」）；③导航失败如实回 `b"no\n"`
（此前先回 ok，面板没挂上时点击方零反馈）。红/绿对照（stash 产品文件后 3 red → 3 green）
与边界见 [复审修复报告](../PR-REPORT-AI-CALLBACK-REVIEW-FIXES-2026-10-17.md)。

---

## 十一、未移植账本（2026-10-17 与作者分支逐文件核对）

**核对方法**：`git diff --name-status 45619ce <作者实现分支>`（分支名与基线 SHA 属仓库内
工作档案，见 `.scratch/dlc-fusion/PLAN.md`；本次快照的分支 HEAD 是 `11646be`，2026-10-10，
基线 `45619ce`，2026-09-24）→ 874 个改动文件（已排除
`content/` 素材与 `.scratch/`）。逐个用 `git cat-file -e` 判本分支存在性；同名文件用
`git rev-parse` 比 blob 判"逐字节相同"。**本节以代码为准，不以本文旧判定为准。**

### 账本：作者已完成的部分 → 本分支

| 作者已完成的面 | 本分支状态 | 一句话 |
|---|---|---|
| Phase 1 `pet/content/`（8 文件） | ⚠️ 换形 + 6 项能力真缺 | 见 Phase 1 格：能对上安装/停用/删除/手动回滚/路径安全；缺任意版本激活、逻辑 SHA-256、事务日志与恢复、激活后自检、manifest 严格契约、bundled/Starter |
| Phase 2 底座（`events` / `capabilities` / `contributions` / `ports` / `package_binding`） | ✅ 逐字节相同 | 5 个文件 blob 完全一致 |
| Phase 2 具名内核（`runtime.py` / `manifest.py` / `config.py` + `builtin/festival_reminder/`） | ❌ 未移植 | `PluginRegistry` / `PluginContext` 零命中；节日提醒仍硬绑 `AppShell` |
| Phase 3A agent-link worker（3 文件） | ⛔ 拍板不移植 | 主线 `pet/agent_link.py` 是现行权威 |
| Phase 3B 主动识屏 worker | ⚠️ 换形 | `worker/runtime.py` → `pet/workers/proactive_screen_worker.py`；`worker/vision.py` → `pet/vision.py` |
| Phase 4A 识屏包（26 文件） | ⚠️ 换形，3 个未移植 | 14 字节相同 / 6 同名小改 / 3 换形 / 3 未移植（含 `host/migration.py`） |
| Phase 4B-1/2/3 事务链 | ✅ 换形移植 | `test_feature_install_state` / `test_feature_version_lease` 是作者 280 个测试改动里**仅有的两个**逐字节相同 |
| 4B-4 管理 UI | ✅ | 「功能扩展」格已由 `LocalFeatureRuntime` 回填 |
| 4B-5 真实冻结构建 | ❌ | 与 Phase 5A 同一缺口 |
| Phase 5A Setup / 分发 / 签名 | ❌ | 见下方清单；**作者自己也没交付完** |
| AI 对话包（30 文件） | ✅ 全量 | 作者 30 个全在；本分支多 `mod.json` + `host/contributions.py` + `host/runtime_mount.py` |
| `docs/modding/*`（10 篇）、`docs/plugin-*`（28 篇）、`examples/mods/`（11） | ✅ | 逐字移植（死链已降级） |

### 未移植清单（按卡路程度）

1. **内容硬门片**：逻辑 SHA-256、事务日志与崩溃恢复、激活后自检、manifest 严格契约、
   任意版本激活、bundled/Starter、结构化坏包诊断、`python -m pet.content` CLI。
   **前置性最强**——作者的推进顺序里 4B-1.5 资源硬门排在"官方功能选装"之前。
   **2026-10-17 状态**：前五项已按目录布局落地（阶段 1 报告）；
   bundled/Starter 与 `pet.content` CLI 判不适用；官方功能选装（5A）仍待阶段 3/4。
2. **Phase 2 内核收口片**：`PluginRegistry` / `PluginContext` / `PluginManifest` /
   `PluginConfigStore` + 节日提醒插件化。终态"连节日提醒都是包"的直接前提；
   `festival_service.__init__(self, app)` 这个签名就是不拆包的天花板。
   **2026-10-17 状态**：四个具名件与 `official.festival-reminder` 插件已落地
   （阶段 2 报告）；`FestivalReminderService` 保留旧签名并新增可选端口参数，
   默认装配仍走内置，插件路径由 `PET_FESTIVAL_PLUGIN=1` 启用。
3. **冻结 / Setup / 签名链**：`scripts/` 34 个 + `packaging/` 9 个，加依赖侧的
   `pet/core_{maintenance,code_gate,uninstall,registration_cleanup}.py`、
   `pet/runtime_layout.py`、`pet/feature_probe_*.py`、`packaging/licenses/LIBSODIUM-LICENSE.txt`。
   同一组里的 `check.py` / `check_docs.py`（ruff + ruff format + mypy + 离线 markdown
   链接检查的统一入口）可以提前单独补，不依赖 Setup。
4. **测试面**：作者新增 122 个测试里 **106 个**在本分支连同名文件都没有；另有 79 个
   "同名但内容仍是 merge-base 旧版"（多为作者对既有测试的改动，与插件化无因果关系，
   不算移植缺口）。

### 一条必须写明的边界

作者 P5A **自己也没交付**——他 roadmap 原文：「Setup 只有编译证据，真实安装更新卸载、
冻结业务/便携、用户和干净环境门未完成，不宣布 Phase5A/5B-1 交付完成」。所以
"本分支没移植 P5A"不等于"落后于一个已完成的上游"。

---

## 十二、作者分支看不到的主干减法（不是移植缺口）

作者分支 HEAD 是 2026-10-10、基于 2026-09-24 的分支点。本分支随后有 **5 个提交整块删掉
16 个文件**——它们不是移植遗漏，是本仓库更晚的主干决定。列在这里，免得下次核对再把它们
算成缺失：

| 域 | 被删载体 | 提交 | 本分支靠什么承载 / 损失 |
|---|---|---|---|
| Agent 事件汇报概率门 | `pet/report_gates.py`（142 行） | `8998a6c`（2026-10-06） | **无替代**。只剩固定去抖/节流 |
| Agent 异常检测三件套 | `pet/stuck_detector.py`（574）/ `behavior_detector.py`（739）/ `exploration_watchdog.py`（718） | 同上 | **无替代**。不再推断 Agent 卡住/循环/纯探索，`intervention-recommended` 事件面消失 |
| 检测器设置页 | `pet/exploration_watchdog_settings.py`（297） | 同上 | 设置树无该页；31 个键仍躺在 `pet/config.py:307-331 _AGENT_LINK_REMOVED_KEYS` |
| 审批/提问回写 | `pet/dsh_responder.py`（59） | 同上 | **无替代**。气泡点"同意/拒绝"不再回写 `/api/respond` |
| 桥接看门狗控制通道 | `pet/dsh_control.py`（140） | 同上 | **无替代**；`integrations/dsh-pet-bridge` 对 watchdog 同样零引用 |
| 多进程碰撞 IPC | `collision_ipc.py`（1311）/ `collision_client.py`（571）/ `collision_codec.py`（262）/ `collision_debug.py`（34） | `286b275`/`acf00f5`（2026-09-23） | 换形：`pet/sprite_collision.py`（753 行）进程内每 tick 直调。保留/丢弃清单写在 `sprite_collision.py:9-33` |
| 第二只桌宠进程 spawn | `pet/instance_launcher.py`（63）/ `child_pet_cleanup.py`（251） | 同上 | 换形：`overlay_shell.spawn_pet()` / `clear_spawned_pets()`。**没有"父宠退出后子宠继续运行"** 这条语义 |
| 旧版右键菜单 | `pet/context_menus/legacy.py`（103）/ `menu_styles/legacy.py` / `menu_templates/{legacy,modern}.json` | `339292e`（2026-10-08） | **无替代**：单一 `modern-default-v1` + 用户可编排 `context_menu_layout`；`context_menu_template` 键读入即丢弃 |
| Config 域 facade | `pet/config_domains.py`（118） | `703e821`（2026-10-09） | 无损失（作者自己标注"只建不用，调用点未迁移"） |

**唯一有实质用户损失的是第一组**：Agent 汇报 + 三类检测 + 审批回写 + 控制通道合计
**2669 行**（142+574+739+718+297+59+140，按上表逐项相加），全部零替代。其余要么换形等价、
要么是作者自己都未接入的脚手架。

**核对口径**：判"作者有、本分支无"时先分到这两张表——§十一 是真缺口，§十二 是主干减法。

---

导航：[MOD 文档入口](README.md) · [移植基线与现状](README.md#移植基线与现状2026-10-13) ·
[作者总路线图](../plugin-roadmap/PLUGIN-DLC-ROADMAP-v5.md) ·
[开放顺序与第三方接口](../plugin-roadmap/PLUGIN-DLC-OPENING-ORDER-AND-THIRD-PARTY-INTERFACES.md) ·
[移植交付证据](../PR-REPORT-DLC-MOD-CENTER-2026-10-13.md) · [全文档索引](../INDEX.md)
