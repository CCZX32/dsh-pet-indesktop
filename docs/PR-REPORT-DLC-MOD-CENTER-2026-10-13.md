# PR 报告：MOD 中心与 workers 子进程基础设施（DLC 移植线）

> **基线**：`3ab1048`（Merge PR #254）
> **分支**：`dlc/mod-center-port`　**日期**：2026-10-13
> **范围**：89 处文件变更（新增 55 / 修改 34，`+18791 / −308`，6 个提交）；本报告额外覆盖
> S4 收尾片（工作树内 4 改 4 增）
> **关联**：`.scratch/dlc-fusion/PLAN.md`（移植判定与排期）、`S1b-1/S1b-2/S1c/S2/S3/S4-HANDOFF.md`
> （逐片证据）、[`docs/modding/README.md`](modding/README.md)（作者文档）、
> `docs/INDEX.md` 的「PR 报告存档」

## 一、核心特性

把上游 DLC 分支（旧基线 `45619ce`，overlay 重构之前）中已经实现
但主线只有设计文档的 **MOD 管理中心**与 **workers 子进程基础设施**，按现行拓扑
（overlay 单合成窗、固定身份槽位、D12 单一指令通道、`tests/test_architecture.py` 的退役
IPC 防复活守卫）**分片移植**进来。DLC 不能合并（基线过旧），只能移植——本报告记录移植物
的交付面、判定依据与未验项。

| # | 能力 | 说明 |
|---|---|---|
| 1 | MOD 中心（角色资源） | 包目录 / 资源包管理 / 原子写 / 启停 / 更新 / 回滚 / 批量删除；设置页新增「扩展管理」域 |
| 2 | MOD 中心（请求队列 + UI） | 一条串行操作队列；批量结果汇总；宿主面从 DLC 的跨进程 IPC 换成进程内宿主契约 |
| 3 | 官方功能包信任链 | 验签 / 清单 / 指纹 / 路径边界 / 安装事务状态机 / 版本租约 / 探针契约（**未接宿主**） |
| 4 | workers 子进程基础设施 | `pet-worker/v1` 帧协议 + QProcess 监督器 + 启动租约 + 诊断白名单 |
| 5 | 主动识屏拆入子进程 | 截图 / dHash / 视觉请求搬进 worker；`proactive_screen.execution` 显式二选一，**不许静默回退** |
| 6 | MOD 作者文档与样例 | `docs/modding/*`（10 篇）+ `examples/mods/`（host-only / host-worker 样例） |

**红线 / 不变量**：

1. **不 import 退役 IPC 层**（`pet/mod_resource_ipc.py` / `feature_lifecycle_ipc.py` 一类
   4.4b 淘汰语义）——`tests/test_architecture.py` 是守卫，本线 115 个新文件里 0 处命中。
2. **探针/沙箱缺位一律 fail-closed，不许静默降级**——缺沙箱就不跑探针、缺交接就不执行
   （`self_check_sandbox_unavailable` / 退出码 77）。
3. **`worker` 模式不许静默回退到进程内管线**——三条机器可判规则见 §三。
4. **冻结版构建产物不进提交**；本片跑过的分析/构建产物已清理（§六）。

## 二、修改文件说明

本线共 6 个提交，逐片明细在各片 HANDOFF 的「§一 修改文件说明」（`.scratch/dlc-fusion/`，
**压缩前完整保留**：本仓库 `.gitignore:66` 忽略 `.scratch/`，所以本节把**全部文件清单**
就地列出，评审不必依赖工作区外文件）。

### S1a：设置页域构建器拆分（前置，`1ae0a33`，+205/−119）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/settings_ai_domain.py` | 新增 | AI 域页构建器（从 `modern_settings_dialog.py` 拆出） |
| `pet/settings_automation_domain.py` | 新增 | 自动化域页构建器（同上） |
| `pet/modern_settings_dialog.py` | 改 | 只留接线；行数预算没有余量是拆出的唯一原因 |
| `tests/test_architecture.py` | 改 | 登记拆出模块 |

### S1b-1：MOD 中心逻辑层（`dae38a8`，+1687/−0，纯新增零调用方）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/feature_state_io.py` | 新增 | 状态 IO 原语（安全路径 / 原子写 / 内核锁），事务层的底座 |
| `pet/mod_catalog.py` | 新增 | 角色包目录枚举 + 跨进程失效令牌 |
| `pet/mod_management.py` | 新增 | 托管布局、ZIP/目录导入、原子发布、符号链接/越界拒绝 |
| `tests/test_feature_state_io.py` | 新增 | — |
| `tests/test_mod_catalog.py` | 新增 | — |
| `tests/test_mod_management.py` | 新增 | — |

### S1b-2：MOD 中心 UI + 设置页「扩展管理」域（`e7e32a7`，+1936/−9，17 文件）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/mod_center_controller.py` | 新增 | 串行操作队列 / 结果协议 / 忙等重试阶梯 / 宿主 `extensions()` 注册表 |
| `pet/mod_center_ui.py` | 新增 | 列表 + 多选 + 「更多」菜单；对后端只认鸭子类型契约 |
| `pet/settings_mod_domain.py` | 新增 | 「扩展管理」域整页装配 + `DialogModHost` 宿主面 |
| `pet/modern_settings_dialog.py`、`pet/settings_page_guide.py`、`pet/settings_search.py`、`pet/settings_widgets.py` | 改 | 域导航 / 搜索 / 引导 / 控件接线 |
| `README.md` | 改 | 用户文档新增「扩展管理」一条 |
| `tests/test_architecture.py`、`test_desktop_pet_features.py`、`test_menu_layout.py`、`test_settings_interaction_tabs.py`、`test_settings_page_guide.py`、`test_settings_pet_tabs.py` | 改 | 行数预算与页面矩阵基线更新 |
| `tests/test_mod_center_controller.py`、`test_mod_center_ui.py`、`test_settings_mod_domain.py` | 新增 | — |

### S2：workers 子进程基础设施（`e5dc6cf`，+2779/−0，8 文件）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/workers/__init__.py` | 新增 | 包面（不做顶层再导出，避免拉起 Qt） |
| `pet/workers/protocol.py` | 新增 | `pet-worker/v1` 帧编解码：长度上限、类型白名单、payload 校验 |
| `pet/workers/supervisor.py` | 新增 | QProcess 监督器：hello/心跳/重启阶梯/超时收口（terminate → kill） |
| `pet/workers/launch.py` | 新增 | 启动参数与一次性交接 token（`HANDOFF_TOKEN_ENV`） |
| `tests/test_workers_protocol.py`、`test_workers_lifecycle.py`、`test_workers_source.py` | 新增 | 协议 / 真进程生命周期 / 源码级边界 |
| `tests/test_architecture.py` | 改 | 登记 worker 包 |

### S1c：官方功能包信任链闭包（`aa96b37`，+7949/−33，25 文件）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/plugins/__init__.py`、`pet/plugins/package_trust.py` | 新增 | 验签 / 清单 / 指纹 / 路径边界 / 祖先快照；零 Qt |
| `pet/feature_package_files.py` | 新增 | 有界 `stage()`：ZIP 中央目录先验证再解包；目录↔ZIP 归一 |
| `pet/feature_install_state.py`、`pet/feature_state_io.py` | 新增/改 | 安装账本（revision 乐观并发 + 崩溃恢复） |
| `pet/feature_package_transactions.py` | 新增 | 安装事务状态机（pending → confirmed → 启动确认；任一步失败即回滚） |
| `pet/feature_version_lease.py`、`pet/feature_lifecycle_contract.py`、`pet/feature_package_startup.py`、`pet/feature_startup_contract.py` | 新增 | 版本租约、生命周期契约、启动许可 |
| `pet/feature_package_probe.py` | 新增 | 探针契约：策略序列化 / `ProbeOutcome` / transcript 校验（**沙箱启动器未移植**） |
| `pet/official_features.py` | 新增 | 官方功能 id 与白名单 |
| `pet/mod_center_controller.py`、`pet/mod_center_ui.py`、`pet/settings_mod_domain.py` | 改 | 接回功能扩展侧：控制器只认契约，注册表由宿主给（当前恒空） |
| `requirements.txt` | 改 | 新增 `cryptography>=43.0`（**构建收集验证见 §四与 §七**） |
| `tests/*`（10 个文件） | 新增/改 | 见 `git diff --name-status aa96b37^ aa96b37` |

### S3：主动识屏拆入 worker 子进程（`3daf969`，+4235/−147，29 文件）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/workers/proactive_screen_worker.py`、`pet/workers/proactive_screen_adapter.py` | 新增 | 子进程侧管线 + 宿主侧适配器（5 / 4 处宿主面改动，逐条理由见 S3-HANDOFF §二） |
| `pet/workers/worker_entry.py`、`pet/workers/worker_diagnostics.py`、`pet/workers/screen_entry.py` | 新增 | `--worker` 分流 / 诊断白名单 / 独立安装入口（探针模式） |
| `pet/proactive.py`、`pet/proactive_limiter.py`、`pet/settings_proactive_worker.py`、`pet/proactive_worker_status.py` | 改/增 | 执行位置二选一、限流对齐、设置页接入、状态快照 |
| `pet/image_hash.py`、`pet/http_compat.py` | 新增 | dHash 抽出（阈值语义不变）、HTTP 兼容层 |
| `pet/vision.py`、`pet/config.py`、`pet/app.py`、`pet/__main__.py`、`pet/multi_window_shared.py`、`pet/chat/providers.py`、`pet/modern_settings_dialog.py`、`pet/settings_automation_domain.py`、`pet/settings_default_marks.py`、`pet/workers/__init__.py`、`pet/workers/supervisor.py` | 改 | 路由 / 启动 / 关停 / 接线 |
| `tests/test_proactive_worker.py`、`test_proactive_worker_adapter.py`、`test_workers_entry.py` | 新增 | worker 路径覆盖 |
| `tests/test_proactive.py` 等 5 个 | 改 | 文件级 autouse fixture 把旧路径钉成 `in_process`（否则 worker 模式下会假绿） |

### S4：收尾片（本片，工作树内未提交）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/frozen_runtime_paths.py` | 新增 +142 | **冻结态缺口 #1 补齐**：把执行文件的密封 `_internal` 以 `\\?\` 扩展拼写放进 `sys.path`，让探针的 `_dsh_probe_native.pyd` 在长路径下可加载。端口严格校验（只认可本机盘符的绝对路径），普通拼写已在 `sys.path` 时**就地替换**——依据是本机实测：追加在它后面**无效**（见 §三-3）。 |
| `pet/workers/screen_entry.py` | 改 +68/−20 | 首行接 `activate_frozen_dependency_path()`（DLC 原文次序，参数解析之前）；`sandbox_verdict()` 四态；77 时往 stderr 写一行有界 JSON `probe_refused` 诊断；坏布局**不捕**（构建缺陷应当炸出来）。 |
| `pet/mod_center_controller.py` | 改 +18/−5 | 模块 docstring 的缺陷指针改成**逐环判定**（本片第 1、2 环的结论与依据） |
| `pet/mod_center_ui.py` | 改 +6/−4 | 同上，保持两处口径一致 |
| `tests/test_frozen_runtime_paths.py` | 新增 +196 | 17 条：源码/非 Windows 零副作用、扩展拼写、幂等、就地替换、邻居目录/不同盘/UNC/设备命名/盘符相对/`.` `..` 段全拒绝 |
| `tests/test_workers_entry.py` | 改 +86/−4 | 探针四态诊断、`activate_frozen_dependency_path` 的接线次序、坏布局不吞 |
| `docs/modding/*`（10 篇） | 新增 +~950 | DLC 作者文档逐字移植 + 统一移植基线头 + 死链改指（**未移植篇改指本仓库对应文档**）+ **外部工具名擦除**（正文不得出现上游 DLC 分支名里的外部工具名——`tests/test_desktop_pet_features.py::test_product_copy_has_no_external_brand_reference` 会扫 `docs/` 下的 `.md` 并判红；分支名/SHA 一律指到 `.scratch/dlc-fusion/PLAN.md` 这份仓库内工作档案）；ZIP 缺陷章节改成 S4 口径 |
| `examples/mods/*`（11 个文件） | 新增 +~300 | `hello-local`（host-only）、`echo-worker`（host-worker）、`persona-phrases.json` |
| `docs/PR-REPORT-DLC-MOD-CENTER-2026-10-13.md`、`docs/INDEX.md` | 新增/改 | 本报告与索引登记 |

### 未改动（看起来相关但故意没动）

- `pet/overlay_shell.py` / `pet/overlay_settings_command.py`：DLC 的 `mod_core` 宿主面改造
  按现行 overlay 拓扑**不需要**改——MOD 中心的宿主面收窄成「设置页所属桌宠窗口」
  （`DialogModHost`），换装复用已有的 `on_switch_character` 入口。
- `pet/island_segments.py` / `pet/island_extension_host.py`：灵动岛保持**唯一数据型第三方
  入口**，不与 MOD 中心合并清单（PLAN.md 的取舍判定）。
- `pet/mod_resource_ipc.py` / `feature_lifecycle_ipc.py`：**不移植**（4.4b 淘汰语义）。
- 三个构建脚本（`build_onedir.ps1` / `build_linux.sh` / `build_macos.sh`）：本片给出
  cryptography 收集的**实测证据**后判定**无需改动**（§四）。

## 三、实现要点

1. **跨进程 IPC → 进程内宿主契约**。DLC 的 MOD 中心靠 `pet/mod_resource_ipc.py` 问主进程
   「谁在用这个包」「把这只宠换到这个角色」。本仓库没有（也不该复活）那条通道，等价物是
   设置页所属桌宠窗口上的 `on_switch_character`。控制器因此只认**契约**：宿主给
   `live_usage()` / `use_resource()` / `catalog_changed()` / `extensions()`，注册表由宿主提供
   （当前恒空 ⇒ 「功能扩展」这一格不出现，导入功能扩展包给一句能照做的拒绝语）。

2. **「使用」不能在设置页当场执行**。换角色会**重建**那只桌宠窗口，而设置窗是它的
   **子窗口**——本机实测（offscreen / Qt 6）父窗 `deleteLater()` 之后子对话框
   `shiboken6.isValid` 即为 False，当场换装等于把设置窗一起销毁。所以 `use_resource()`
   只记下请求，等 `finished` 再执行。

3. **冻结版探针路径：为什么必须"就地替换"而不是"追加"**。这是本片唯一一处**有意偏离**
   DLC 原文的地方，偏离由实测驱动（Windows 11 / Python 3.13.7）：目录总长超过 MAX_PATH 时，
   FileFinder 的 `stat` 会**成功**（于是它认定"模块就在这里"），随后 `LoadLibrary` 才以
   `ERROR_FILENAME_EXCED_RANGE` 失败，而 importlib **不会**因为加载失败退到后面那条 path
   条目。实测矩阵（同一个 `.pyd`，目录长 267 字符）：

   | `sys.path` 内容 | 结果 |
   |---|---|
   | `['plain']` | `ImportError: DLL load failed …: 文件名或扩展名太长。` |
   | `['plain', 'extended']` | **同样失败**（追加等于没改） |
   | `['extended', 'plain']` | 导入成功 |
   | `['extended']` | 导入成功 |

   所以 `activate_frozen_dependency_path()` 在普通拼写已在 `sys.path` 里时**就地替换**它，
   缺席时才追加。PYZ 优先级不受影响——冻结版的 `PyiFrozenFinder` 在 `sys.meta_path` 上，
   与 `sys.path` 顺序无关。

4. **77 不再是一个没有内容的退出码**。原先「`_dsh_probe_native` 缺席」「模块在但说沙箱
   没生效」「导入/调用炸了（缺 DLL）」三种缺陷共用一个 77，现场只剩一句
   `worker_probe_failed`——这正是 DLC 把 `hello-local` 的准确 reason 列为"待补信息"的原因。
   现在 `sandbox_verdict()` 分开四态，77 时往 stderr 写一行有界 JSON。

5. **不许静默回退**（S3 的核心纪律，三条机器可判规则）：`worker` 模式下 `_worker_capture`
   **永不**被调用（故障时也不）；故障只写 `_worker_fault` 并停派发，**不改**
   `_execution_mode`；清故障只有「supervisor 重启阶梯把 worker 拉回 ready」或「用户显式改
   执行位置」两条路。`tests/test_proactive.py` 的文件级 autouse fixture 把执行位置钉成
   `in_process`——不钉的话那些 `monkeypatch.setattr(watcher, "_worker_capture", …)` 的用例
   在 worker 模式下会变成**恒真**（假绿）。

## 四、性能分析

**方法（可复现）**：环境 `Windows 11 / Python 3.13.7`，工作区 `D:/dsh-pet-wt-dlc`。

### 4.1 本片（S4）改动的成本

| 指标 | 实测 | 归属 |
|---|---|---|
| `activate_frozen_dependency_path()` 源码运行开销 | 1 次 `sys.platform != "win32"` 判断后立即返回；`pytest -q tests/test_frozen_runtime_paths.py` 17 条 **1.24 s**（含 17 次进程内 fixture） | 新增路径，**每次 worker 进程启动 1 次** |
| 冻结版下实际工作 | 1 次 `ntpath` 字符串比对 + 至多 1 次列表元素替换（O(len(sys.path))，实测 `sys.path` 长度量级 10¹） | 新增路径，每进程 1 次 |
| 77 诊断行 | ≤512 字节的一次 stderr 写，**只在探针前置条件不成立时**发生（生产正常路径不发生） | 新增路径，故障才触发 |
| 稳态开销变化 | **0**：游戏/桌宠主循环没有被改动的代码路径 | — |
| 新增系统调用 / 网络 / 磁盘 / 线程 | **0**（纯 `sys.path` 列表操作 + 一次 stderr 写） | — |
| 内存增长 | **0**（不缓存、不注册回调） | — |

### 4.2 本线各片的实测数字（逐片引用其 HANDOFF §五）

| 片 | 关键实测 | 落点 |
|---|---|---|
| S1b-2 | MOD 中心列表构建 / 操作队列的 100 包 × 5 次批量删除耗时 | `S1b-2-HANDOFF.md` §五 |
| S1c | 安装事务的稳态成本、锁竞争下的重试阶梯次数 | `S1c-HANDOFF.md` §五 |
| S2 | **真 worker 冷启动中位 267.1 ms**；握手默认值由此定 | `S2-HANDOFF.md` §五 |
| S3 | worker 常驻 **24.9 MB RSS**、两侧合计 ≲0.4% 单核；先兆气泡晚约 **40 ms** | `S3-HANDOFF.md` §五 |

### 4.3 cryptography 冻结收集（本片 task 3，实测）

构建脚本的 `--collect-all` 名单里没有 `cryptography`，S1c 把"冻结包收集未验证"留给了本片。
用 PyInstaller 的 **Analysis**（只建模块图，不落盘、不复制二进制）在自己的构建机上量了四组
样本，参数取 `scripts/build_onedir.ps1` 的相关子集（entry 相同、`pathex`/`excludes` 相同、
`--collect-all` 名单相同）：

```bash
python .scratch/dlc-fusion/s4/_crypto_control.py    # 四组对照，56 s
python .scratch/dlc-fusion/s4/_crypto_collect.py    # 完整入口 pet_entry.py，160 s
```

| 样本 | `cryptography` 模块 | `_rust.pyd` | 图规模 |
|---|---|---|---|
| 空入口（对照） | **0** | 否 | 123 |
| `import pet.plugins.package_trust` | **33** | 是 | 163 |
| `import pet.feature_package_transactions` | **33** | 是 | 186 |
| 空入口 + `--collect-all keyring` | **54** | 是 | 1661 |
| **完整入口 `packaging/pet_entry.py`（= 真实 webm-chat 构建）** | **54** | 是 | 2579 |

**结论**：① `hook-cryptography.py` 被处理、`pyi_rth_cryptography_openssl` 运行期 hook 被
包含、`cryptography/hazmat/bindings/_rust.pyd`（9.9 MB）进 `binaries`——**PyInstaller 会带上
cryptography，无需新增 `--collect-all` / `hiddenimport`**。② 静态分析**跟随惰性 import**
（`_valid_signature` 函数体内的 `from cryptography…` 也被收进图）——这是关键，因为该依赖
只在「签名包」这条路上用到。③ 但完整入口里 `pet.plugins.package_trust` **不在模块图内**
（`watched_present = false`）：真实现代的 cryptography 是从 `--collect-all keyring`
的 SecretService 后端链**捎带**进来的。④ 用量：`_rust.pyd` 的 PE 导入表实测为
`advapi32 / bcryptprimitives / crypt32 / kernel32 / ntdll / python3 / user32 / vcruntime140 /
ws2_32`——**含 `user32.dll`**，与 DLC 上游记录的"Windows 轮会连带拉起 USER32"一致（这也是
DLC 在冻结版另挂 libsodium 后端的原因）。**影响面**：`_rust.pyd` 只被探针/信任链用，而
`build_screen_worker.py` 的 "no USER32/GDI32/OLE32" 约束只针对**探针 bootloader**，不针对
`.pyd`，故本仓库现状不构成红线冲突；但「无头 worker 不许拉 USER32」若将来扩到 `.pyd`，
这条就是第一嫌疑。

## 五、实机运行记录

**本机真实环境**：Windows 11 / Python 3.13.7 / PySide6（`QT_QPA_PLATFORM=offscreen`），
工作区 `D:/dsh-pet-wt-dlc`。

### 5.1 根因/前提的现场复现（ZIP 探针缺陷第①环）

复现对象是**本地真实扩展模块**（`shiboken6/Shiboken.pyd` 整目录拷贝）放到长度超过 MAX_PATH
的目录里，实测 Windows 的加载器语义：

```
$ python .scratch/dlc-fusion/s4/_repro_longpath.py     # 原始输出（节选）
plain len = 267 | extended len = 271
BEFORE  plain    -> ImportError: DLL load failed while importing Shiboken: 文件名或扩展名太长。
AFTER   extended -> IMPORT OK
```

这就是「探针找不到 `_dsh_probe_native.pyd`」的机制本体：`LoadLibrary` 在长路径下直接失败
（`ERROR_FILENAME_EXCED_RANGE`）。修复前的 `screen_entry` 把它吞成
`sandbox_enforced() is False`，于是探针恒 77、上游只看到 `worker_probe_failed`。

### 5.2 用户可见行为的确认

- **角色资源包**：ZIP / 目录两条导入路径在 `pet/mod_management.py::_materialize` 归一后
  同一套原子发布，是 S1b-1/S1b-2 的实机面（本轮未回归重跑 GUI，见 §七未验项）。
- **功能扩展包**：本仓库导入会被如实拒绝并给一句能照做的话
  （`unsupported_package_message`），**不是**静默失败。这是本片**有意保留**的行为——见 §三-1。
- **探针 77 的原因现在可读**（新增能力，实机输出）：

```
$ QT_QPA_PLATFORM=offscreen python -m pytest tests/test_workers_entry.py -q -k screen_entry
............................                                             [100%]
（用例断言 stderr 上的：{"kind": "probe_refused", "reason": "module_missing", "schema": 1}）
```

### 5.3 边界与失败路径

- **本该拒绝的**：`tests/test_frozen_runtime_paths.py` 里 7 种非法布局（相对路径 / UNC /
  设备命名空间 / 盘符相对 / 邻居目录 / 不同盘 / 含 `.` `..` 段）全部抛
  `ValueError("frozen_runtime_layout")`，且断言 `sys.path` **一字未动**。
- **本该拒绝的**：`tests/test_workers_entry.py::test_a_broken_frozen_layout_is_not_swallowed`
  ——坏布局抛错，**不**降级成 77。
- **本该拒绝的**：`test_default_selfcheck_fails_closed_without_os_sandbox` —— 没有 OS 沙箱
  时功能包安装被拒（`self_check_sandbox_unavailable`）。

### 5.4 无法自动验证的能力（为什么不能自动）

- **真实冻结版探针沙箱**：本仓库**没有**这条构建流水线（DLC 侧需要钉版 PyInstaller 源码
  tarball + MSVC + 官方 libsodium 归档 + AppContainer/LPAC canary）。排查证据：`grep -rn
  "feature-probe\|PROBE_BUNDLE" scripts/ pet/ tests/` 结果为空——本仓库既没有
  `_internal/feature-probe` 的产出步骤，也没有 `PROBE_BUNDLE_MANIFEST_SHA256` 这份钉版策略。
  **结论不作为"已修复"**：本片修的是它下面那层**可移植**的路径查找，沙箱本身按 §七列为未完成。
- **真模型侧的视觉报文差异**（S3）：本机没有可用视觉 API Key，端到端用的是本地 HTTP 端点
  （真 `urllib` + 真 TLS 上下文 + 真 JPEG base64 载荷）。
- **POSIX 主动识屏**：`vision.foreground_window_info()` 在非 Windows 恒返回 None，该功能
  本就仅 Windows。
- **打包后的入口形态**（S3 遗留 #5）：`--worker` 分流用 `sys.executable --worker <id>`；
  本机只验了源码运行，打包入口是否仍是 `pet.__main__` 未验（见 §七）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet/ tests/` | **All checks passed!** |
| S4 聚焦 | `pytest -q tests/test_frozen_runtime_paths.py` | **17 passed**（1.24 s） |
| S4 聚焦 | `pytest -q tests/test_workers_entry.py` | **19 passed**（3.28 s） |
| S4 聚焦 | `pytest -q tests/test_workers_entry.py -k screen_entry` | **28 passed** |
| 纪律门 | `pytest -q tests/test_architecture.py tests/test_pr_report_discipline.py` | **146 passed**（3.37 s） |
| 全量 | `python -m pytest -q` | 见 `.scratch/dlc-fusion/S4-HANDOFF.md` §四（跑前/跑后 sha256 核对交付文件） |
| 冻结交付文件核对 | `sha256sum -c .scratch/dlc-fusion/_s4_frozen_hashes.txt` | 见 S4-HANDOFF §四 |
| 冻结收集验证 | `python .scratch/dlc-fusion/s4/_crypto_control.py` / `_crypto_collect.py` | 见 §四-4.3 |
| 长路径机制复现 | `python .scratch/dlc-fusion/s4/_repro_longpath.py` | 见 §五-5.1（before/after） |

## 七、已知限制与后续

**本片未完成 / 未验**（逐条给触发条件）：

1. **LPAC 原生探针沙箱未移植** ⇒ 功能扩展包在本仓库不可安装（会被上游闸门如实拒绝）。
   要开这一格，需要一条独立的原生构建片（钉版 PyInstaller 源码 + MSVC + libsodium 归档 +
   AppContainer canary），不是本仓库能在当前机器上验证的事。
2. **`screen_entry` 生产调用方仍不存在**（S3 遗留 #1）：它现在是 fail-closed 且无人调用的
   入口。要么随功能扩展宿主一起接上，要么在下一次消融式审查（`AGENTS.md` §16）判定删除。
3. **cryptography 在完整构建里是"捎带进来"的**：真实现代 `pet.plugins.package_trust` 不在
   模块图内，cryptography 来自 `--collect-all keyring` 的后端链。一旦有人把信任链接进宿主，
   PyInstaller 会**自动**收集（已实测），但**no-chat 变体排除了 keyring**，那时就得靠静态
   分析这条腿——建议补一条**条件构建门**（存在 `pet.plugins.package_trust` ⇒ 必须有
   `cryptography` 与 `_rust.pyd`），本轮未做。
4. **冻结版（PyInstaller）实跑未做**：本片只跑了 PyInstaller 的 Analysis；真构建会把
   `dist-onedir` 写到仓库根，本片按"不污染工作树"的纪律未跑。
5. **`worker` 一旦拉起就活到"执行位置切换 / 进程退出"**（S3 遗留 #11，**待拍板**）：关闭
   「主动识屏」不释放那 ~25 MB。代价已实测登记。
6. **真实视觉服务、POSIX 主动识屏、打包版 `--worker` 入口**未验（§五-5.4）。
7. **`docs/modding` 的功能扩展篇是"待落地契约"**，本仓库只交付角色资源这条腿；每篇都加了
   统一的移植基线头，`README.md` 有逐项对照表。

## 八、风险与回滚

- **影响面**：本线新增 55 个文件、改 34 个；`pet/workers/` 与 MOD 中心是新增域，
  对既有桌宠/聊天/岛功能是**加法**。S3 触碰了 `pet/proactive.py` 与设置页，风险最高，
  已按并发/生命周期档做了独立静态审查 + 真进程测试（见 S3-HANDOFF）。
- **新增持久状态**：`proactive_worker_status.json`（≤4 KiB、原子写、只在状态变化时写；
  S3-HANDOFF §六-6/§六-10 有写入时机核实）。`config.json` 无新增键（执行位置是
  `proactive_screen.execution`，属既有域的既有键新增取值）。MOD 中心的托管目录
  （`mod-versions/`、`mod-staging`、`mod-disabled/`、`mod-catalog.revision`）随首次导入产生。
- **回滚**：`git revert` 本分支的 6 个提交即可——代码是加法，无不可逆迁移；但**已导入的
  MOD 托管目录不会自动清理**，需要手工删 `data/` 下的 `mod-*` 目录（用户数据
  `feature-data/` 与个人配置按设计保留）。
- **不变量**：`tests/test_architecture.py` 全程绿（146 passed 含该文件），退役 IPC 层
  没有被本线任何新文件 import。
