# 小包接线：拖文件解读路由 + MOD 中心官方包装卸入口

> 分支：`dlc/mod-center-port`；阶段 1/2 报告见
> [`PR-REPORT-RESOURCE-HARD-GATE-2026-10-17.md`](PR-REPORT-RESOURCE-HARD-GATE-2026-10-17.md) /
> [`PR-REPORT-PHASE2-PLUGIN-KERNEL-2026-10-17.md`](PR-REPORT-PHASE2-PLUGIN-KERNEL-2026-10-17.md)。

## 一、修改文件说明

### 新增文件（`wc -l`）

| 文件 | 行数 | 改了什么 / 为什么 |
|---|---:|---|
| `pet/file_interpret_router.py` | 53 | 拖文件解读选路：包聊天窗至少开着一个且包可接收 → 包解读器；否则内置。持有两个 offer 与开窗计数，不 import Qt。 |
| `pet/official_package_source.py` | 145 | 官方包来源解析：显式 `PET_OFFICIAL_PACKAGE_ROOT`、冻结态 `<exe>/features/`、源码态 `<data>/official-packages/`（按需调用 `scripts/build_{screen,ai_chat}_package.py`）。三态 `found/absent/invalid` + 可照做的原因。 |
| `tests/test_file_interpret_router.py` | 78 | 包窗开/关、两个窗口、缺包 offer、清空计数、重复 close。 |
| `tests/test_official_package_source.py` | 70 | 未知 owner、显式根目录/ZIP、absent 不构建、源码态构建缓存、冻结态随包目录与缺失提示。 |
| `tests/test_official_feature_install.py` | 76 | 真 `LocalFeatureRuntime`：官方包安装 → 启用 → 卸载；无来源时如实拒绝。 |

### 修改文件（`git diff --numstat`）

| 文件 | +/− | 改了什么 / 为什么 |
|---|---:|---|
| `features/ai-chat/host/runtime_mount.py` | +70/−0 | 包窗开/关登记到 Core 路由（Close 事件过滤器，不依赖 `WA_DeleteOnClose`）；`file_interpret_offer` 惰性创建包的解读器；`close()` 清空路由与控制器。 |
| `pet/ai_bindings.py` | +12/−0 | 进程级拖文件路由注册/解析（`register_file_interpret_router` / `file_interpret_router`）。 |
| `pet/app.py` | +132/−6 | 创建路由并注册；legacy 建窗传入路由；overlay 的内置解读器挂到路由；退出时摘除路由。另含阶段 2 的插件 Registry 装配（同一文件的累计 diff）。 |
| `pet/window_optional_services.py` | +8/−3 | `install_file_interpreter(router=None)`：有路由时把内置 offer 挂上去，保留旧直连路径。 |
| `pet/feature_management.py` | +57/−0 | `official_source` / `official_packages`（按 active 判定未安装）/ `install_official` / `uninstall_official` / `set_official_enabled`。复用既有事务与宿主链。 |
| `pet/settings_mod_domain.py` | +18/−0 | `DialogModHost.official_packages` / `install_official` 转发；宿主没接入时如实空表/抛错。 |
| `pet/mod_center_controller.py` | +61/−1 | `install_official` 动作；未安装官方包行；结果回到 GUI 线程后再 `connect_extensions`。 |
| `pet/mod_center_ui.py` | +9/−0 | 未安装官方包行显示「安装」按钮；其余行交互不变。 |
| `tests/test_ai_package_host.py` | +23/−0 | 包窗打开 → 路由走包；关窗 → 计数归零。 |
| `tests/test_file_eater.py` | +3/−1 | Spy 窗口接受 router 参数；断言 legacy 建窗接上 Core 路由。 |

## 二、性能分析

环境：Windows 11，Python 3.12.10，16 核，`QT_QPA_PLATFORM=offscreen`。

```text
resolve_official_package(explicit found): 0.1 ms 级（单次目录 stat）
源码态首次构建 AI 包（含验签）:            ~1 s 级（test_official_package_source 6 条 1.02s，含一次构建）
拖文件路由一次选路:                        纯函数，纳秒级（两个可调用对象 + 整数计数）
MOD 中心未安装官方包行:                    固定 2 个 owner，一次 list 遍历
```

- **稳态开销**：每次拖文件只多一次 Python 调用；每次 MOD 中心刷新多遍历 2 个官方 owner（无磁盘 I/O，除非打开“安装”）。
- **新增路径成本与频率**：官方包首次安装才解析来源；源码态没有缓存时才构建一次（写 `<data>/official-packages/`）；冻结态只做目录 stat。安装/启用/卸载复用既有事务链，不新增后台线程。
- **新的系统调用 / 网络 / 磁盘 / 线程**：新增的是构建时的文件写入（一次性）与目录 stat；无网络、无新增常驻线程。
- **内存**：路由对象只持两个引用；来源解析返回 dataclass，不缓存包内容。

## 三、实机运行记录

```text
$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q -p no:randomly \
    tests/test_file_interpret_router.py tests/test_file_eater.py tests/test_file_interpret.py \
    tests/test_ai_package_host.py
70 passed in 5.86s

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q -p no:randomly \
    tests/test_official_package_source.py
6 passed in 1.02s

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q -p no:randomly \
    tests/test_official_feature_install.py
2 passed in 2.77s

$ .venv/Scripts/python.exe -m ruff check pet tests scripts
All checks passed!
```

- **真实包链**：`test_official_feature_install` 用真 `LocalFeatureRuntime` + 真事务链 + 真 `build_package`（识屏包），完成安装 → 启用 → 卸载；不是 mock 管理器。
- **包窗口路由**：`test_ai_package_host` 打开真包聊天窗，断言 Core 路由计数；关窗后计数归零。
- **未做人工桌面验收**：本会话没有可交互桌面；「从设置页点安装 → 看列表状态」「真拖文件到桌宠」的人工记录仍列为本片未验证项。机器判据覆盖真实 Qt 控件、真实包构建与真实事务链。
- **全量分片门**：见提交说明与 `.scratch/stage1-full-shards-3.log`。

## 四、边界与未做

- 官方包来源只做**本地**：随包 `features/` 或源码态构建缓存；不做在线下载、不让用户任选目录（`PET_OFFICIAL_PACKAGE_ROOT` 是开发/测试覆盖）。
- 拖文件路由默认「包窗开着走包」；包停用/卸载/解析失败回落内置。永远只弹一个确认。
- 未做包内 AI 聊天 UI 与内置 UI 的逐项对齐（PORT-STATUS §九的未做项）。
- 未做冻结产物上的真实安装（阶段 4）。

## 五、决策点

1. 拖文件路由策略若维护者要「永远内置」或「双入口可选」，改 `pet/file_interpret_router.py` 的 `__call__` 即可；当前默认已写进 PORT-STATUS。
2. 官方包是否允许在线下载/用户选目录，属阶段 4/5A 的分发决策。
