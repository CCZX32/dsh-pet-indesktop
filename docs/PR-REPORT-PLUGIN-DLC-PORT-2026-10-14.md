# PR 报告：DLC 支线 D1–D4 移植与盲审修复批（MOD 中心线）

> **基线**：`7575572`（S4「MOD 中心收官」——前作报告
> [`PR-REPORT-DLC-MOD-CENTER-2026-10-13.md`](PR-REPORT-DLC-MOD-CENTER-2026-10-13.md) 的收尾提交）
> **分支**：`dlc/mod-center-port`　**日期**：2026-10-14　**HEAD**：`584ca57`（写完本报告时）
> **范围**：19 个提交 / 112 处文件（新增 58 / 修改 54，`+16265 / −848`；在 `cf9e2e6` 的
> 110 处 `+15414 / −844` 之上多了门文案修复 `fac40e3` 与复审修复轮 `584ca57`）
> **关联**：`.scratch/dlc-fusion/PLAN.md`（移植判定）、`D2-RUNTIME-SPEC.md`（D2 实施 spec）、
> `D2a-HANDOFF.md` / `D2b-HANDOFF.md` / `D4-HANDOFF.md`（逐片断点）、
> [`docs/modding/PORT-STATUS.md`](modding/PORT-STATUS.md)（§六/§七/§八/§八之二 回写）、
> 前作报告（S1–S4 六片汇总，本报告不重复它的内容）

> **范围口径（先读）**：本报告覆盖 `7575572..584ca57` 这 19 个提交（D1 → D4 → 盲审修复 →
> 崩溃修复 → flake → 门文案修复 → 复审修复轮）。分支相对 `main` 的**累计**面更大——
> `git diff main...HEAD` 是 **178 处文件 / 131 新增 47 修改 / `+36064 −987`**，其中 S1–S4 六片已在 2026-10-13 的前作
> 报告里逐文件写过，本报告只列累计数字、不重复逐文件说明。

## 一、核心特性

S1–S4 已经把 MOD 中心（角色资源）与 workers 子进程底座搬进来，但**功能扩展包这条腿只到
「信任链 + 事务 + 状态机」，没有宿主运行时、没有导入链、没有分发链**——代码在、方向盘没装。
本片把这条腿接通：第三方本地功能扩展包从"装不上/装上了也看不见"变成
**导入（ZIP / 目录）→ 启用（菜单贡献出现）→ 停用（贡献撤销、旧句柄失效）→ 卸载（个人数据保留）
→ 重装**全链可用，并在**装前用子进程预检**、在**构建期有可执行的门**。

| # | 能力 | 说明 |
|---|---|---|
| 1 | D1 文档同步 | 上游 phase 1–7 设计文档 28 篇按现行拓扑同步（其中 12 篇覆盖 2026-09-24 旧快照），新增 `docs/modding/PORT-STATUS.md` 逐 phase 状态对照 |
| 2 | D2 宿主运行时（片 1） | `pet/mod_api/v1.py` 公开契约真的跑起来：`FeatureHost` 注册表/状态机、从**已验签字节**装载 `host/`、`FeaturePackageBinding`、端口集 `FeatureHostContext`、`WorkerClient` |
| 3 | D2 接线（片 2） | 扩展菜单（两个菜单建造器共用一份追加函数）、owner 设置面板容器、草稿/占用生命周期门、`AppShell` 装配与收口、`extensions()` 从恒空换成真注册表 |
| 4 | D3 导入链 | 装前**子进程**预检（另一进程按同一份字节装载一次，回报 owner/契约/贡献）、官方 owner 保留与第三方 owner 路由隔离、ZIP 与目录归一 |
| 5 | D4 分发链 | 作者侧打包入口 + 发布/构建门（`scripts/verify_feature_package.py`）+ 三端构建脚本两道门与 `<app>/features/`；策略（能力上限/API 版本/本地包验签口径）收成唯一真相源 `pet/feature_policy.py` |
| 6 | 盲审修复包 | B1 冻结入口分流、M1 ID 规范形、M2 失败回装、M3 门文案诚实化、M4 worker 用完即停、m3 复制范围=验证范围、m5 STOPPING 窗口补拉、n1/n2 收口（见 §二-F） |
| 7 | 测试稳定性 | conftest 逐测试收口 `WorkerSupervisor`（修掉一条跨用例的原生访问违规）、一条全量负载下的轮询 flake |

**红线 / 不变量**（本片一个字都不许改的既有语义）：

1. **默认装配仍然 fail-closed**：没有 OS 沙箱时 `FeaturePackageTransactionService` 照样抛
   `self_check_sandbox_unavailable`（`pet/feature_package_transactions.py:772` 的守卫与用例继续绿）。
   本片给的是**另一条口子**：本地用户自选包走显式用户信任 + 装前子进程预检，且预检
   **只在拒绝方向有权威**、**不声称隔离**。
2. **官方 owner 保留**：本地包占用 `official.*` 一律拒绝（D3 把这个判定叫 `official_reserved`，
   M1 把 ID 判定收紧到规范形）。
3. **信任口径统一**：门 / 三端构建脚本 / 作者打包入口 / 作者文档都说「清单完整性 + 摘要校验 +
   装前子进程预检」，**不许**出现"验签"这种暗示发布者认证的说法（M3）。
4. **worker 模式不许静默回退**到进程内管线（S3 的三条机器可判规则未动）；本片只改
   "用完就停"与 STOPPING 窗口的补拉。
5. **冻结入口只转发、不抄第二份**：`--worker` / `--feature-package-probe` 的分流在
   `packaging/pet_entry*.py` 里转发给 `pet/__main__.py` 的那一份实现。
6. **零新增持久配置键**：`pet/config.py` 与 `tests/test_config_schema.py` 的键表本片未动；
   功能包自己的配置与个人数据落在 `feature-data/<owner>/`，不进 app 配置树。

## 二、修改文件说明

### 规模

| 面 | 文件数 | 增删（本片 `7575572...HEAD`，HEAD=`584ca57`） |
|---|---|---|
| `docs/plugin-*/`（D1 同步的 28 篇） | 28 | `+4873 / −737` |
| 其他文档（`docs/INDEX.md`、`docs/ONEDIR_PACKAGING.md`、`docs/modding/*`、本报告） | 14 | `+1136 / −53` |
| `pet/`（实现） | 39 | `+4805 / −46` |
| `scripts/`（打包入口与门） | 5 | `+692 / −0` |
| `packaging/`（冻结入口分流） | 2 | `+31 / −0` |
| `tests/` | 23 | `+4713 / −6` |
| `examples/mods/README.md` | 1 | `+15 / −6` |
| **合计** | **112**（58 新增 / 54 修改） | **`+16265 / −848`** |

（上表按 `git diff --numstat 7575572...584ca57` 分面汇总；`cf9e2e6` 时点是 110 处 /
`+15414 −844`，之后多了门文案修复 `fac40e3` 与复审修复轮 `584ca57` 这两笔。本报告自身
也在"其他文档"这一行里，所以它越写越长时这行的数字会跟着长——这不是回归。）

**分支相对 `main` 的累计**：178 处文件（131 新增 / 47 修改）、`+36064 / −987`
（含 S1–S4，见前作报告）。**落地形式**：`git diff main...HEAD --numstat`。

下面是**逐片、逐文件**的说明。同一文件被多片改过时，各片按提交分别列（所以把各片数字相加
会大于上表的净值）。

### A. D1 文档同步（`36ab810`，31 文件 `+5167 / −740`）

| 文件 | 增删 | 改了什么 / 为什么 |
|---|---|---|
| `docs/plugin-roadmap/*.md`（4 篇）+ `docs/plugin-phase-01..07/*.md`（24 篇） | `+4873 / −737` | 逐字同步上游新版设计文档 28 篇（其中 12 篇覆盖本仓库停在 2026-09-24 的旧快照、16 篇新增）。每篇 H1 之后加一段统一「移植基线头」，声明"正文里的『本仓库/已实现』说的是上游分支自己的进度"；上游独有文件的 70 处死链降级为「文字 + 反引号路径」，不留假链接。**为什么**：作者文档是 MOD/插件线唯一的设计依据，旧快照会让后来者按上游进度误判本仓库现状 |
| `docs/modding/PORT-STATUS.md` | 新增 `+242` | 本文是**本仓库自己的**状态对照：逐 phase 写「目标 / 本仓库状态（✅⚠️❌）/ 证据落点（文件:行号）/ 没做的原因与后续片归属」，另加 §一 五条必须先知道的口径与 §四 未做项汇总。**为什么**：作者文档与本仓库进度对不上号是这条线最大的沟通成本 |
| `docs/INDEX.md` | `+45 / −2` | 28 篇移植文档 + PORT-STATUS 全部登记（新文档入场规则第 1 条），并把相关行的「何时必读」改成触发条件 |
| `docs/modding/README.md` | `+7 / −1` | 移植基线表加一行指向 PORT-STATUS |

### B. D2 片 1：宿主运行时核心（`3ec2afe`，26 文件 `+3297 / −6`）

| 文件 | 增删 | 改了什么 / 为什么 |
|---|---|---|
| `pet/mod_api/v1.py` | 新增 `+53` | 公开薄接口 `Contribution` / `FeatureDefinition`（默认 `mount_contract="mod/v1"`）/ `MOUNT_CONTRACT`；顶层只 stdlib，`WorkerClient` 用 `__getattr__` 惰性导出（无 GUI 探针会 import 它） |
| `pet/mod_api/__init__.py` | 新增 `+6` | 不做任何顶层再导出——导入本包不得拉起 Qt |
| `pet/mod_api/worker_v1.py` | 新增 `+123` | 子进程侧 `serve(owner, handler)`：先认领租约 → HELLO → config_push → READY → request/response；stdout 只写 JSONL，日志走 stderr |
| `pet/plugins/feature_host.py` | 新增 `+279` | 进程级注册表与状态机（`provide/enable/disable/fault/state/enabled/bind_*/menu/close`），每个 owner 一份 `FeatureDefinition` + Runtime + 贡献句柄 |
| `pet/plugins/feature_packages.py` | 新增 `+396` | 装载器从**已验签的字节**导入 `host/` 代码（不是对磁盘路径现开 loader），处理包内相对 import 与 `common/`；卸载时从 `sys.modules` 摘除（换版本不许复用旧代码） |
| `pet/plugins/package_binding.py` | 新增 `+138` | `bind_verified_feature`：拿进程级 host pin → 装载 → `provide(..., enabled=False)` → 交回 `handle/context/selection` |
| `pet/plugins/ports.py` / `capabilities.py` / `contributions.py` | 新增 `+383` / `+34` / `+213` | 端口协议、能力闭集、贡献描述与撤销模型（Qt 只在 `SchedulerPort` 内惰性导入） |
| `pet/plugins/worker_launch.py` | 新增 `+150` | 已验签包 → `WorkerLaunch`（冻结 exe / 源码态解释器由 Core 决定）、两个引导字段 |
| `pet/feature_ports.py` | 新增 `+81` | `FeatureHostContext`：owner 作用域的配置/文档/状态端口 + 执行许可 + worker 位；端口根是 `feature-data/<owner>/` |
| `pet/feature_host_bindings.py` | 新增 `+161` | 把 `FeatureHostContext` 绑到 `Config.dir` 与 owner |
| `pet/api_ports.py` | 新增 `+73` | ABI 端口：**调用即抛固定码** `unsupported_capability`，绝不静默返回（拍板口径：宁可见错，不可假成功） |
| `pet/mod_runtime.py` | 新增 `+76` | `GenericModMounts`：GUI 侧挂载面（菜单 scope / 设置面板 / 撤销 / `sync()` / `close()`） |
| `pet/feature_management.py` | `+56` | 只搬 `discover_local_feature_ids`（扫 `plugins/*/`，`pending_transaction` 非空也算"有此 owner"——首次安装被打断也要被发现） |
| `pet/local_package_intents.py` | 新增 `+190` | `LocalPackageRoute` + `route_local_package`：有界读 `manifest.json` 做自动路由 |
| `pet/workers/worker_client.py` / `lease_bootstrap.py` | 新增 `+94` / `+47` | 宿主侧 Worker 客户端；子进程侧从环境认领 worker 租约并常驻到退出 |
| `pet/plugins/package_trust.py` | `+11` | 新增公开方法 `capture_sources()` 包住既有的私有快照缝——装载器必须用验过的字节，跨模块伸私有方法不可接受 |
| `pet/mod_center_controller.py` | `+29` | 宿主契约新增**可选**缝 `feature_route(source)`：注册表由安装状态导出、安装状态只能由导入改变，不加这条缝"首次安装"永远进不去（死锁） |
| `pet/plugins/__init__.py` | `+10 / −6` | docstring 与惰性导出同步现状 |
| `tests/test_mod_center_contracts.py` / `test_mod_center_routing.py` / `test_mod_host_runtime.py` | 新增 `+169` / `+109` / `+299` | 上游契约测试移植、路由用例、宿主运行时用例（真示例包端到端） |
| `tests/test_architecture.py` | `+7` | 零 Qt 名单加入 `mod_api/v1.py`、`mod_api/worker_v1.py`、`workers/lease_bootstrap.py` |

### C. D2 片 2：菜单 / 设置 / 生命周期接线（`dd91ff9`，25 文件 `+3403 / −48`）

| 文件 | 增删 | 改了什么 / 为什么 |
|---|---|---|
| `pet/feature_management.py` | `+682 / −8` | 新增 `FeatureManagementManager`（`extensions()` 的真值）、`LocalFeatureRuntime`（进程级宿主，core/settings 两个角色）、`LocalUserTrustSelfChecker`（显式用户信任，取代"一律拒装"）。旧 docstring 里"宿主管理面属后续切片"到此为止 |
| `pet/settings_mod_domain.py` | `+154 / −13` | `extensions()` 从**恒空**换成真注册表；新增 `feature_route` / `prepare_feature_revocation` / `feature_host()`（独立设置进程自建 settings 角色宿主，永不构造 Runtime）；`install_mod_domain` 挂 owner 面板容器与关窗收口 |
| `pet/mod_menu.py` | 新增 `+150` | `append_extension_submenu(menu, pet_like)` + `feature_runtime_for` + `move_before_quit`——**唯一实现**，两个菜单建造器都调它（避免拓扑分叉出第二份） |
| `pet/plugins/lifecycle.py` | 新增 `+104` | `FeatureHostLifecycle.prepare()`：事务层 `runtime=` 的唯一消费方，回答"现在能不能释放这个版本"（草稿 / 活 worker / 租约占用） |
| `pet/settings_mod_panel.py` | 新增 `+233` | owner 设置面板容器：草稿四件套转发 + 保存按钮 + 冲突/失败文案；从 `modern_settings_dialog.py` 拆出（该文件行数预算已紧） |
| `pet/app.py` | `+38` | `AppShell._build_feature_runtime()` 装配（建窗之前）+ 注入窗口/壳 + `_on_about_to_quit` **先关宿主**再走窗级收尾 |
| `pet/mod_center_controller.py` | `+40 / −8` | 新增可选宿主缝 `prepare_feature_revocation(owner)`：停用/删除/回滚/更新前问一次；**拒绝语改写**——宿主已接上，旧话（"安装子系统未接入"）变成假话 |
| `pet/plugins/feature_host.py` | `+22` | **真缺陷修复**：`remove` 改成 `provide` 的真逆（摘声明/绑定/面板缓存/执行登记）。旧实现留着 `_definitions`/`_bindings` ⇒ 同进程重装报 `feature already provided`，且下一次 `enable` 会把菜单挂回上一代已 close 的 Runtime |
| `pet/feature_package_startup.py` | `+31` | 新增 `release()`：交还绑定**并放掉本进程的 host `process_pin`**。不这么做，"卸载一个装过的包"在任何活进程里都不可能完成（pin 留到 atexit）；别的进程的 pin 照旧拦着，"等对方退出"那句话仍是真话 |
| `pet/mod_runtime.py` | `+21` | owner 变 `absent` 时 `_forget()`（丢 Runtime + detach），免得注册表留死对象 |
| `pet/sprite_menu_facade.py` / `pet/context_menu.py` | `+18 / −8` / `+3 / −1` | overlay 与 legacy 两个菜单建造器末尾各追加一次扩展子菜单 |
| `pet/window.py` / `pet/overlay_shell.py` | `+3` / `+3` | `feature_runtime = None` 占位，由 `AppShell` 注入 |
| `pet/feature_package_probe.py` / `tests/test_feature_package_transactions.py` | `+4 / −3` / `+5 / −2` | 订正失真说法："宿主运行时属本片范围外"→ 宿主运行时已落，缺的是沙箱本身 |
| `tests/test_feature_management.py` | 新增 `+521` | 管理器 + 进程级宿主（真示例包端到端，含"闸门跨卸载重装存活"） |
| `tests/test_mod_center_end_to_end.py` | 新增 `+589` | 设置页 → 控制器 → 两个真菜单建造器（命题 1–7 + 草稿门 + 接线守卫 + 独立设置进程自建宿主） |
| `tests/test_mod_menu.py` / `test_mod_lifecycle_gate.py` / `test_settings_mod_panel.py` | 新增 `+266` / `+158` / `+245` | 扩展子菜单（含双拓扑逐项一致与陈旧句柄）、草稿门、面板容器 |
| `tests/test_mod_center_controller.py` | `+100 / −2` | 撤回前预检的六个用例（取消中止 / 放行 / 启用不受门 / 更新也受门 / 无此能力照旧 / 预检抛错不卡用户） |
| `tests/test_architecture.py` | `+5` | 零 Qt 名单加 `plugins/lifecycle.py`（带日期与理由） |
| `tests/test_mod_center_routing.py` | `+2 / −2` | 两处断言文案跟拒绝语一起改 |

### D. D3 本地 ZIP 导入链 + 落地期修复（`211b5dc` / `78d471a` / `ad37137` / `b4348f7`，17 文件 `+1414 / −52`）

| 文件 | 增删 | 改了什么 / 为什么 |
|---|---|---|
| `pet/feature_package_preflight.py` | 新增 `+425`（后由 `78d471a` `+6 / −5`、`b4348f7` `+3 / −1` 收口） | 装前**子进程**预检：在另一个解释器里按同一份验签字节装载一次，读回 `create_host()` 的 `FeatureDefinition`，回答"装载得起来吗、owner 与清单一致吗"。子进程不导入 Qt；原因码闭集；父侧**不采信**子进程写回的形状。收口两笔：原因码表收口成闭集；运行器把"子进程自身起不来"也归进 `probe_unavailable`（环境问题 ≠ 包的结论） |
| `pet/feature_management.py` | `+29 / −9` | `LocalUserTrustSelfChecker` 增加可选 `probe`（生产装配默认给）：探针拒 ⇒ 事务在接受之前就返回 rejected，安装状态与版本目录一个都不动 |
| `pet/local_package_intents.py` | `+13` | `LocalPackageRoute.is_official` 按闭集登记表判定；官方 ID 是保留的 |
| `pet/mod_center_controller.py` | `+3` | 官方 ID 的本地包在 `unsupported_package_message` 处得到一句点名"保留 ID"的拒绝语 |
| `pet/__main__.py` | `+15` | 新增 `--feature-package-probe` 分流（冻结态由 `probe_command` 用同形参数起子进程） |
| `pet/app.py` | `+3 / −1` | 退出路径注释不再写收口泵的全限定名——它骗过了源码级守卫（守卫按字面查名，注释里出现即算命中） |
| `tests/test_feature_package_preflight.py` | 新增 `+269` | 21 条：真子进程、真 CLI、回执形状不被采信、原因码闭集 |
| `tests/test_feature_package_import_zip.py` | 新增 `+462`（后 `+20`、`+49`） | 17 条 + 收尾：坏清单 / 校验失败 / 官方 ID 拒 / owner 隔离 / 重复安装与版本解析 / 探针前置拒装 / 含空格与中文路径的 ZIP |
| `tests/_feature_import_package.py` | 新增 `+65` | 测试用的真包构造助手（ZIP/目录两种形态） |
| `tests/test_architecture.py` | `+8` | 零 Qt 名单加 `feature_package_preflight.py` 等 |
| `docs/modding/{PORT-STATUS,README,USER-GUIDE,MOD-CENTER-IMPLEMENTATION-PLAN-2026-10-10}.md` | `+93 / −36` | 回写 D2/D3 落地后失真的移植状态（§一-1 口径改写、§五 现状、新增 §六 回写表） |

### E. D4 分发 / 打包链最小子集（`6e2f723`，23 文件 `+1304 / −94`）

| 文件 | 增删 | 改了什么 / 为什么 |
|---|---|---|
| `scripts/verify_feature_package.py` | 新增 `+308` | **功能包的门**：单份 / `--bundle-root` / `--json` / `--target-platform`；只读、零 Qt、退出码 0/1、原因码闭集（探针的 `probe_*` 原样透传，不发明第二套词汇）。只在拒绝方向有权威 |
| `pet/feature_policy.py` | 新增 `+53` | 能力上限 / API 版本 / 本地包验签策略 / 资源上限的**唯一真相源**（零 Qt），宿主、打包脚本、构建门共用 |
| `pet/feature_management.py` | `+5 / −15` | 改从 `feature_policy` 取策略，删掉那份重复的 `FEATURE_CAPABILITIES` 字面量（旧导入名保留） |
| `scripts/build_mod_example.py` | `+124 / −38` | 从"测试材料级"升级为**正式作者入口**：源码树不合格、`host/` 里有打不进包的文件、输出已存在，都在写任何字节之前报一句能照做的错（不给 traceback）；`--check` 升级为「清单完整性 + 摘要校验 + 装前子进程预检」，与构建门同一套判据 |
| `scripts/build_onedir.ps1` / `build_linux.sh` / `build_macos.sh` | `+42` / `+28` / `+28` | `-FeaturePackages` / `--feature-packages`：源码侧门 → 复制进 `<app>/features/`（macOS 在 `.app/Contents/Resources/features/`）→ 产物侧门；`--target-platform` 按产物平台传 |
| `docs/ONEDIR_PACKAGING.md` | `+29` | 新增「随包携带功能扩展包」一节：两道门、候选判据、复制范围=验证范围、信任口径与诚实边界（产品运行期**还没有**读那个目录的地方） |
| `docs/modding/{README,AUTHORING-HANDBOOK,API-V1,CHARACTER-PACKS,COMPATIBILITY,HOST-ONLY,HOST-WORKER,PERSONA-TEMPLATES,USER-GUIDE}.md` | `+76 / −32` | 作者侧命令与现状表；同时订正 8 篇基线头里"宿主运行时尚未接入 / 打包脚本不存在"这句（D2/D3 之后即失真） |
| `docs/modding/PORT-STATUS.md` | `+35 / −1` | 新增 §七 D4 回写（逐条对照作者口径：做 / 不做 / 半做） |
| `docs/INDEX.md` / `examples/mods/README.md` | `+1 / −1` / `+15 / −6` | 索引「何时必读」更新；样例目录说明 |
| `tests/test_feature_package_gate.py` | 新增 `+292` | 22 条：正路径（目录/ZIP/相对路径/包根）、坏清单、官方保留 ID、篡改字节、平台不符、owner 不符由子进程预检抓、只读、JSON 纯 ASCII、解析期拦 Qt |
| `tests/test_feature_packaging_wiring.py` | 新增 `+257` | 30 条：构建入口正/负路径、**单一真相源守卫**、三端两道门与目标平台、文档一致性 |
| `tests/test_architecture.py` | `+5` | 零 Qt 名单加 `feature_policy.py` |

### F. 盲审修复包（6 个提交，31 文件触达 `+970 / −62`）

| 编号 | 文件（增删） | 改了什么 / 为什么 |
|---|---|---|
| B1 冻结入口分流 | `packaging/pet_entry.py` `+18`、`packaging/pet_entry_no_chat.py` `+13`、`tests/test_frozen_entry_routing.py` 新增 `+179` | 冻结包里 PyInstaller 执行的是**入口脚本**，`pet/__main__.py` 那条分流根本不会跑。漏掉这一步的 worker / 预检子进程会 import `pet.app`，把整只桌宠（窗口/托盘/素材库/ffmpeg）拉起来并撞主进程的单实例门。两条分流补在 `import pet.app` **之前**，实现只有一份（转发给 `pet/__main__`）。守卫打在真进程上：`sitecustomize` 元路径拦截器，走进桌面 UI 图即抛；另配一次真 worker 握手与真探针回执，证明"没走桌面图"是因为走了正确那条路 |
| M1 ID 规范形 | `pet/official_features.py` `+26 / −3`、`tests/test_official_features.py` 新增 `+22`、`tests/test_feature_package_import_zip.py` `+49` | 旧判定允许大写与末尾点、放过设备名：`Official.Screen-Understanding` 绕过官方闭集，`foo`/`Foo`/`foo.` 在 NTFS 上共用同一份 `feature-data/`。规范形收口为 `[a-z0-9][a-z0-9_.-]*` + 禁末尾 `.`/`-` + 禁设备名首段（`nul`、`con.package`），官方闭集按规范形比较。**无迁移负担**：没有任何 tag 包含本分支，仓库里也不存在大写 ID 的字面量或落盘写法 |
| M2 失败回装 | `pet/feature_management.py` `+14`、`tests/test_feature_management.py` `+43` | 两段式（先交还宿主绑定、再落盘）第一段成功而第二段失败时，交还成了净损失：菜单与会话消失到重启。改法：记 `_released_for_apply`，第二段非 settled 时把**当前落盘**的版本重新装回宿主；用户看到的只是这次操作失败 |
| M3 门文案诚实化 | `scripts/verify_feature_package.py` `+39 / −13`、`scripts/build_mod_example.py` `+6 / −5`、`scripts/build_{onedir.ps1,linux.sh,macos.sh}` `+9 / −5`、`docs/modding/{README,AUTHORING-HANDBOOK}.md` `+9 / −5`、`tests/test_feature_packaging_wiring.py` `+36` | 门自称"验签"，而 `local_user` 口径下 `manifest.sig` 被静默忽略。口径统一为「清单完整性 + 摘要校验 + 装前子进程预检」；报告新增 `trust_status`（`local_user`、未做发布者认证）与 `warnings`，包里带 `manifest.sig` 时给 `signature_ignored` 告警（放行但说出来）。守卫 `TestTheChainDoesNotClaimPublisherAuthentication` 把五个文件的文案一起钉住 |
| M4 worker 用完即停 | `pet/proactive.py` `+16 / −2`、`pet/workers/proactive_screen_adapter.py` `+19`、`pet/workers/supervisor.py` `+8`、`tests/test_proactive_worker_adapter.py` `+172`、`tests/test_workers_lifecycle.py` `+68` | 关闭 / 清空白名单 / tick 发现已关闭 / 窗口隐藏（pause）四处此前只停表、不停子进程——一个已经没人会用它的子进程会一直活着。四处补 `_stop_worker_process()`（幂等）；`pause` 的代价（恢复要重新握手）写进方法 docstring |
| m3 复制范围 | `scripts/verify_feature_package.py`（含在 M3 那笔之外的 `c840c23`）、`docs/ONEDIR_PACKAGING.md` `+8 / −2`、`tests/test_feature_package_gate.py` `+34 / −1` | 构建脚本整目录复制，而门只验候选 ⇒ 复制范围大于验证范围。判据收在**门**里：包根出现非候选条目（`bundle_stray_entry`）或同一 owner 多份包（`bundle_duplicate_id`）就在**复制之前**中止构建（三端脚本只看退出码，不各自枚举候选） |
| m5 STOPPING 窗口 | `pet/workers/supervisor.py`（含在 `725dc5c`）、`pet/workers/proactive_screen_adapter.py`、`tests/test_workers_lifecycle.py`、`tests/test_proactive_worker_adapter.py` | `stop()` 在 STOPPING 期间重入会重计关闭预算并重发 shutdown；STOPPING 期间来的 `start` 被静默丢弃——"隐藏→恢复"正好落在那个窗口里，此前恢复之后识屏再也不开工且**没有任何报错**。改法：STOPPING 期间 `stop()` 幂等空操作；适配器把这次 start 记成待补拉，进程停定后自己再起一次 |
| n1 定时器收口 | `pet/workers/supervisor.py`、`tests/test_workers_lifecycle.py` | `stop()` 的"进程已不在"分支不停 `_io_timer` ⇒ 不论从哪个分支收口都留一个活动定时器。补上 + 不变式用例 |
| n2 回执 pid | `pet/feature_package_preflight.py` `+22 / −12`、`tests/test_feature_package_preflight.py` `+34 / −1` | 预检回执的 `child_pid` 采信子进程自述，而包代码就在那个进程里跑。改为父侧 `Popen` 给出的 pid（runner 由 `subprocess.run` 换成 `Popen` + `wait`，超时仍只杀这一次直接起的进程）；回执里那一栏既不采信也不对质 |
| 文档回写 | `docs/modding/PORT-STATUS.md` `+37 / −1`、`tests/{test_feature_package_gate,test_feature_package_preflight,test_feature_packaging_wiring}.py` `+7 / −6` | PORT-STATUS 新增 §八 修复回写（含缓做项 m1/m2/m4 与顺带发现的既有崩溃）；测试里的文档串跟着 M3 的口径改 |

### G. 测试稳定性（`0317987` / `cf9e2e6`，2 文件 `+19 / −2`）

| 文件 | 增删 | 改了什么 / 为什么 |
|---|---|---|
| `tests/conftest.py` | `+12` | 逐测试收口 `WorkerSupervisor`（登记册范式，同 `AgentLinkManager`/`OverlayShell`/`MovieLibrary`）。`ProactiveScreenWatcher(execution="worker")` 构造期就 `apply_config` 起真 worker 子进程；只验路由/编解码的用例随后把它塞给替身适配器、从不 `shutdown()`，于是「handshaking + 活子进程 + 活动的 `_io_timer`(50ms)/`_handshake_timer`」跨用例存活十几例，被 GC 时的销毁落在后续用例的事件循环里 ⇒ Qt Windows 事件分发器的 QTimer 登记表项悬空、WM_TIMER 投递给已销毁对象 ⇒ 原生访问违规（崩点随套件进度漂移） |
| `tests/test_overlay_app_hosts.py` | `+7 / −2` | `test_show_balance_uses_overlay_host` 的余额气泡断言从"一轮 `processEvents`"改成有界轮询（2 s 宽预算）。全量高负载下 `singleShot` 一轮派不完（61 分钟全量里实测红过一次，隔离与文件内均绿）；按 `PR-MERGE-LESSONS` 的时序测试纪律修 |

### H. 复审修复轮（`584ca57`，9 文件 `+277 / −5`）

对 §F 那批的**复审**又提了三条（N1/N2/N3）与一处 M3 漏改。N1/N2 是**同一处代码**（M2 的
"装回"）在两段式不同阶段上的两种伤害，N3 是 m5 那条修复的收口缺口（下表的"为什么"里给了
每条一句话）。

| 编号 | 文件（增删） | 改了什么 / 为什么 |
|---|---|---|
| N1 重试阶梯被自己挡死 | `pet/feature_management.py`（与 N2 同文件，合计 `+47 / −1`）、`tests/test_feature_apply_retry_ladder.py` 新增 `+117` | 第二段失败时把那**当前落盘**的版本装回宿主（M2）会重新占上本进程的版本 pin，而控制器的重试阶梯恰好要在**已交还**状态下才走得通——重试被自己挡在 `version_in_use` 上（`feature_package_transactions.py:838-845`），重试到超时也解不开（挡路的不是别的程序，是这只桌宠自己）。改法：`submit("apply")`（只有控制器重试走这条入口）先重新交还再进事务（`_rearm_apply`），并照旧置 `_released_for_apply` 让这一趟再失败时还能装回。装回那一半行为不变 |
| N2 接受后装回 = 把宿主打成 fault | 同上 | 装回只覆盖"接受前失败"：事务在 `state_pending` 之后失败时落盘的 active 已指向候选版本，装回走 `load_pending` 的启动确认路，而本进程不是启动方（`startup_permit` 以 `not_awaiting_startup` 拒绝）⇒ 变成一次带假理由的 `host.fault("startup_load_failed")`。改法：只在事务**未被接受**时装回（`_transaction_accepted` 读 `store.read()` 的 `pending_transaction`，唯一权威；没干净读出来按"已接受"处理）。用 `store.read()` 而不是 `inspect()`：后者会把"状态没读出来"一并报成 `pending_transaction is None`，方向正好相反 |
| N3 退出收口补拉待办的 start | `pet/workers/supervisor.py` `+11 / −2`、`pet/workers/proactive_screen_adapter.py` `+11`、`tests/test_proactive_worker_adapter.py` `+37` | "待补拉"只在 `ProactiveScreenAdapter.stop()` 里作废，而退出收口两条路径（`finish_app_shutdown` / `_shutdown_live_for_tests`）直接调 `supervisor.stop()`：进程停定后适配器照常补拉，在整只桌宠正在退出的当口又拉起一个 worker 子进程。改法：作废挂在 supervisor 的通知上（新增 `stop_requested` 信号，在重入闸**之前**广播，重入那次调用同样要作废），退出收口对每个 supervisor 一律调一次 `stop()`（本身幂等） |
| M3 漏改作者面文案 | `docs/modding/README.md` `+3 / −2`、`tests/test_feature_packaging_wiring.py` `+10` | README 仍写着"清单 + 验签 + 装前子进程预检"与"宿主按完整验签链重新回答"，改成与门一致的口径；守卫扩到这份 README（定向规则：只钉作者面 README，`package_trust` 内部链与 `PORT-STATUS` 里描述那条链自己做什么的"验签/指纹对账"措辞不动） |
| N4 作者文档一句 | `docs/modding/AUTHORING-HANDBOOK.md` `+4`、`docs/modding/PORT-STATUS.md` `+20` | 补"发布根里每个 owner 只放一种形态"（`build_mod_example.py` 的标准产出是目录 + 同名 ZIP，两份同放会被判 `bundle_duplicate_id` 并在复制之前中止构建，实测 rc=1 且文本模式本轮已能打出原因——`fac40e3`）；PORT-STATUS §八 补"八之二"修复轮回写与 N4/N5/N6 缓做登记 |

### 未改动（看起来相关但故意没动）

| 文件 | 为什么不动 |
|---|---|
| `packaging/dsh-pet.iss`、`scripts/build_pyside6_fcitx_plugin.sh` | 本片不含 Setup 选装器与便携模式（PORT-STATUS §七 明确划出边界） |
| `pet/feature_package_transactions.py` | 事务层只**消费**：D2/D3 通过 `runtime=` / `self_checker=` 注入，事务本身一个字没改（fail-closed 守卫原样） |
| `pet/mod_management.py` / `pet/mod_catalog.py` / `pet/mod_center_ui.py` | 角色资源那条腿是 S1b 的成果，本片只共用它的队列与入口 |
| `pet/config.py` / `tests/test_config_schema.py` | 零新增持久配置键（功能包配置与个人数据在 `feature-data/<owner>/`） |
| `pet/workers/{protocol,supervisor,launch,worker_entry}.py` | 除 M4 的两处（`stop` 幂等、`_io_timer` 收口）外未动；`worker` 模式不许回退的三条规则原样 |

## 三、实现要点

1. **装载必须走已验签的字节。** `FeaturePackageLoader` 的输入是
   `FeaturePackageVerifier.capture_sources()` 抓下来的 `host/**.py` 字节，而不是磁盘路径——
   上游注释写得很直白：`execution uses captured, digest-checked Python bytes, never a fresh
   unchecked SourceFileLoader`。D2 为此给 `package_trust` 补了一个公开缝
   （私有快照跨模块伸手不可接受）。**卸载只删安装副本**：导入过的代码仍留在 `sys.modules`，
   本仓库不承诺 Python 模块热卸载（PORT-STATUS §一-5）。
2. **注册表由安装状态导出，而安装状态只能由导入改变 ⇒ 死锁。** `ModCenterController` 的
   `extensions()` 是 `manifest["id"] in self.extensions` 的判据，第一次导入时它必然为空。
   修法是一条**可选**宿主缝 `feature_route(source)`：在 `unsupported_package_message` 之前
   问一次（返回 `None` = 现状）。这是 D2 能端到端成立的前置条件。
3. **两处上游同形的真缺陷**（不是顺手重构）：
   ① `FeatureHost.remove` 只置 `absent`，留着声明与绑定 ⇒ 同进程重装报 `feature already
   provided`，且下一次 `enable` 会把菜单挂回上一代已 close 的 Runtime；
   ② host `process_pin` 是进程级、到 `atexit` 才放 ⇒ "卸载一个装过的包"在任何活进程里都
   不可能完成（事务层要求占用全 free）。修法：`remove` 摘干净；`ProductionFeatureStartup.release()`
   显式关掉**本进程**那一份 pin（别的进程的 pin 照旧拦着，控制器那句"等对方退出"仍是真话）。
4. **预检的位置与权威边界。** 预检只在 `apply` 的候选检查处跑（`preflight_*` 绝不执行包代码），
   在**另一个进程**里按同一份字节装载一次，回报 owner / 契约 / 贡献数。它不占用宿主 host 租约、
   不声称隔离（同用户同权限同文件系统，超时只杀这一次直接起的进程），**说行的那一半仍由宿主
   按完整验签链重新回答**。父侧不采信子进程写回的形状，pid 取父侧 `Popen`。
5. **两道门的判据只有一份。** `verify_feature_package.py` 同时是作者自检（`--check`）、
   三端构建脚本的源侧/产物侧门；`pet/feature_policy.py` 是能力上限 / API 版本 / 本地包验签策略
   的唯一真相源（此前 `build_mod_example.py` 抄了一份字面量，现在有"不许有第二份定义"的守卫）。
   包根的候选**不猜**：每个直接子目录与每个 `*.zip` 都算候选——少打了 `manifest.json` 的目录
   会被如实报成 `route_rejected`，而不是被跳过。
6. **"用完就停"与 STOPPING 窗口。** 用户关掉主动识屏 / 清空白名单 / 外部改配置 / 隐藏窗口，
   这四件事对用户的含义都是"这个功能不再占内存"，所以四处都在停表之后停子进程；代价是恢复
   要重新握手（实测见 §四）。`start` 落在 STOPPING 窗口里不许被静默丢弃——记成待补拉，
   进程停定后自己再起一次。
7. **取舍与备选**：不搬上游的 LPAC 原生探针沙箱与密封 probe bundle（要钉版 PyInstaller tarball +
   MSVC + libsodium + AppContainer canary，属未排期的构建片），也**不**把预检包装成"沙箱"——
   文档与回执口径逐字写明它不是；`api` 端口取"存在、调用即抛固定码"而不是"干脆不提供"
   （宁可见错，不可假成功）；`<app>/features/` 只做到"发布载体契约 + 两道门"，产品侧读取链
   不在本片范围（不做就是不做，文档写明）。

## 四、性能分析

**方法（可复现）**：本机 Windows，Python 3.13.7，PySide6 6.11.2，`QT_QPA_PLATFORM=offscreen`，
空载交替取样。脚本落在 git 忽略的工作档案目录（`.scratch/` 不进提交）：

| 场景 | 命令 |
|---|---|
| 装前预检单次 | `python .scratch/dlc-fusion/_d3_probe_smoke.py`（真子进程，计时只包住 `LocalPackageProbe().run`） |
| 发布门单份 / 包根 | `python scripts/verify_feature_package.py <包>`、`... --bundle-root <根>`（`time.perf_counter` 包 `subprocess.run`） |
| worker 冷启动 / 收口 | `python .scratch/pr-report-metrics/probe_worker_cost.py`（真 QProcess + 真子进程 + 真事件循环） |
| 宿主装配与稳态 | `python .scratch/pr-report-metrics/probe_runtime_cost.py`（零包 / 装一包停用 / 启用三态各 3 次） |

| 指标 | 实测（本轮，样本量见括号） | 归属 |
|---|---|---|
| 装前预检单次 | **中位 0.29 s**（5 次：0.33/0.36/0.29/0.29/0.29）；子进程回执 `child_pid` 非 0、宿主 `sys.modules` 无包痕迹 | 新增路径；只在导入/升级/更新时付，每次安装 1 次 |
| 发布门：固定开销 | 0.195 s（3 次：0.194/0.195/0.200；在平台检查处即返回，不做校验与预检），其中裸解释器启动 0.044 s | 新增路径；构建/发布期 |
| 发布门：单份目录全链 | **中位 0.474 s**（3 次：0.469/0.474/0.488） | 同上；= 固定开销 + 校验链 + 子进程预检 |
| 发布门：单份 ZIP 全链 | **中位 0.563 s**（3 次：0.514/0.563/0.578；含 ZIP 解包到私有临时目录） | 同上 |
| 发布门：包根（2 候选） | 0.944 s（3 次：0.894/0.944/0.947） | 同上；候选数线性增长 |
| worker 冷启动 → READY | **中位 269 ms**（3 次：254/269/286；`pid` 每次不同、`alive=True`） | 既有路径（S2 记录 135 ms，今天这台机器偏慢，两个数都是真进程测得） |
| worker 收口 → STOPPED | **中位 30 ms**（3 次：30/30/30；结束态 `process=None`） | M4 新增的"停进程"这一步；每次停用/隐藏/关闭各 1 次 |
| 宿主装配（零安装包） | 中位 145 ms（3 次：141.8/144.7/173.8），`threads=1`、`children=0` | 新增路径；每个进程启动 1 次 |
| 宿主装配（装 1 包，停用态） | 中位 177 ms（3 次：168.0/177.4/231.5），`threads=1`、`children=0` | 同上（多出的是读该 owner 的安装状态） |
| 宿主装配（装 1 包，启用态） | 中位 161 ms（3 次：157.5/161.4/215.0），`threads=1`、`children=0` | 同上；host-only 包不拉子进程 |

**结论（逐条回答四问）**：

1. **稳态开销**：装一个 host-only 功能包并启用后，实测**主线程 1 条、子进程 0 个**——新增面
   在稳态不产生线程、不产生常驻子进程、不产生定时器（宿主是纯注册表 + 已装代码的 Runtime
   对象）。三条装配数字（零包 / 停用 / 启用）中位差 16–32 ms，且同一场景 3 次抖动达 ±60 ms
   （样本量小 + 本机同时在跑别的进程），**我不据此断言"停用比启用慢"这种差异是真实的**；
   能确定的是量级：**每个进程启动付一次 ~0.15 s 的装配**，与包数弱相关。
2. **新增路径成本与触发频率**：装前预检 0.29 s/次（每次安装/升级/更新 1 次，装不上就不落盘）；
   发布门 0.47–0.56 s/份（构建期，人工触发）；worker 冷启动 269 ms、收口 30 ms（每次
   启用识屏 / 停用或隐藏 1 次，是"用完即停"换来的一次性代价，对应的是隐藏期间**不再有**这个
   子进程及其 RSS）。以上都是**真命令的墙钟时间**，包含解释器/子进程启动。
3. **有没有引入新的系统调用 / 网络 / 磁盘 / 线程**：
   - **网络：零**。本片新增代码没有任何 HTTP/套接字调用（预检与被检包都不联网；本地包链
     不做发布者认证，也不去取签名）。
   - **磁盘**：预检在新建的私有临时目录里解包一次（`tempfile.TemporaryDirectory`，随用随删）；
     门对 ZIP 同样只读解包；安装事务落 `feature-data/<owner>/`（既有机制）。**没有新增常驻
     文件、没有新增缓存目录**。
   - **线程：零新增（宿主侧）**。worker 的读线程在**子进程**里（这正是选子进程而不是线程的
     理由之一）；宿主侧只有 Qt 主线程。
   - **子进程**：预检每次安装 1 个（用完即退）；worker 只在用户显式选 `worker` 执行位置或
     有 host-worker 包时按既有监督器起。
4. **内存与缓存**：宿主侧每个 owner 持有 1 份已装代码的 Runtime + 贡献句柄（host-only），
   无随运行时间增长的结构；`FeatureHost.remove` 摘干净声明与绑定（M2 修复顺带消灭了
   "旧一代 Runtime 被菜单句柄吊住"的引用）。worker 子进程在 M4 之后**隐藏/停用即消失**，
   不再有"没人用的子进程常驻"这一份常驻内存。

**运行期零新增开销的路径（不经过就不付）**：

- **D1 的 28 篇文档**与所有 `docs/**`：没有任何代码读它们（`tests/test_pr_report_discipline.py`
  只在测试期读），运行期零。
- **`scripts/*`（打包入口、发布门、三端构建脚本）**：`pet/` 下零 import——`git grep` 里
  `scripts.verify_feature_package` 只出现在 `scripts/build_mod_example.py` 的 `--check` 分支，
  产品运行期不经过。它们是**构建/发布期**成本，用户机器上不存在。
- **`pet/feature_policy.py`**：纯常量与纯函数（零 Qt），只有 `feature_management` /
  `build_*` / 门 import；运行期它是"被 import 一次、不再执行"的常量表。
- **`<app>/features/` 那条链**：构建时复制 + 两道门，**产品运行期没有读者**（PORT-STATUS §七
  写明）；不带 `-FeaturePackages` 的构建一行都不碰功能包。
- **装前预检**：只在"用户选了本地包要装/升级/更新"这一条路径上跑；不开那个动作的进程
  （含只跑桌宠、不用 MOD 中心的用户）零成本。
- **`tests/conftest.py` 那 12 行**与 `test_overlay_app_hosts.py` 的轮询改动：测试期收口，
  `pet/` 运行期零。

**复审修复轮新增路径的实测**（方法同 §四 开头；脚本 `.scratch/dlc-fusion/probe_perf_round.py`
与 `probe_read_cost.py`，真事务层 + 真宿主 + 真控制器）：

| 新增路径 | 触发时机（频率） | 实测（样本量） |
|---|---|---|
| `_sync_host` → `_transaction_accepted()` | **只在**"第一段已交还 + 第二段非 settled"这条失败路径上；成功路径与稳态一次都不问 | `store.read()` **14.9 ms/次**（300 次平均；含 install-state 读 + state 共享锁）。对照 `service.inspect()` 19.0 ms/次（还多一次 journal 目录枚举，且会把"没读出来"报成 `pending_transaction is None`）。GUI 线程一次调用，无新增线程/网络/新进程 |
| `submit("apply")` → `_rearm_apply` → `_release_host` | 只在控制器的重试阶梯上（`_retry_apply` 最多 5 次，delay 100/250/500/1000/2000 ms） | 复用既有 `release()`（关 host 绑定 + 放本进程租约），零新增系统调用；端到端实测"第一段失败 → 重试 → 删除完成" **1106 ms**（第一段 399 ms、重试段 707 ms，含 100 ms 起始延迟），删除成功 |
| `WorkerSupervisor.stop_requested.emit()` | 每次 `stop()`（含 STOPPING 期间的重入）+ 退出收口对每个 supervisor 一次 | **1.81 µs/次**（10000 次平均，1 个订阅者）；无新系统调用。退出收口是进程级一次，且 `finish_app_shutdown` 对已在 STOPPING 的 supervisor 这次调用本身就是幂等早退 |
| 稳态 | `enable` + `disable` 一次往返（不经过任何失败路径） | 805 / 818 / 924 ms（3 次），与本轮改动前同数量级；本轮新增判据一次都不跑 |

- **内存**：无新增缓存/容器；新增的只有 `pet/feature_management.py` 的一个模块级 `frozenset`
  与一个 Qt 信号（`stop_requested`，常量级）。
- **不经过就不付**：`feature_package_transactions.py` 一个字没改；`mod_center_controller.py`
  没改（重试阶梯原样，只是现在能真正跑通）。

## 五、实机运行记录

本机真实环境（Windows，Python 3.13.7，`QT_QPA_PLATFORM=offscreen`）跑过的命令与真实输出。
**不是 CI、不是 mock**：涉及子进程的地方起的是真解释器，涉及包装载的地方装的是真 ZIP。

### 5.1 D3 端到端：真 ZIP → 导入 → 启用 → 停用 → 卸载 → 重装

```
$ python .scratch/dlc-fusion/_d3_e2e.py .scratch/d4run/release/hello-local-1.zip .scratch/pr-report-e2e/data
== ZIP == D:\dsh-pet-wt-dlc\.scratch\d4run\release\hello-local-1.zip 2676 bytes
== 1. 导入（MOD 中心：import_source）==
   accepted: True
   result: True | 已导入；点击启用即可使用
   MOD 中心行: [('demo.hello-local', '离线打招呼', '1.0.0', False, '功能扩展')]
   安装状态: Inspection(status='disabled', revision=4, active='1.0.0', previous=None, enabled=False, ...)
   宿主状态: disabled
   扩展菜单 owner: ()
== 2. 启用（MOD 中心：perform('enable')）==
   accepted: True
   宿主状态: enabled | 菜单 owner: ('demo.hello-local',)
   贡献句柄: True | active: True
   作者自己的数据: {"greetings": 1} -> ...\data\dsh-pet-standalone\feature-data\demo.hello-local\memory.json
== 3. 停用 ==
   accepted: True
   宿主状态: disabled | 旧句柄 active: False
   扩展菜单 owner: ()
   安装副本仍在: 1.0.0
== 4. 卸载（保留个人数据）==
   accepted: True
   安装状态: None | 宿主状态: absent
   个人数据仍在: True {"greetings": 1}
   MOD 中心行: []
== 5. 重装 + 再启用 ==
   accepted: True
   安装状态: Inspection(status='disabled', revision=11, active='1.0.0', ...)
   MOD 中心行: [('demo.hello-local', '1.0.0', False)]
   accepted enable: True
   宿主状态: enabled | 菜单 owner: ('demo.hello-local',)
== OK ==
```

脚本走的是**生产装配**（`LocalFeatureRuntime` + `DialogModHost` + `ModCenterController` + 真菜单
建造器），不是替身。用户可见行为由这份输出确认：启用后扩展菜单出现 owner、贡献句柄可调用并
把作者数据写进 `feature-data/<owner>/`；停用后旧句柄 `active=False` 且 owner 从菜单消失；
卸载后安装副本没了而个人数据还在；重装后可以再启用。

### 5.2 D4：打包入口与发布门（正路径 + 三条件负路径）

```
$ python scripts/build_mod_example.py examples/mods/hello-local .scratch/pr-report-e2e/build/hello-local
created: D:\dsh-pet-wt-dlc\.scratch\pr-report-e2e\build\hello-local
ZIP: D:\dsh-pet-wt-dlc\.scratch\pr-report-e2e\build\hello-local.zip          （rc=0）

$ python scripts/build_mod_example.py .scratch/pr-report-e2e/build/hello-local --check
valid: demo.hello-local 1.0.0 (host-only)
检查：...\build\hello-local（directory）
  包：demo.hello-local 1.0.0（host-only） 声明平台 win32
  清单摘要：sha256:a9cc87662fc73456189ec02afbc2562af5999729e3e362cea81fd326e6a32727
  信任口径：local_user（未做发布者认证）
  装前预检：通过（owner=demo.hello-local，契约 mod/v1，贡献 1 项）
  结论：通过                                                                 （rc=0）

$ python scripts/verify_feature_package.py .scratch/d4run/release/hello-local-1.zip
... 结论：通过
OK: 1 份包全部通过（清单完整性 + 摘要校验 + 装前子进程预检）                    （rc=0）
```

**本该失败的三条（实机观察）**：

```
① 篡改一个字节（host/factory.py 里 greetings→farewells）
$ python scripts/build_mod_example.py .scratch/pr-report-e2e/tampered --check
自检没过（verification_failed）：这份包装上一样会失败，别发出去。
  问题：校验链拒：size limit or replaced file: ...\tampered\host\factory.py   （rc=1）

② 目标平台不符
$ python scripts/verify_feature_package.py --target-platform linux .scratch/d4run/release/hello-local-1.zip
  问题：清单声明 platforms=['win32']，目标平台是 linux                        （rc=1，0.195 s）

③ 输出已存在（构建入口不该覆盖）
$ python scripts/build_mod_example.py examples/mods/hello-local .scratch/pr-report-e2e/build/hello-local
打不了包：output already exists; choose a new candidate directory              （rc=2，无 traceback）
```

### 5.3 盲审修复：每条的红 → 绿（注入法，改完即还原）

注入方式：把该修复那一笔的对应文件改动**反向应用**（`git show <sha> -- <path> | git apply -R`），
跑守卫，再 `git checkout -- <path>` 还原；还原后 `git status` 干净、`git diff` 为空。

| 修复 | 注入 | 注入后（红） | 还原后（绿） |
|---|---|---|---|
| B1 冻结入口分流 | 撤掉 `packaging/pet_entry.py` 的两条分流 | `tests/test_frozen_entry_routing.py` **5 failed / 5 passed**（chat 入口的 5 条，含真进程握手与真探针回执） | 同文件含在 §5.4 的 133 passed 里 |
| M1 ID 规范形 | 还原 `pet/official_features.py` 的收紧 | `test_official_features.py` + `test_feature_package_import_zip.py` **10 failed / 44 passed**（大小写、末尾点/连字符、`nul`/`con.package`/`COM1.tool`/`lpt9`、官方 ID 变体在路由层不被拒） | 133 passed（§5.4）+ 76 passed（§5.4） |
| M2 失败回装 | 还原 `pet/feature_management.py` 的 `_released_for_apply` | `test_feature_management.py` **1 failed / 26 passed**，红的正是 `test_a_failed_apply_puts_the_old_version_back_in_the_host` | 133 passed（同文件在列） |
| M4 worker 用完即停 | 还原 `pet/proactive.py` 的四处停进程 | `test_proactive_worker_adapter.py -k "stops_the_worker or brings_it_back"` **4 failed / 1 passed** | 76 passed（§5.4） |
| m5 / n1（supervisor） | —（本轮只跑守卫，未做注入） | — | `tests/test_workers_lifecycle.py` **22 passed, 1 skipped** |

### 5.4 聚焦族与崩溃修复：三连绿

```
$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_frozen_entry_routing.py \
      tests/test_official_features.py tests/test_feature_management.py \
      tests/test_feature_packaging_wiring.py tests/test_feature_package_gate.py
133 passed in 55.93s

$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_feature_package_import_zip.py \
      tests/test_feature_package_preflight.py tests/test_proactive_worker_adapter.py
76 passed in 36.14s
```

**崩溃修复（conftest 逐测试收口）** —— 同一组三个文件，同进程连跑三遍（`test_proactive.py`
+ `test_proactive_worker.py` + `test_proactive_worker_adapter.py`）：

```
run1: 125 passed, 3 warnings in 27.47s
run2: 125 passed, 3 warnings in 27.81s
run3: 125 passed, 3 warnings in 31.33s
（还原/注入复核后再跑一遍：125 passed in 26.91s）
```

**同一组注入（撤掉 conftest 那 12 行）后当场复现崩溃**：

```
$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_proactive.py \
      tests/test_proactive_worker.py tests/test_proactive_worker_adapter.py
........................................................................ [ 57%]
..........................Windows fatal exception: access violation
Current thread 0x0000154c (most recent call first):
  File "...\tests\test_proactive_worker_adapter.py", line 203 in _wait_until
  File "...\tests\test_proactive_worker_adapter.py", line 216 in test_adapter_drives_the_real_worker_over_the_default_command
  ...
Segmentation fault    pytest exit=139（无汇总行）
```

这是**原生访问违规**，不是断言失败：98 例通过后崩在第 99 例
（`test_adapter_drives_the_real_worker_over_the_default_command`），与
[`PORT-STATUS.md` §八](modding/PORT-STATUS.md) 记录的崩点一致。收口后同一条命令 4/4 全绿。
崩溃日志留在 `.scratch/pr-report-metrics/_crash_repro.log`；跑完检查无残留 `--worker` 进程（0 个）。

### 5.5 写报告时**新发现**的一个缺陷（已修：行为那一半 `fac40e3`、文档那一半 `584ca57`）

门的**人类可读输出**丢掉了包根级原因：`--bundle-root` 的 `bundle_empty` /
`bundle_stray_entry` / `bundle_duplicate_id` 只在 `--json` 分支出现
（`scripts/verify_feature_package.py:274-287` 把它们收进 `problems`，`main()` 的文本分支只
逐份打印 `format_human(report)`，包根级问题没有一行）。实测（同一个构建输出目录里
`build_mod_example.py` 会产同名的目录 + ZIP）：

```
$ python scripts/verify_feature_package.py --bundle-root .scratch/pr-report-e2e/build
检查：...\build\hello-local（directory） … 结论：通过
检查：...\build\hello-local.zip（zip） … 结论：通过

FAIL: 有包没通过门——构建/发布中止（坏包在界面上多半看不出来，装到用户机器上才知道）。
逐条见上面的「问题」。                                            （rc=1；上面并没有「问题」这一行）

$ ... --json | python -c "…"
ok= False
problems= ['demo.hello-local 在包根里有 2 份（bundle_duplicate_id）：hello-local, hello-local.zip
           ——同一个 owner 两份包，随包携带时以谁为准说不清']
```

即：**退出码是对的（1）、拒绝是对的（m3 的设计如此）、但用户看不到原因**，而 FAIL 那句话还
明确指着不存在的「问题」行。现有用例只覆盖 `--json`
（`tests/test_feature_package_gate.py:182/200/214` 都走 `_json_run`），所以全量套件全绿也抓不到。
**已修（`fac40e3`）**：文本模式把包根级原因一并打出（同一目录现在第一行就是"包根问题：
demo.hello-local 在包根里有 2 份（bundle_duplicate_id）…"，rc 仍为 1），并补了文本模式的
包根拒绝用例；作者文档那一句见 §7.1。

### 5.6 未验项（如实登记，不含"应该没问题"）

| 未验的东西 | 为什么不能自动验（探针/理由） |
|---|---|
| **冻结 exe 形态的入口分流**（B1 的真正目标） | 本机**没有** DLC 分支的 PyInstaller 冻结产物（冻结构建属未排期的打包片）。`tests/test_frozen_entry_routing.py` 用 `sys.executable` 起**真进程**跑入口脚本，用 `sitecustomize` 元路径拦截器证明"没走进桌面 UI 图"——它验的是**分流顺序与实现单源**，验不了 PyInstaller 把 `sys.executable` 指到 exe 后的行为 |
| **host-worker 的真实冻结构建** | `build_mod_echo` / `build_feature_probe_native` 未移植，`--worker-bundle` 那条路在本机无输入可验；`examples/mods/echo-worker` 因此没能进过门 |
| **`<app>/features/` 的产品侧读取** | **还没有读者**（PORT-STATUS §七）——本片只交付"发布载体契约 + 两道门"，没有可验的运行期行为 |
| **三端构建脚本的整段构建** | 需要跑完整 PyInstaller onedir（分钟级、数百 MB 产物）。本轮只跑了它们调用的那道门（§5.2）与 `-FeaturePackages` 的脚本逻辑守卫（`tests/test_feature_packaging_wiring.py`） |
| **人工点按**（真机点"停用/删除/回滚"的三键询问、真机隐藏→恢复、设置页「扩展管理」逐步点按） | 本轮全程 offscreen；草稿门与三键询问由 monkeypatch 驱动，真机交互未点过 |
| **全量套件复跑** | 61 分钟 × 单机（§六 记录的是分支交卷口径），本轮改动只新增一份文档 |
| **m1 / m2 / m4** | 缓做项，见 §七 |

### 5.7 复审修复轮（`584ca57`）：每条的红 → 绿

注入方式与 §5.3 同：把该修复那一笔的对应文件**反向应用**
（`git stash push -- <path>`），跑守卫，再 `git stash pop` 还原；还原后 `git status` 只剩
本轮该有的改动。

| 修复 | 注入 | 注入后（红，原始断言） | 还原后（绿） |
|---|---|---|---|
| N1 重试阶梯 | `git stash push -- pet/feature_management.py` | `test_feature_apply_retry_ladder.py` **1 failed / 1 passed**：`assert '1.0.0' is None`（`Inspection(status='disabled', revision=6, active='1.0.0', pending_transaction='tx-5122…')`——第一段失败后重试自己把事务接受又卡在 `version_in_use`，删除永远做不完） | 该文件 `2 passed in 5.57s` |
| N2 接受后装回 | 同上（同一文件） | 同文件**另一条**：`AssertionError: OperationResult(status='recovery_required', …, reason='startup_load_failed')` / `assert 'recovery_required' == 'awaiting_release'`（宿主被装回打成 fault） | 同上 |
| N3 退出收口 | `git stash push -- pet/workers/supervisor.py pet/workers/proactive_screen_adapter.py` | `test_proactive_worker_adapter.py -k exit_drain` **2 failed**（两条参数各自失败，原始断言 `assert 'ready' == 'stopped'`——收口之后真的又拉起了一个 worker 并完成握手） | `2 passed in 2.82s` |
| M3 补漏 | `git stash push -- docs/modding/README.md` | `test_feature_packaging_wiring.py -k never_says_the_chain_verifies` **1 failed**（README 里"验签"仍在） | 整文件 `35 passed in 3.93s` |

**真链路证据（不是 mock）**：`test_feature_apply_retry_ladder.py` 走的是
`scripts.build_mod_example` 真构建的示例包 + `DialogModHost`/`LocalFeatureRuntime` 真宿主 +
`ModCenterController` 真队列 + `FeaturePackageTransactionService` 真事务层（既有那两条用例
把 `service.apply` 换掉，测不到这两条）。N3 那条起的是真 Python 子进程（慢退 worker 脚本）
跑真关闭阶梯。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts packaging` | `All checks passed!` |
| 聚焦（盲审修复守卫） | `pytest -q tests/test_frozen_entry_routing.py tests/test_official_features.py tests/test_feature_management.py tests/test_feature_packaging_wiring.py tests/test_feature_package_gate.py` | `133 passed in 55.93s` |
| 聚焦（D3/预检/M4） | `pytest -q tests/test_feature_package_import_zip.py tests/test_feature_package_preflight.py tests/test_proactive_worker_adapter.py` | `76 passed in 36.14s` |
| 崩溃族（受影响时序族 3 遍） | `pytest -q tests/test_proactive.py tests/test_proactive_worker.py tests/test_proactive_worker_adapter.py` ×3 | `125 passed` ×3（27.47 / 27.81 / 31.33 s），还原后第 4 遍 `125 passed in 26.91s` |
| supervisor 守卫（m5/n1/M4） | `pytest -q tests/test_workers_lifecycle.py` | `22 passed, 1 skipped` |
| 断言有效性（注入） | 见 §5.3 表（5 组注入，分别 5F/10F/1F/4F） | 每组注入都精确命中对应守卫 |
| 崩溃归因（反向验证） | 撤掉 conftest 收口后跑同一组 | `exit=139`、原生访问违规、崩点第 99 例、无汇总行 |
| 端到端（实机，非 CI） | §5.1 的 `_d3_e2e.py`；§5.2 的打包入口 + `--check` + 门 | `== OK ==`；门正路径 rc=0、三条负路径 rc=1/1/2 |
| 架构红线 | `tests/test_architecture.py`（本片给零 Qt 名单 +25 行登记） | `15 passed in 3.62s` |
| 复审修复轮：静态检查 | `python -m ruff check pet tests scripts packaging` | `All checks passed!` |
| 复审修复轮：新增守卫 | `pytest -q tests/test_feature_apply_retry_ladder.py` | `2 passed in 5.57s` |
| 复审修复轮：`feature_*` 族（12 文件） | `pytest -q tests/test_feature_{apply_retry_ladder,management,package_transactions,package_startup,packaging_wiring,package_gate,package_import_zip,install_state,state_io,version_lease,gating,package_preflight}.py` | `357 passed, 1 skipped in 184.11s`（1 skipped 是本机无 LPAC 沙箱那条既有 fail-closed 守卫） |
| 复审修复轮：`mod_center_*` + `workers_*` 族（9 文件） | `pytest -q tests/test_mod_center_{contracts,controller,end_to_end,routing,ui}.py tests/test_workers_{entry,lifecycle,protocol,source}.py` | `158 passed, 1 skipped in 43.63s` |
| 复审修复轮：proactive 族（5 文件一起跑） | `pytest -q tests/test_proactive.py tests/test_proactive_worker.py tests/test_proactive_worker_adapter.py tests/test_proactive_memory_concurrency.py tests/test_overlay_chat_proactive.py` | `178 passed in 37.84s`（§八 登记的三文件组合访问违规本轮两遍都没复现，见 PORT-STATUS §八 补记；分开单跑也绿：新增文件 37 passed、三文件组合 127 passed、另两个 51 passed） |
| 复审修复轮：断言有效性（注入） | 见 §5.7（4 组注入，分别 1F/1F/2F/1F） | 每组注入都精确命中对应守卫 |
| 全量 | `QT_QPA_PLATFORM=offscreen python -m pytest -q` | **`7739 passed / 18 skipped`（分支交卷口径，未变）**。口径说明：本分支自己的全量记录（D2 片 1 那次是 `7522 passed, 18 skipped`，59 分 08 秒，日志 `.scratch/dlc-fusion/_d2a_fullsuite.log`）加上 D3/D4 与两个修复批新增的用例数；**复审修复轮未复跑全量**（61 分钟 × 单机，本轮按"相关族全绿"口径收口：上面三行共 693 passed / 2 skipped，一次跑完，在同一棵提交树上）。其中 61 分钟那一次在 `tests/test_overlay_app_hosts.py::test_show_balance_uses_overlay_host` 红过一回，已按轮询宽预算修（`cf9e2e6`），隔离/文件内跑均绿 |

**跨平台**：本片无新增平台分支；`platform=sys.platform` 沿既有验签策略，`--target-platform`
把产物平台显式传给门（三端脚本各自传自己的）。新代码零 Qt 名单已登记（`feature_policy.py`
等），`tests/test_architecture.py` 守卫。

## 七、已知限制与后续

### 7.1 本轮登记但不改的 bug（写报告时发现，见 §5.5）

`scripts/verify_feature_package.py` 的文本输出丢失包根级原因（`bundle_empty` /
`bundle_stray_entry` / `bundle_duplicate_id`），FAIL 提示指向不存在的「问题」行；退出码正确。
**已修（`fac40e3`）**：文本模式把包根级原因一并打出，并补了文本模式的包根拒绝用例。
顺带的事实：`build_mod_example.py` 的默认产出（同名目录 + ZIP 在同一输出目录）直接当包根喂给
门会触发 `bundle_duplicate_id`（这是 m3 的设计意图），但作者文档没写"包根每个 owner 只放一份"。
**文档这一半已补（`584ca57`）**：`docs/modding/AUTHORING-HANDBOOK.md` 加"发布根里每个 owner
只放一种形态"，写明门在复制之前就中止构建。实测（本机）：

```
$ python -X utf8 scripts/build_mod_example.py examples/mods/hello-local .scratch/probe-bundle/release/hello-local
created: …\release\hello-local
ZIP: …\release\hello-local.zip          # 打包入口的标准产出就是两份

$ python -X utf8 scripts/verify_feature_package.py --bundle-root .scratch/probe-bundle/release ; echo rc=$?
包根问题：demo.hello-local 在包根里有 2 份（bundle_duplicate_id）：hello-local, hello-local.zip
          ——同一个 owner 两份包，随包携带时以谁为准说不清
FAIL: 有包没通过门——构建/发布中止…                  rc=1
```

### 7.2 PORT-STATUS §八 的缓做项（本轮不改，登记在此）

| 编号 | 问题 | 缓的理由 / 归属 |
|---|---|---|
| m1 | 预检回执没有 nonce，理论上可被同名旧文件顶替 | 回执路径在每次新建的私有临时目录里（`tempfile.TemporaryDirectory`），顶替要先拿到那个目录；收益低于改动面（回执 schema 升版）。归属：探针硬化片 |
| m2 | 预检不可取消（父侧不持有句柄），只能等 `timeout` | 30 s 单次上限已经有界；取消要父侧留句柄 + 事务层接口，与"装前预检要不要并发"一起做。归属：Phase 4B-5 |
| m4 | 构建机在预检阶段执行包代码（`create_host()`），构建机上没有告警/文档 | 门与产品口径一致地**不声称隔离**（`pet/feature_package_preflight.py` 模块 docstring 已写死"不是沙箱"）；缺的是构建脚本侧一句告警。归属：构建脚本文案批次 |
| N4 的行为那一半 | 同名目录 + ZIP 同放一个发布根被判 `bundle_duplicate_id` | 判据本身是对的（m3 的设计意图），所以行为不改；作者文档一句已补（§7.1）。回归面：构建机若把打包产物的两份都拷进发布根，会看到 rc=1 与包根原因（`fac40e3` 起文本模式可见） |
| N5 | 补拉会让 `state_changed` 乱序（迟到事件夹在 `stopping → stopped → starting → ready` 之间） | 订阅者读的是快照（`status_snapshot()` / `state`），乱序不影响它们；要修得给补拉一条"代次"语义（迟到的旧代次事件直接丢），属状态机精修。归属：proactive worker 状态机片 |
| N6 | B1 的守卫在**源码解释器**下跑入口，覆盖不到 windowed 冻结包的 stdio | 需要一份真冻结产物（`build_onedir` 的 windowed exe）才能测，本机没有随包分发的探针 bundle。归属：Phase 4B-5 冻结构建片（与 host-worker 真实冻结构建同批），已同时登记在 PORT-STATUS §八之二 |

完整的编号对应与红→绿证据见 `docs/modding/PORT-STATUS.md` §八（首轮）与 §八之二（复审轮）。

### 7.3 未做的片与边界

- **D5 未做**：本轮不动 `official.ai-chat` / `official.screen-understanding`（官方包安装链
  本身未落地，见 PORT-STATUS §二 Phase 4A/5A）。
- **打包片（未排期）**：Setup 选装器与官方包链、便携模式迁移、产品侧读 `<app>/features/`、
  host-worker 的真实冻结构建（`build_mod_echo` / `build_feature_probe_native`）、
  `build_character_mod_example.py`、LPAC 相关一切。
- **探针硬化片（未排期）**：m1 + 回执 schema 升版。
- **人工验收**：真机点按三键询问、真机隐藏→恢复、设置页「扩展管理」逐步点按，随下一次实机批次。
- **全量口径**：见 §六 那一行的说明（交卷口径 `7739 passed / 18 skipped`，本轮未复跑）。

## 八、风险与回滚

**影响面**：新增能力集中在 MOD 中心的"功能扩展"这条腿（导入/启用/停用/卸载/重装、发布门、
打包入口）；对既有角色资源 MOD、主动识屏、AI 对话、灵动岛**没有改动**。运行期风险面三点：
① 宿主随进程启动装配（~0.15 s，一次）；② 用户显式导入包时才起预检子进程（0.29 s/次）；
③ 用户显式选 worker 前只有既有路径。**没有**新增网络、常驻线程与常驻子进程（§四）。

**开关与配置迁移**：**零新增持久配置键**（`pet/config.py` / `tests/test_config_schema.py`
本片未动）。功能包自己的配置与个人数据在 `feature-data/<owner>/`，属包自己的数据面，
不参与 app 配置迁移。

**回滚步骤**：

1. `git revert` 本分支的两个范围——若要**只回滚本报告覆盖的片**（D1–D4 + 修复批），
   按提交逆序 revert `36ab810..cf9e2e6`（15 个提交）即可；若要回滚整条 DLC 线，
   连同 S1–S4 一起（`1ae0a33..cf9e2e6`）。
2. **落盘残留**：用户装过的功能包留在 `%APPDATA%\<变体>\plugins\<owner>\`（安装状态、版本目录）
   与 `feature-data/<owner>/`；回滚代码后这些目录不再有读者，但**不会**自动清理——
   要清干净需手工删这两个根（这也是设计：个人数据不因代码回滚而丢）。
3. **构建产物**：`<app>/features/` 只在带 `-FeaturePackages` / `--feature-packages` 时出现；
   回滚后不带开关的构建本来就不生成它，无残留。
4. **不变量**：回滚后默认装配仍 fail-closed（`self_check_sandbox_unavailable`），
   官方 owner 仍保留，worker 模式仍不许静默回退——这三条在本片里从未被放宽过，
   回滚只是去掉新增口子。
