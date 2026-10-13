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
> **功能扩展包**：本仓库尚未接入宿主运行时，导入会被**如实拒绝**并说明原因
> （`pet/mod_center_controller.py::unsupported_package_message`），不是静默失败。

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
| ② 之上的 LPAC 原生探针沙箱与其 `_internal/feature-probe` 密封 bundle | **本仓库不存在**，且**不是本仓库能修的** | 该 bundle 由 DLC 的原生构建流水线产出（钉版 PyInstaller 源码 tarball + MSVC + 官方 libsodium + AppContainer/LPAC canary）。本仓库没有也不该凭空造一个"看起来像沙箱"的东西。因此功能扩展包导入在本仓库被**更上游**的一道闸门如实拒绝：`FeaturePackageTransactionService` 见 `self_checker.available is False` 即抛 `self_check_sandbox_unavailable`（守卫：`tests/test_feature_package_transactions.py::test_default_selfcheck_fails_closed_without_os_sandbox`）。 |

**由此得到的一条可直接照做的结论**：DLC 报告里「目录可以、ZIP 不行」这个差异**在本仓库
没有复现面**——ZIP 与目录在 `preflight_*` 里都被 `files.stage()` 归一成同一个已解包的
`staged_root`，两条路在本仓库收敛到同一处拒绝。DLC 自己也记录过"本地非冻结环境无法复现
该差异"，并把 `hello-local`（host-only）的准确 reason 列为待补信息。

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
| 包信任（签名 / 清单 / 指纹 / 路径边界） | ✅ 已落地（**未接入宿主**） | `pet/plugins/package_trust.py`、`pet/feature_package_files.py` |
| 安装事务 / 状态机 / 版本租约 | ✅ 已落地（**未接入宿主**） | `pet/feature_package_transactions.py`、`pet/feature_state_io.py`、`pet/feature_version_lease.py` |
| 探针契约（策略 / 结果 / transcript 校验） | ✅ 已落地（**未接入宿主**） | `pet/feature_package_probe.py` |
| 原生探针沙箱（LPAC 启动器 + 密封 bundle） | ❌ 未移植 | 见上表第②环 |
| 功能扩展宿主运行时（`pet.mod_api.v1` / `pet/feature_management.py` / `pet/local_package_intents.py`） | ❌ 未移植 | MOD 中心 `extensions()` 注册表恒空 |
| workers 子进程基础设施 | ✅ 已落地 | `pet/workers/`（protocol / supervisor / launch / proactive-screen worker） |
| 跨进程角色控制通道（`pet/mod_resource_ipc.py`） | ❌ 放弃 | 属 4.4b 淘汰语义；等价物是设置页所属桌宠窗口上的 `on_switch_character` |

**因此**：本目录里凡描述「功能扩展」的教程（`API-V1.md` / `HOST-ONLY.md` /
`HOST-WORKER.md` / `AUTHORING-HANDBOOK.md` 的功能扩展部分 / `COMPATIBILITY.md`）
在本仓库是**作者契约的权威描述 + 待落地目标**，不是"现在就能照着跑一遍"的操作手册；
凡描述「角色素材包」的（`CHARACTER-PACKS.md` / `PERSONA-TEMPLATES.md` / `USER-GUIDE.md`
的导入与管理部分）**现在就可用**。

样例源码在 [`examples/mods/`](../../examples/mods/README.md)：`hello-local`（host-only）、
`echo-worker`（host-worker）、`persona-phrases.json`（台词模板）。它们保留 DLC 的作者侧
源码形态（`mod.json` + `host/`），**打包脚本 `scripts/build_mod_example.py` 未移植**——
本仓库的 MOD 中心按成品包的 `manifest.json` 接入，不提供示例打包命令。

## 工程入口

[总索引](../INDEX.md) · [制作手册](AUTHORING-HANDBOOK.md) · [实施计划](MOD-CENTER-IMPLEMENTATION-PLAN-2026-10-10.md) ·
[角色素材教程](CHARACTER-PACKS.md) · [MOD 使用指南](USER-GUIDE.md) ·
[交付报告（本仓库汇总）](../PR-REPORT-DLC-MOD-CENTER-2026-10-13.md)。
所有命令在仓库根目录执行；推荐独立 Python 虚拟环境，不读取真实用户配置或 Key。

## 实际效果与限制

这是本地 MOD 管理与制作入口，不是联网商店。受信任 Python MOD 不是安全沙箱，只安装可信来源；角色资源不含执行代码。公开的是 v1 薄接口，不是 Core 的全部 Python 模块。**本仓库当前只交付「角色资源」这条腿**，功能扩展侧等宿主运行时与探针沙箱到位后再开。
