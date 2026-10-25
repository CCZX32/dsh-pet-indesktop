# petcore P5 收口报告（2026-10-25）

> **基线**：`3f2155fd`（摸头互动交付提交）
> **分支**：`feat/petcore-vpet-architecture`  **日期**：2026-10-25
> **范围**：petcore 实现、petcore 测试、必要文档；未修改旧 `pet` 实现，未上传 Release。

## 一、核心特性

本轮一次性实现 P5 的五个代码域：灵动岛 P5-a2、按宠物 slot 的点击显示余额、菜单/设置图标与下拉框几何修复、性能治理与可测量计数、检查更新与冻结 Windows 安装版 Core 自更新边界。余额的左键、右键和灵动岛刷新共用一个异步单飞 presenter；更新服务只写配置目录缓存，源码运行不会替换开发目录。

| # | 能力 | 结果 |
|---|---|---|
| 1 | 灵动岛 P5-a2 | 已实现：停靠、位置恢复、固定模板宽度、展开卡片、余额、消息队列、第三方段、折叠停采样、刷新/设置/清除消息、桌宠几何避让和可取消反馈。 |
| 2 | 点击显示余额 | 已实现：`click_show_balance` 默认关闭、按 slot 保存；左键、右键、灵动岛入口共享 `BalancePresenter`，支持缓存、单飞、失败原因和迟到结果拒收。 |
| 3 | UI 裁切 | 已实现：菜单/托盘/子菜单显式 icon size 与 icon 列宽；设置导航行高与 icon size；QComboBox 按字体度量为文字和箭头槽留安全边距。 |
| 4 | 性能治理 | 已实现：指标采样不快于 1 Hz，隐藏/折叠/关闭立即停采样，聚合 UI 更新、缓存、网络、磁盘和活动 worker 计数；有 15 秒预热、60 秒采集、3 次实测。 |
| 5 | 更新与自更新 | 已实现：HTTPS trusted host、manifest ETag/cache、镜像回退、Range/断点、取消、大小/SHA-256 校验；只有 frozen Windows 启动独立安装器，源码/非 Windows 明确拒绝原地替换。 |

**红线 / 不变量**：不修改旧 `pet`；不把 API key 写入配置、日志、异常或灵动岛；不使用全局 Qt monkey patch；不新增长驻线程；不把 GPU/FPS 不可用伪造成 0；不把源码运行误标为可自动安装；不上传 Release、不覆盖现有安装。

## 二、修改文件说明

以下是本轮收尾后的 `git diff --numstat` 快照。新增文件按工作区实际行数列出；最终复核命令为 `git diff --numstat` 与 `git diff --check`。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `petcore/account/__init__.py` | +2/−1 | 导出余额 presenter，保持账户域公共入口。 |
| `petcore/account/presenter.py` | +127/−0（新增） | 按 slot 单飞、缓存、取消、generation 和 UI 回调边界。 |
| `petcore/performance.py` | +56/−0（新增） | 无 Qt 的聚合性能计数器与 `PerformanceSnapshot`。 |
| `petcore/update/__init__.py` | +13/−0（新增） | 更新模型/服务公共导出。 |
| `petcore/update/model.py` | +167/−0（新增） | manifest、资产镜像、版本比较和字段安全解析。 |
| `petcore/update/service.py` | +456/−0（新增） | HTTPS/host 校验、ETag、缓存、断点、Range、取消、摘要校验及 frozen Windows 安装器条件。 |
| `petcore/cli.py` | +45/−0 | `update check/download/status` 与 `--check` 更新诊断。 |
| `petcore/config.py` | +5/−1 | `click_show_balance` 默认值和按 slot 归一化；修正 GPU/FPS 能力口径注释。 |
| `petcore/island/segments.py` | +40/−3 | SegmentRegistry 第三方段注册、释放、未知/迟到快照拒绝。 |
| `petcore/net/http.py` | +13/−0 | 更新下载的有界响应、状态/Range 读取支持。 |
| `petcore/platform/netmon.py` | +2/−0 | 采样次数与 1 Hz 约束接入运行时计数。 |
| `petcore/platform/sysmon.py` | +4/−2 | CPU 采样计数与 GPU/FPS unavailable 边界说明、现有不可用错误边界接入。 |
| `petcore/ui/app.py` | +213/−2 | CoreHost 统一余额/更新服务、slot 路由、generation、更新下载中/取消状态、消息和退出取消。 |
| `petcore/ui/island.py` | +258/−10 | P5-a2 岛屿布局、卡片操作、余额/消息/第三方段、反馈、折叠停采样和避让；增加可选 GPU/FPS snapshot 接缝，不创建第二采样线程。 |
| `petcore/ui/menu_actions.py` | +14/−0 | 显示余额/检查更新菜单动作与动作处理。 |
| `petcore/ui/menu_model.py` | +3/−0 | 菜单/子菜单显式图标度量与父对象。 |
| `petcore/ui/menu_style.py` | +4/−4 | 菜单 icon 列宽、padding、行高，避免图标和文字相互遮挡。 |
| `petcore/ui/pet_window.py` | +13/−0 | 左键点击余额请求，保留原点击动画/音效。 |
| `petcore/ui/settings/coverage.py` | +2/−0 | 新菜单动作的设置覆盖登记。 |
| `petcore/ui/settings/dialog.py` | +23/−1 | 设置导航 icon size、行高及 QComboBox 字体度量安全宽度。 |
| `petcore/ui/settings/page_about.py` | +68/−0 | 当前版本、检查/下载/安装状态、下载中取消和诊断操作。 |
| `petcore/ui/settings/page_api.py` | +16/−0 | 点击显示余额开关、状态、刷新和错误反馈。 |
| `petcore/ui/settings/style.py` | +15/−0 | QComboBox 文字/箭头/下拉项独立空间。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---:|---|
| `tests/test_petcore_balance.py` | +85/−0（新增） | slot 隔离、缓存、单飞、取消、错误和迟到结果。 |
| `tests/test_petcore_island_p5.py` | +96/−0（新增） | 余额、消息、第三方段、按钮、GPU/FPS unavailable 及可选真实 probe snapshot。 |
| `tests/test_petcore_menu_icons.py` | +49/−0（新增） | 菜单 icon size、QSS 图标列空间和设置导航 icon。 |
| `tests/test_petcore_performance.py` | +23/−0（新增） | snapshot 字段、计数器、重置隔离。 |
| `tests/test_petcore_update.py` | +228/−0（新增） | manifest、ETag、镜像、Range/断点、取消、传输失败保留断点、摘要和 frozen 条件。 |
| `tests/test_petcore_cli.py` | +10/−0 | update 子命令与 `--check` 诊断。 |
| `tests/test_petcore_island_segments.py` | +20/−0 | SegmentRegistry 注册、卸载和释放。 |
| `tests/test_petcore_island_window.py` | +1/−1 | P5 卡片/窗口生命周期断言。 |
| `tests/test_petcore_settings.py` | +35/−1 | 余额开关、图标尺寸、下拉框宽度和设置契约。 |
| `tests/test_petcore_about_page.py` | +15/−0 | 更新下载中状态、取消按钮和取消回调。 |

### 文档与证据

`docs/PETCORE-LOG.md`/`PETCORE-LOG-INDEX.md` 记录 L081、L082；`PETCORE-ROADMAP.md`、`PETCORE-SPEC.md`、`PETCORE-MAIN-PARITY-BACKLOG.md` 同步状态；`ONLINE-UPDATE.md`、`ONEDIR_PACKAGING.md`、`STABLE_BUILDS.md` 明确更新协议和候选包缺口；本报告和 `.scratch/petcore-p5-complete/HANDOFF.md` 保存验收证据与下一台机器的交接步骤。

## 三、实现要点

### 灵动岛

`DynamicIsland` 继续使用已有胶囊/卡片窗口和 `SegmentRegistry`，没有增加第二个岛窗口或动画引擎。`_sync_sampling()` 以窗口可见、展开状态和折叠计划统一控制 CPU/内存/网络采样；卡片操作通过 signals 回到 CoreHost。消息使用 `deque(maxlen=8)`，余额只在显式刷新时请求。扩展段带释放函数，卸载和清理时不会保留未知/迟到快照。`set_probe_snapshot()` 提供可选 GPU/FPS 平台探针接缝，使用真实快照时显示其值；未接入探针时保持具体 unavailable 原因，不创建伪采样线程。避让仅调整灵动岛几何，失败时不改变桌宠物理位置。

### 余额

`BalancePresenter` 以 slot 为键保存 cache/inflight/generation。重复点击命中 inflight 时直接返回，不创建第二个请求；关闭、取消或代次变化时丢弃回调。CoreHost 对同一服务选择逻辑统一，菜单、左键和卡片刷新不复制网络实现。

### UI 几何

菜单 QSS 把图标列固定为 24 px，并给文字保留左右安全空间；设置导航显式 `QListWidget.setIconSize(QSize(24, 24))` 与 42 px 行高；每个 QComboBox 按 `QFontMetrics.horizontalAdvance()` 的最大项宽加边框/箭头/内边距设置最小宽度。没有全局 Qt patch，也没有修改旧 `pet` 样式。

### 更新

更新 manifest 支持 list/dict 两种资产形态与多个可信镜像。下载使用稳定的 `<asset>.part` + JSON 元数据，206 校验 `Content-Range`，200 重启，416 区分完整与无效范围；取消或传输中断保留可复用断点，摘要/大小/协议失败清除断点。设置页在下载中显示取消按钮，取消会递增 generation 并拒收迟到完成回调。`install()` 只接受 updates 缓存目录中已成功校验的 `.exe/.msi`，源码和非 Windows 固定返回 `unsupported_runtime`。

## 四、性能分析

**方法（可复现）**：`.venv\Scripts\python.exe .scratch\petcore-p5-complete\measure_performance.py`；Windows，Python 3.11.1，PySide6 6.11.1，psutil 7.2.2，offscreen Qt；每种 active/hidden/off 预热 15 秒、采集 60 秒、重复 3 次。原始数据：`.scratch/petcore-p5-complete/performance-2026-10-25.json`。

| 场景 | CPU mean（3 次） | CPU max | RSS 峰值范围 | 线程数 | 采样/更新结果 |
|---|---:|---:|---:|---:|---|
| active | 1.486–1.805% | 4.6–6.2% | 49,250,304–49,831,936 B | 6 | CPU 73–74、网络 73、UI 74–75、合并 74–75 |
| hidden | 0.153–0.407% | 1.5–3.0% | 49,311,744–49,451,008 B | 2–4 | CPU/网络/UI/合并均 0 |
| off | 0.312–0.433% | 3.1% | 49,295,360–49,897,472 B | 2–4 | CPU/网络/UI/合并均 0 |

启停耗时：active 启动 4.114–13.348 ms、停止 0.652–1.497 ms；hidden 启动 4.628–11.795 ms、停止 0.262–1.702 ms；off 状态启动/停止约 0–0.002 ms。余额/更新网络请求在该探针中为 0，磁盘写入为 0；它们只在用户显式操作时触发，不在灵动岛采样循环中触发。运行时新增长驻 worker 仅在余额/更新任务实际提交时创建；默认 island 采样维持已有两条监控线程，隐藏和关闭时停止。

性能结论：① active 相对 hidden 多出 73 次 CPU/网络样本和约 74–75 次合并 UI 更新/60 秒，即约 1.2 Hz 的 Qt/offscreen 事件节拍，采样器本身约束为 1 Hz；② hidden/off 没有指标或 UI 更新；③ P5 没有新增持续网络/磁盘写入，余额/更新为显式请求；④ 三次 RSS 峰值均在约 49.25–49.90 MB 区间，未观察到随重复增长；⑤ 高负载时受影响聚焦族 121 tests 连续 3 遍均通过，耗时 13.08/13.29/12.96 秒。

## 五、实机运行记录

### Windows 进程级现场

命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m petcore --root .scratch\petcore-p5-complete\check-root-final --check --out .scratch\petcore-p5-complete\check-final.json
```

真实输出关键字段：`exit=0`、`version=0.2.0`、`platform=windows`、`architecture=x64`、`frozen=false`、`can_auto_install=false`、`manifest_url_allowed=true`、`fallback_manifest_urls_allowed=true`。`characters` 读取到 `shenshen` 的 106 个 WebM 动画以及 `body_box/head_box`，说明 Core 诊断链实际运行；该命令不等同于可视化桌面通过。

### 本机可见 UI / 候选安装器边界

本轮在当前电脑只用 offscreen Qt 运行自动化窗口测试，没有真实桌面窗口操作记录，因此不能宣称鼠标、右键菜单、DPI、停靠、两宠或安装器的 Windows 实机通过。探针结果为：项目 `.venv` 中 `PyInstaller` 模块不存在（`pyinstaller_module=False`），虽然系统命令可见版本 `6.20.0`，按约束没有把全局工具用于项目候选构建；冻结运行条件由测试覆盖但没有启动真实安装器。

GPU/FPS 本机没有可用原生探针；代码提供 `DynamicIsland.set_probe_snapshot()` 接入真实平台快照，当前不注入伪造读数，无 probe 时显示具体 `当前环境未接入可用 GPU/FPS 探针`，不会显示 0。真实余额服务、真实 API key、GitHub Release/CDN 和 Smart App Control 没有在本轮使用。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `.venv\Scripts\python.exe -m ruff check petcore tests scripts` | `All checks passed!` |
| P5 聚焦 | `$focused = @('tests/test_petcore_about_page.py','tests/test_petcore_balance.py','tests/test_petcore_cli.py','tests/test_petcore_island_p5.py','tests/test_petcore_island_segments.py','tests/test_petcore_island_window.py','tests/test_petcore_menu_icons.py','tests/test_petcore_performance.py','tests/test_petcore_settings.py','tests/test_petcore_update.py'); .venv\Scripts\python.exe -m pytest @focused -q` | `121 passed in 13.08s`；CPU 压力进程下 3 次：`13.08s / 13.29s / 12.96s` |
| petcore 全量 | `$files = (Get-ChildItem tests -Filter 'test_petcore_*.py').FullName; .venv\Scripts\python.exe -m pytest @files -q` | `1513 passed in 126.19s (0:02:06)`，exit 0 |
| Core 诊断 | `.venv\Scripts\python.exe -m petcore --root .scratch\petcore-p5-complete\check-root-final --check --out .scratch\petcore-p5-complete\check-final.json` | exit 0；`version=0.2.0`、`platform=windows`、`frozen=false`、`can_auto_install=false` |
| 代码/文档空白 | `git diff --check` | 无空白错误，仅 LF/CRLF 转换提示 |
| 旧实现整仓 | 未执行 | 按用户边界，本轮只验收 petcore |

## 七、已知限制与后续

- 本机没有执行真实可视化 Windows UI、双屏混合 DPI、冻结安装器、真实余额服务、真实 GPU/FPS、macOS/Linux 或公开 CDN/Release；这些缺口已由代码降级、测试和探针记录覆盖，但不能写成实机通过。
- 当前 `pyinstaller` 只在系统 PATH 可见，项目 `.venv` 没有对应模块；候选构建交给另一台 Windows 机器，必须补回真实 SHA、安装/更新失败恢复/回滚和进程残留证据。
- 不新增 GPU/FPS 伪读数；平台探针可通过 `DynamicIsland.set_probe_snapshot()` 或 SegmentRegistry 接入真实快照，当前无探针显示 unavailable 原因。
- 不在本轮切换默认入口、不上传 Release、不启动真实安装器。

## 八、风险与回滚

新增持久键只有按 slot 的 `click_show_balance`，缺失默认 false，删除该键即可回到旧行为。更新下载只在配置目录 `updates/` 产生 manifest/etag/part/cache；代码回滚不会触碰源码目录。回滚本轮工作树应按文件级 `git revert`/恢复本轮提交，未有真实安装器在本机启动，因此没有安装目录回滚动作。

## 九、最终状态

本轮代码在 petcore 范围内已完成并通过自动化门禁；“Windows 实机可见 UI”“冻结安装器验收”“GPU/FPS 真读数”“公开发布”保持未验证/未执行。详细交接见 `.scratch/petcore-p5-complete/HANDOFF.md`。

## 十、远端交付复验（2026-10-26）

- 实现提交：`ce8c67fb1e626686c8e5553bcb5957289f798b55`，43 文件、+2351/−28。精确文件清单可复核 `git show --numstat ce8c67fb`；报告内历史测试和性能数据仍为 2026-10-25 的原记录。
- 本次提交前复验：Ruff `All checks passed!`；petcore 全量 `1513 passed in 122.25s (0:02:02)`、exit 0；架构/文档/设置覆盖/PR 报告门禁 `306 passed in 3.88s`；暂存区 `git diff --cached --check` 通过。
- 暂存检查清理 3 处空白问题；`tests/test_petcore_island_p5.py` 最终为 +96/−0。没有更改运行行为，未追加旧实现测试或重复性能实测。
- SSH 443 普通推送已成功：`3f2155fd..ce8c67fb HEAD -> feat/petcore-vpet-architecture`；随后 `ls-remote` 核验远端为上述完整 SHA。
- 本节和 L083 是实现提交之后的独立文档回填；未推送 Release 资产、未合并 main、未覆盖安装。已知实机及环境缺口仍见第五、七节。
