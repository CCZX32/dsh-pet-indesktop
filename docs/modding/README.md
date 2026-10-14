# MOD 使用与制作指南（v1）

> **移植基线（2026-10-13，本仓库分支 `dlc/mod-center-port`）**
>
> 本目录移植自上游 DLC 分支的 `docs/modding/`（分支名与基线 SHA 属仓库内工作档案，
> 见 `.scratch/dlc-fusion/PLAN.md`；本目录正文不写外部工具名），**逐字保留**其作者
> 契约文本，只做两件事：改掉指向 DLC 分支才有的文件链接、按本仓库的落地现状写明
> 「哪些已经能跑、哪些还没接」。**本仓库当前只落地了「角色资源」这条腿**——请先读
> 下面的[「移植基线与现状」](#移植基线与现状2026-10-13)，再读各篇教程。
>
> ZIP 导入缺陷的处置口径见同一节（[§四](#四zip-导入探针缺陷2026-10-10--2026-10-13-收口口径)），
> 修复前/后原始输出见 `.scratch/dlc-fusion/S4-HANDOFF.md`。

本页是全套 MOD 文档的入口。先看你是「加 MOD 的人」还是「做 MOD 的人」，再按 MOD 类型跳到对应教程与接口契约。

## 一、我只想加 MOD（使用者）

1. 打开 设置 → 扩展管理，用「导入 ZIP」或「导入目录」选一个完整包（所选目录根必须有 `manifest.json`，别选仓库根或单独的 `videos`）。
2. 新包默认**未启用**；点「启用」后入口与设置立即出现，不必关闭设置。
3. 角色包的「启用」只是加入可选列表，点「使用」才给当前实例换装。

完整步骤、更新 / 停用 / 回滚 / 批量删除、项目目录布局与常见问题：[MOD 使用指南](USER-GUIDE.md)。

> **角色资源包**：ZIP 与目录两条路都可用（`pet/mod_management.py::_materialize`）。
> **功能扩展包（第三方本地包）**：ZIP 与目录都装得上（D2/D3）——显式用户信任 +
> 装前子进程预检，导入后在「扩展管理」里启停；**官方包（`official.*`）**的安装链未落地，
> 本地包声明官方 ID 会被点名拒绝（`pet/mod_center_controller.py::unsupported_package_message`），
> 不是静默失败。

## 二、我想做 MOD（作者）

先按类型选教程，写代码时对照[公共接口](API-V1.md)：

| MOD 类型 | 你得到什么 | 教程 | 本仓库可跑 |
|---|---|---|---|
| 角色素材包（纯内容，不执行代码） | 换角色、替换 / 新增动画 | [角色素材教程](CHARACTER-PACKS.md) | ✅ |
| 台词 / 人格模板 | 只改台词与口吻，不做可卸载功能包 | [台词模板教程](PERSONA-TEMPLATES.md) | ✅（素材侧） |
| 功能扩展 · host-only | 增加菜单与设置，不需要独立进程 | [host-only 样例](HOST-ONLY.md) | ❌ 宿主未接入 |
| 功能扩展 · host-worker | 在独立进程里跑耗时任务 | [Echo Worker 样例](HOST-WORKER.md) | ❌ 宿主未接入 |

四类 MOD 的**字段表、放置位置和接口速查**见 [MOD 制作手册与注意事项](AUTHORING-HANDBOOK.md)——本页只做分流，手册才是完整参考。

## 三、接口文档

- [pet.mod_api.v1 接口基线](API-V1.md)：定义与挂载、菜单与设置协议、自有配置 / 数据、Core 简易 API、WorkerClient 生命周期与边界。**本仓库尚未实现该模块**，本文是待落地契约的权威描述。
- [兼容承诺与影响矩阵](COMPATIBILITY.md)：v1 的稳定边界，以及以后 Core 拆包时哪些做法不用重做。
- 两个官方 DLC 案例（DLC 分支的 `OFFICIAL-DLC.md`）：**AI 1.0.4（host-only）** 与 **识屏 1.0.4（host-worker）** 的生命周期与端口设计参考。本仓库没有 DLC 的独立安装形态，故该篇**未移植**；可对照本仓库的 [PROACTIVE_SCREEN_IMPLEMENTATION_MANUAL.md](../PROACTIVE_SCREEN_IMPLEMENTATION_MANUAL.md) 与 `pet/workers/` 阅读。

## 四、ZIP 导入探针缺陷（2026-10-10 → 2026-10-13 收口口径）

DLC 原文（2026-10-10）报的是「用 ZIP 导入示例功能包报 `worker_probe_failed`、操作未完成，
同一份内容改用「导入目录」正常；角色资源包走 ZIP 正常」。**S4 把这条缺陷拆成两环，逐环给
结论——不要笼统表述为"已修复"**：

| 环 | 结论（2026-10-13） | 依据 |
|---|---|---|
| ① 冻结版 onedir 的密封依赖目录查找 | **已修复** | `pet/frozen_runtime_paths.py`（本仓库新增）+ `pet/workers/screen_entry.py` 首行接线。探针 `_probe()` 的第一步是 `import _dsh_probe_native`；该 `.pyd` 只存在于执行文件自己的 `_internal` 里，安装路径一长 `LoadLibrary` 就以「文件名或扩展名太长」失败 ⇒ 探针恒 77 ⇒ `worker_probe_failed`。**修复前 vs 修复后原始输出见 `.scratch/dlc-fusion/S4-HANDOFF.md`**（同一个 `.pyd`：普通拼写 ⇒ `ImportError: DLL load failed … 文件名或扩展名太长`；扩展拼写 ⇒ 导入成功）。 |
| ② 之上的 LPAC 原生探针沙箱与其 `_internal/feature-probe` 密封 bundle | **本仓库不存在**，且**不是本仓库能修的**；D3 起本地导入走另一条明确的口子 | 该 bundle 由 DLC 的原生构建流水线产出（钉版 PyInstaller 源码 tarball + MSVC + 官方 libsodium + AppContainer/LPAC canary）。本仓库没有也不该凭空造一个"看起来像沙箱"的东西，所以**默认装配仍然 fail-closed**：`FeaturePackageTransactionService` 见 `self_checker.available is False` 即抛 `self_check_sandbox_unavailable`（守卫：`tests/test_feature_package_transactions.py::test_default_selfcheck_fails_closed_without_os_sandbox`，**未改**）。用户**自己挑选**的本地包另走"显式用户信任"（Phase 5A 口径）+ D3 的**装前子进程预检**（`pet/feature_package_preflight.py`）；探针**不是沙箱**，只在拒绝方向有权威。 |

**由此得到的一条可直接照做的结论**：DLC 报告里「目录可以、ZIP 不行」这个差异**在本仓库
没有复现面**——ZIP 与目录在 `preflight_*` 里都被 `files.stage()` 归一成同一个已解包的
`staged_root`，两条路收敛到同一处判定。DLC 自己也记录过"本地非冻结环境无法复现
该差异"，并把 `hello-local`（host-only）的准确 reason 列为待补信息。
**本仓库现状（D3）**：第三方本地功能包的 ZIP 与目录现在都能装（走显式用户信任 + 装前子进程
预检）；官方包与 host-worker 的真实冻结构建仍未做。

顺带补上 DLC 列为"待补信息"的那一项：本仓库给 77 加了**可读的原因**——
`pet/workers/screen_entry.py::sandbox_verdict()` 把前置状态分成
`module_missing` / `module_unusable` / `not_enforced` / `enforced` 四态，77 时往 stderr
写一行有界 JSON `{"schema":1,"kind":"probe_refused","reason":…}`。原先四种缺陷共用一个
没有内容的退出码，正是这条缺陷难以定位的成因。

完整结论见 [实施计划 · 已知未解决缺陷](MOD-CENTER-IMPLEMENTATION-PLAN-2026-10-10.md)
（该篇同样按 S4 口径加了移植基线头）。

## 移植基线与现状（2026-10-13）

本仓库（分支 `dlc/mod-center-port`，基线 `fix/post-integration-and-pr247-251`）把 DLC 的
MOD 中心**分片移植**，落地面如下——判定依据是分支上的六份 HANDOFF
（`.scratch/dlc-fusion/S1a…S3-HANDOFF.md`）：

| DLC 面 | 本仓库现状 | 落点 |
|---|---|---|
| 角色资源包（清单、原子写、启停、更新、回滚、批量删除） | ✅ 已落地并已接入设置页 | `pet/mod_catalog.py`、`pet/mod_management.py`、`pet/mod_center_controller.py`、`pet/mod_center_ui.py`、`pet/settings_mod_domain.py` |
| 包信任（签名 / 清单 / 指纹 / 路径边界） | ✅ 已落地 | `pet/plugins/package_trust.py`、`pet/feature_package_files.py` |
| 安装事务 / 状态机 / 版本租约 | ✅ 已落地 | `pet/feature_package_transactions.py`、`pet/feature_state_io.py`、`pet/feature_version_lease.py` |
| 探针契约（策略 / 结果 / transcript 校验） | ✅ 已落地 | `pet/feature_package_probe.py` |
| 原生探针沙箱（LPAC 启动器 + 密封 bundle） | ❌ 未移植（**本拓扑不做**，见下） | 默认 fail-closed 那一半不变；本地导入走"显式用户信任 + 装前子进程预检" |
| 本地包装前预检（子进程，元信息 + 失败检查） | ✅ 已落地（**不是沙箱**） | `pet/feature_package_preflight.py`（D3） |
| 作者侧打包入口 + 发布前自检 | ✅ 已落地（D4）：构建入口产目录 + ZIP，自检走"清单完整性 + 摘要校验 + 装前子进程预检" | `scripts/build_mod_example.py`、`scripts/verify_feature_package.py` |
| 随包携带功能包的构建门（三端两道门 + `<app>/features/`） | ✅ 接线已落地（D4）；**产品运行期还没有读那个目录的地方**（Setup 选装 / 便携未做） | `scripts/build_{onedir.ps1,linux.sh,macos.sh}`、`docs/ONEDIR_PACKAGING.md` |
| 功能扩展宿主运行时（`pet.mod_api.v1` / `pet/feature_management.py` / `pet/local_package_intents.py`） | ✅ 已落地并已接入 MOD 中心（D2/D3） | `pet/feature_management.py`、`pet/mod_runtime.py`、`pet/mod_menu.py`、`pet/settings_mod_panel.py`、`pet/plugins/{feature_host,feature_packages,package_binding}.py` |
| 官方功能包（`official.ai-chat` / `official.screen-understanding`）的安装链 | ❌ 未落地（官方 ID 在本地导入处按保留 ID 拒绝） | `pet/official_features.py`、`pet/mod_center_controller.py` |
| workers 子进程基础设施 | ✅ 已落地 | `pet/workers/`（protocol / supervisor / launch / proactive-screen worker） |
| 跨进程角色控制通道（`pet/mod_resource_ipc.py`） | ❌ 放弃 | 属 4.4b 淘汰语义；等价物是设置页所属桌宠窗口上的 `on_switch_character` |

### 本地功能包的信任口径（一句话）

**没有 LPAC 原生沙箱**：那个 `_internal/feature-probe` 密封 bundle 要钉版 PyInstaller 源码
tarball + MSVC + 官方 libsodium + AppContainer canary，本仓库没有也不该凭空造一个"看起来像
沙箱"的东西。所以：**默认装配仍然 fail-closed**（无沙箱即拒装，这条纪律一个字没改）；用户
**自己挑选**的本地 ZIP/目录走另一条明确的口子——"显式用户信任"（Phase 5A 的原文口径），
外加 D3 的一道**装前子进程预检**：在另一个进程里把包装一次，回答"装载得起来吗、
`create_host()` 说的 owner 与清单一致吗"。

> 本地 MOD 是你自己选择信任的 Python 代码，与桌宠以相同权限运行；子进程预检只是另一个进程，
> **不是沙箱**。导入即代表你信任它的来源。

探针**只在拒绝方向有权威**（包装不起来、owner 对不上 ⇒ 装之前就拒，状态与版本目录都不动），
说行的那一半仍由宿主按同一套完整校验链（清单完整性 + 摘要 + 版本与身份核对）自己重新回答
——同样是显式用户信任，不是发布者认证。

**因此**：本目录里凡描述「功能扩展」的教程（`API-V1.md` / `HOST-ONLY.md` /
`HOST-WORKER.md` / `AUTHORING-HANDBOOK.md` 的功能扩展部分 / `COMPATIBILITY.md`）
在**第三方本地包（未知 owner、host-only）**这一面上现在可以照着跑一遍（导入 → 启停 →
卸载 → 重装），官方包与 host-worker 仍是**待落地目标**；凡描述「角色素材包」的
（`CHARACTER-PACKS.md` / `PERSONA-TEMPLATES.md` / `USER-GUIDE.md`
的导入与管理部分）**一直可用**。

样例源码在 [`examples/mods/`](../../examples/mods/README.md)：`hello-local`（host-only）、
`echo-worker`（host-worker）、`persona-phrases.json`（台词模板）。它们保留 DLC 的作者侧
源码形态（`mod.json` + `host/`）——**是源码不是包**，要用打包入口打出来：

```bash
python scripts/build_mod_example.py examples/mods/hello-local <输出目录>   # 同时产出目录与同名 ZIP
python scripts/build_mod_example.py <输出目录> --check                     # 发布前自检
python scripts/verify_feature_package.py <包目录或 ZIP>                    # 同一道门，可批量/可 --json
```

`--check` 与 `verify_feature_package.py` 是**同一套判据**：清单完整性（有界路由）+ 摘要校验
（结构 / 兼容性 / 路径边界 / 逐文件摘要）+ **装前子进程预检**。本地包走"显式用户信任"口径，
这道门**不做发布者认证**——`manifest.sig` 存在也只被忽略（报告里给 `signature_ignored`
告警，`trust_status` 如实写 `local_user`）。`echo-worker` 那条
host-worker 路径需要冻结的 worker 可执行（`--worker-bundle`），本机不可验证。

上表只覆盖 MOD 这一面。**要把作者的全部 phase（1 / 2 / 3A / 3B / 3C / 4A / 4B / 5A / 5B /
6 / 7）逐项对照本仓库的落地状态，读 [`PORT-STATUS.md`](PORT-STATUS.md)**——它按作者的 phase
结构写明 ✅ 做到 / ⚠️ 半做 / ❌ 未做、证据落点与没做的原因，也是
[`../plugin-roadmap/`](../plugin-roadmap/) 与 [`../plugin-phase-01-foundation/`](../plugin-phase-01-foundation/)
那批移植件的状态总表。

## 工程入口

[总索引](../INDEX.md) · [制作手册](AUTHORING-HANDBOOK.md) · [实施计划](MOD-CENTER-IMPLEMENTATION-PLAN-2026-10-10.md) ·
[角色素材教程](CHARACTER-PACKS.md) · [MOD 使用指南](USER-GUIDE.md) ·
[移植状态对照](PORT-STATUS.md) · [交付报告（本仓库汇总）](../PR-REPORT-DLC-MOD-CENTER-2026-10-13.md)。
所有命令在仓库根目录执行；推荐独立 Python 虚拟环境，不读取真实用户配置或 Key。

## 实际效果与限制

这是本地 MOD 管理与制作入口，不是联网商店。受信任 Python MOD 不是安全沙箱，只安装可信来源；角色资源不含执行代码。公开的是 v1 薄接口，不是 Core 的全部 Python 模块。**本仓库当前两条腿都在**：角色资源包（一直可用）与第三方本地功能扩展包（D2/D3：导入 → 启停 → 卸载 → 重装），打包与发布前的自检在 D4 补齐（`scripts/build_mod_example.py` + `scripts/verify_feature_package.py`）。**仍未落地的是官方功能包（`official.*`）的安装链、host-worker 的真实冻结构建与 LPAC 探针沙箱**——这三条见 [移植状态对照](PORT-STATUS.md)。
