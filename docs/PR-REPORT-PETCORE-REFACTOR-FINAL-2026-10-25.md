# petcore 修复、重构收尾与分支交付报告（2026-10-25）

> **基线**：`6326e31c410dc86d632caf0e4201a664e6924964`（远端分支同步后的提交）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：`2026-10-25`
> **范围**：市场生命周期/传输授权/回滚语义、WorkerHost 运行时边界、DPR 帧渲染、候选索引状态及对应测试与文档。
> **交付边界**：不上传 GitHub Release，不切换默认入口，不合并 `main`，不 force push。

## 一、核心特性

本轮关闭了六类已复现的市场阻断，并完成了一个有界的运行时/媒体收口批次：市场页面销毁不再丢失运行中的 QThread，下载取消和可重试中断保留可续传状态，远程 feature 包才套用安全解包预算，本地 `file://` 访问受显式授权根和索引来源约束，回滚结果不再用成功文案掩盖失败，候选索引与已发布索引通过显式状态区分；同时给 `WorkerHost` 增加握手/代次边界，并修正帧 pixmap 的物理尺寸和 DPR。

| # | 能力 | 结果 |
|---|---|---|
| 1 | 市场任务生命周期 | `MarketJobRegistry` 由应用持有，页面销毁只取消、断开并移交；应用退出有界等待，不调用 `QThread.terminate()`。 |
| 2 | 下载与安装安全 | 稳定 `.part`/元数据、Range 分支、取消检查、来源/根目录授权、实际流式预算、结构化回滚状态。 |
| 3 | WorkerHost | 真实子进程 READY 等待、代次回调过滤、迟到消息拒收、异常/退出事件测试。 |
| 4 | DPR | 帧按物理像素尺寸缩放并写回 DPR；窗口帧入口使用屏幕 DPR。 |
| 5 | 分发状态 | 构建器默认 `candidate` 并保持 `blocked`；只有显式 `published` 才生成可下载索引。 |

**红线 / 不变量**：不改变默认开关和配置归属；不把 `file://` 变成网络索引的隐式后门；取消中的安装不进入备份/替换；回滚失败不显示“已回滚”；未完成 Windows 双屏、候选安装器和公开 Release 验收前不切换默认入口。

## 二、修改文件说明

以下为相对基线 `6326e31c` 的 `git diff --numstat` 摘要。截至提交前复核，`git diff --numstat 6326e31c` 的文档增量为：`docs/INDEX.md` +2/−0、`docs/PETCORE-EXTENSIONS-RELEASE.md` +8/−3、`docs/PETCORE-LOG-INDEX.md` +3/−0、`docs/PETCORE-LOG.md` +35/−0、`docs/PETCORE-MAIN-PARITY-BACKLOG.md` +15/−0、`docs/PETCORE-ROADMAP.md` +13/−0、`docs/PETCORE-SPEC.md` +7/−0；本报告新增 1 个文件（`git diff --numstat` 对未跟踪文件不显示，提交前以 `git diff --stat HEAD` 复核）。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `petcore/contracts/archive.py` | +41 / −0 | 增加按来源与包类型计算有效解包预算，避免 content/local/bundled 被远程 feature 限制误伤。 |
| `petcore/contracts/http.py` | +5 / −0 | 增加本地文件传输的显式开关和授权根。 |
| `petcore/market/cli.py` | +11 / −2 | 复用网络层 URL/本地根解析，保持 Core 架构不直接导入 urllib。 |
| `petcore/market/download.py` | +90 / −6 | 稳定断点文件、元数据、取消/重试保留和成功原子移动。 |
| `petcore/market/install.py` | +160 / −38 | 接入来源/预算/本地根授权、取消门、结构化回滚结果和失败诊断。 |
| `petcore/market/source.py` | +30 / −5 | 将取消信号贯穿索引读取并兼容旧 fetcher。 |
| `petcore/net/market.py` | +37 / −6 | 索引读取限额、取消检查和显式本地索引授权。 |
| `petcore/net/market_transport.py` | +103 / −27 | 修正 Range/206/200/416、响应释放、file 重定向拒绝和有界流式复制。 |
| `petcore/platform/worker.py` | +79 / −23 | 增加 READY 等待、会话代次、迟到回调过滤和退出事件边界。 |
| `petcore/ui/app.py` | +8 / −0 | 应用级持有市场任务 registry 并在退出阶段有界收口。 |
| `petcore/ui/market_jobs.py` | +82 / −0 | 新增 `MarketJobRegistry`，统一登记、取消和诊断任务。 |
| `petcore/ui/pet_window.py` | +1 / −0 | 帧渲染入口传入当前屏幕 DPR。 |
| `petcore/ui/renderer.py` | +19 / −7 | 按物理尺寸生成 pixmap、写回 DPR，并用 Qt 变换镜像。 |
| `petcore/ui/settings/page_market.py` | +82 / −18 | 页面 dispose 只取消/断开/移交，抑制迟到信号。 |
| `scripts/build_petcore_extensions.py` | +25 / −6 | 增加 candidate/published 状态，默认候选索引保持 blocked。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---:|---|
| `tests/test_petcore_extension_build.py` | +6 / −0 | 候选索引 blocked 与显式 published 解锁。 |
| `tests/test_petcore_market_hardening.py` | +311 / −0 | 市场线程、续传、解包预算、file 授权、回滚和进程边界回归。 |
| `tests/test_petcore_market_install.py` | +17 / −4 | 安装取消和 rollback 结果语义。 |
| `tests/test_petcore_renderer.py` | +43 / −0 | DPR 1.5、物理尺寸、镜像与非法 DPR。 |
| `tests/test_petcore_worker.py` | +90 / −109 | READY、代次替换、迟到消息和退出边界。 |

### 文档与日志

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `docs/PETCORE-LOG.md` | +35 / −0 | 追加 L072/L073/L074 逐批记录。 |
| `docs/PETCORE-LOG-INDEX.md` | +3 / −0 | 登记 L072/L073/L074。 |
| `docs/PETCORE-EXTENSIONS-RELEASE.md` | +8 / −3 | 明确 candidate 默认状态与发布状态转换。 |
| `docs/PETCORE-MAIN-PARITY-BACKLOG.md` | +15 / −0 | 追加本轮真实收口快照，未验收项仍保留。 |
| `docs/PETCORE-ROADMAP.md` | +13 / −0 | 追加当前重构收尾状态和默认入口前置条件。 |
| `docs/PETCORE-SPEC.md` | +7 / −0 | 追加可验证契约与未完成 parity 边界。 |
| `docs/INDEX.md` | +2 / −0 | 登记本报告。 |
| `.scratch/petcore-refactor-final/HANDOFF.md` | 工作区交接文件 | 记录提交、门禁和准确断点；按项目约定不纳入产品提交。 |
| `docs/PR-REPORT-PETCORE-REFACTOR-FINAL-2026-10-25.md` | 新增 | 本轮逐文件、性能、实机、测试、限制和回滚证据。 |

无删除文件。

## 三、实现要点

1. **任务所有权**：`MarketPage` 不再通过无主模块集合维持线程；应用级 registry 保存 QThread 引用直到完成或有界退出。页面关闭不阻塞，应用最终退出统一取消并等待，超时保留诊断引用。
2. **续传状态**：断点键包含 package id、version、expected size、expected SHA-256；取消、连接中断和可重试错误保留 `.part` 与元数据，完整性/协议/超限等不可恢复错误清理对应状态。
3. **来源与预算**：`effective_archive_limits()` 只对 `MARKET + feature` 套用 64 MiB/256 MiB/10000 条目上限；显式值只能收紧。网络索引不能借重定向访问 `file://`，显式本地索引也必须提供授权根并做路径包含检查。
4. **回滚语义**：回滚返回 `RollbackResult`，恢复成功、恢复后清理失败、备份缺失、恢复失败等状态分开表达；UI 只在实际恢复成功时显示成功文案。
5. **Worker/DPR**：worker 注册代次后再启动，回调检查当前代次；渲染先按物理尺寸缩放再写回 DPR，逻辑布局仍使用 Qt 逻辑像素。

## 四、性能分析

**方法（可复现）**：
```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest tests/test_petcore_market_transport_security.py tests/test_petcore_market_install.py tests/test_petcore_market_ui.py tests/test_petcore_remote_archive_limits.py tests/test_petcore_extension_index.py tests/test_petcore_extension_build.py tests/test_petcore_market_hardening.py -q
.venv\Scripts\python.exe -m pytest tests/test_petcore_worker.py tests/test_petcore_renderer.py -q
```
环境：Windows、Python 3.11.1、PySide6 6.11.1、pytest 8.3.4、offscreen Qt。

| 指标 | 实测 | 归属 |
|---|---:|---|
| 市场相关 90 项测试 | 90 passed / 19.56 s | 新增市场安全与生命周期路径 |
| Worker + renderer 5 项测试 | 5 passed / 4.20 s | 新增握手/代次/DPR 路径 |
| 市场+Worker+renderer+架构联合 56 项 | 56 passed / 11.83 s | 交叉门禁 |
| full pytest 基线（修复前） | 1 failed, 9947 passed, 20 skipped, 14 warnings / 1367.59 s | 修复前架构守卫被 urllib 直导入触发 |
| 本轮 15 s 预热 + 60 s ×3 sustained benchmark | 未执行 | 没有与市场/Worker/DPR改动对应的可比采样器；历史 D2 菜单/安装器数字未冒充本轮 |

**结论**：registry 只在存在市场任务时持有 QThread，不改变无任务稳态线程数；下载续传新增的是缓存目录中的 `.part` 和小型 JSON 元数据，只有下载/重试路径写盘；新增网络请求为零；Worker READY/代次判断为每条消息的进程内条件检查；DPR 只改变帧 pixmap 物理分辨率，未增加线程。内存增长和完整 15+60×3 采样待最终门禁实测，不能以“可忽略”替代数据。

## 五、实机运行记录

当前已在本机真实 Windows/Python 环境执行源码级命令和真实子进程/Qt offscreen 测试；这些不是 CI，也不是 mock 的协议替代。完整命令及原始输出在第六节。已确认：远程/本地来源的失败边界、市场线程取消、worker 子进程握手、DPR 物理尺寸断言均可在本机复现并通过。

已在本机隔离数据根执行 `python -m petcore --root .scratch/petcore-check-20261025 --check`，真实输出为 JSON 报告并返回 `isolated_exit=0`。默认用户根的 `python -m petcore --check` 触发旧数据迁移时返回 Windows `WinError 17`（同一 C 盘路径的 `os.replace`），因此保留为环境/迁移缺口，不修改用户数据目录。依赖探针：`PyInstaller=False`、`cryptography=False`、`rapidocr=True`、`onnxruntime=True`；offscreen Qt 只有 1 个 800×800、DPR 1.0 虚拟屏。以下能力仍未写成“实机通过”：真实 HTTPS/CDN 下载、Windows 可见桌面双屏/混合 DPI、PyInstaller 候选安装器、macOS/Linux、真实外部 TTS、公开 Release。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| Ruff | `.venv\Scripts\python.exe -m ruff check petcore tests scripts` | `All checks passed!` |
| 聚焦市场 | 上述市场命令 | 90 passed / 19.56 s |
| Worker/DPR | 上述 worker+renderer 命令 | 5 passed / 4.20 s |
| 高负载 3 遍 | 19 个 CPU burner + `pytest tests/test_petcore_market_hardening.py tests/test_petcore_worker.py tests/test_petcore_renderer.py -q`，循环 3 次 | 每次 12 passed，分别 4.98s / 4.97s / 4.95s |
| 全量 | `.venv\Scripts\python.exe -m pytest -q` | `9951 passed, 20 skipped, 14 warnings in 1289.12s (0:21:29)`，exit 0 |
| 架构/文档 | `tests/test_petcore_architecture.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_petcore_docs.py` | `316 passed in 4.65s` |
| `python -m petcore --root .scratch/petcore-check-20261025 --check` | Windows 隔离源码探针 | JSON 自检报告，`isolated_exit=0`；默认 C 盘旧迁移另有 WinError 17，未伪报通过 |

## 七、已知限制与后续

- 本轮没有实现主分支没有接通的新业务，也没有把“示例 mod 可安装”当作完整 parity。
- 会话/待办/API 全量迁移、角色设置内导入、多屏混合 DPI 实机、GraphType 全映射、点击音效按下/释放配对、媒体适配层完全脱离旧 `pet`、候选安装器验收仍需独立批次。
- PyInstaller、双屏/混合 DPI、macOS/Linux、真实外部服务若本机不可用，只记录探针结果；不切换默认入口。
- 公开 GitHub Release、CDN 上架、真实账号操作、Agent 写端和灵动岛二阶段不在本轮。

## 八、风险与回滚

- 代码提交独立可回滚：先回滚后续文档/验收提交，再按需要 `git revert e371f92c`、`git revert 9e973b53`；不使用 reset/force push。
- 新下载断点位于市场缓存目录，旧版本不应读取新元数据；保留新文件不删除用户安装。取消中的安装不会进入替换阶段。
- 如发现远端分支在推送前前进，先重新 fetch，再以 `git merge --ff-only` 集成；不覆盖他人提交。
- 代码提交为 `9e973b53`、`e371f92c`；证据文档提交为 `5c2ba786`。回滚按提交逆序执行 `git revert`，不使用 reset/force push。


## 九、提交与推送

- 远端分支：`origin/feat/petcore-vpet-architecture`。
- 推送前使用 `ssh://git@ssh.github.com:443/MerZlin/dsh-pet-indesktop.git` 做只读 fetch；远端仍为 `6326e31c410dc86d632caf0e4201a664e6924964`，本地领先 3 个提交。
- 使用 SSH over 443 推送 `HEAD:refs/heads/feat/petcore-vpet-architecture`，真实输出：`6326e31c..5c2ba786  HEAD -> feat/petcore-vpet-architecture`，返回码 0。
- 本轮未上传 GitHub Release 资产、未推送 tag、未合并 `main`、未 force push。第二次推送将文档-only 提交 `71e528b6` 推到同一分支，真实输出为 `5c2ba786..71e528b6`；该提交包含远端交付结果记录，不改变产品代码和门禁结果。
