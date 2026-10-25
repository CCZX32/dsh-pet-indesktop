# petcore 修复、重构收尾与分支交付报告（2026-10-25）

> **基线**：`e79e2a5f`（本地分批实施前）
> **分支**：`feat/petcore-vpet-architecture`
> **当前代码提交**：`da107abe`、`c456ff56`、`42856889`
> **日期**：2026-10-25
> **范围**：运行时迁移与 Worker、媒体/角色边界、已有 parity 设置与入口、petcore 专项验收证据。
> **交付边界**：不上传 GitHub Release，不切换默认入口，不合并 `main`，不 force push。

## 范围与结论

本轮将计划中已有实现、且能在当前代码边界内独立验收的重构尾项分成三个代码批次完成，并保留未具备环境或明确不在范围的任务。结论不是“所有主分支能力都已迁移”：运行时迁移、Worker、角色 ZIP 导入、点击音效 token、彩蛋设置、余额入口和 GraphType 菜单已经有代码与自动化证据；双屏/混合 DPI 实机、PyInstaller 候选包、macOS/Linux、真实外部服务、公开 Release 和默认入口切换仍未完成或未验证。

按用户最新要求，后续门禁只运行 `petcore` 测试和 petcore 专项文档/架构门禁，不重复运行旧 `pet` 实现的整仓测试。此前在该要求生效前已完成的一次整仓测试仅作为历史证据保留，不作为本次后续门禁承诺。

## 修改文件说明

下表为相对基线 `e79e2a5f` 的代码与测试 `git diff --numstat`；文档收口在最终 release 提交中另行记录。

### 批次一：运行时迁移与 Worker（`da107abe`）

| 文件 | 增删 | 改动原因 |
|---|---:|---|
| `petcore/config.py` | +169 / −22 | 增加迁移状态与诊断、备份优先和原子写入约束，避免失败时静默覆盖原配置。 |
| `petcore/chat/session_store.py` | +26 / −4 | 增加 schema/version 校验与损坏文件诊断，保留不可迁移原文件。 |
| `examples/petcore-mods/reminder.todo/host/store.py` | +57 / −13 | 为提醒数据增加迁移状态、备份/写入/校验失败分类，兼容旧纯文本条目。 |
| `petcore/platform/worker.py` | +66 / −21 | 补齐非法消息拒收、有界 shutdown、管道/线程清理与退出结果记录。 |
| `tests/test_petcore_refactor_final.py` | +156 / −0 | 新增迁移、session、Worker、ZIP、点击音效的失败回归。 |

### 批次二：媒体与角色边界（`c456ff56`）

| 文件 | 增删 | 改动原因 |
|---|---:|---|
| `petcore/content/importer.py` | +71 / −9 | 设置内角色 ZIP/目录导入使用临时目录，拒绝路径穿越、非法链接与重复覆盖。 |
| `petcore/media/click_sound.py` | +46 / −0 | 以 token 配对按下/释放，处理失焦、拖拽取消和重复释放。 |
| `petcore/ui/easter_egg.py` | +25 / −3 | 增加配置头像/默认回退和提示文案，不另建窗口实现。 |
| `petcore/ui/pet_window.py` | +36 / −7 | 将点击 token 接入真实按下/释放/拖拽/关闭生命周期。 |

### 批次三：已有 parity 设置与动画入口（`42856889`）

| 文件 | 增删 | 改动原因 |
|---|---:|---|
| `petcore/ui/settings/pages_core.py` | +28 / −8 | 增加角色导入入口并保持设置页布局/作用域。 |
| `petcore/ui/settings/page_interaction.py` | +64 / −0 | 增加彩蛋提示/头像的实时预览、保存、取消、重置与搜索。 |
| `petcore/ui/settings/page_api.py` | +73 / −1 | 增加异步余额查询、disposed 迟到信号抑制和分类错误反馈。 |
| `petcore/ui/menu_actions.py` | +11 / −0 | 使用既有 `GraphType` 增加可选懒加载动作组，资源缺失时不制造假入口。 |

### 文档与交接

`docs/PETCORE-LOG.md` 的 L075–L077 已记录三个代码批次及对应 numstat；最终文档批次将以 L078 记录。`docs/PETCORE-MAIN-PARITY-BACKLOG.md`、`PETCORE-ROADMAP.md`、`PETCORE-SPEC.md`、`docs/INDEX.md` 和本报告同步区分实现、自动化、实机与待验证状态。`.scratch/petcore-refactor-final/HANDOFF.md` 保存精确断点，不进入产品代码。

## 性能分析

本轮没有对新功能伪造“预热 15 秒、采集 60 秒、重复 3 次”的长稳态数据；已有市场 D1/T09 的 loopback 基准仍保留在历史报告中，不冒充本轮媒体/迁移性能。

| 路径 | 实测证据 | 结果 |
|---|---|---|
| 受影响 petcore 回归族 | 136 tests，`23.24s`；API/账户/设置族 95 tests，`52.08s`；新增回归 6 tests，`1.00s` | 作为功能路径耗时样本，不等价稳态 CPU/内存基准。 |
| CPU 高负载时序 | 19 个负载进程、3 轮；pytest 分别 `29.44s`、`24.65s`、`27.28s`，驱动总耗时 `31.15s`、`38.63s`、`28.45s`；每轮 136 passed | 受影响线程/Qt 测试在压力下未出现失败。 |
| 新增运行时成本 | 角色导入临时目录/归档读写；余额查询新增异步 `QThreadPool` 任务；点击音效只增加 token 状态 | 本轮没有持续采样 CPU/内存、磁盘字节或系统调用计数，因此不宣称“无成本”；任务均在显式用户动作或已有点击/设置路径触发。 |
| 语音/网络 | 语音默认关闭；本轮余额测试使用 fake service，不连接真实外部服务 | 未测真实网络延迟、代理、TTS/CDN；无新增远程地址或公开下载链路。 |

## 实机运行记录

环境：Windows，项目 `.venv`，`QT_QPA_PLATFORM=offscreen`，`PYTHONUTF8=1`；数据目录使用 `.scratch/petcore-refactor-final` 隔离路径。

| 命令/探针 | 真实结果 | 结论 |
|---|---|---|
| `.venv\Scripts\python.exe -m petcore --root .scratch\petcore-refactor-final\check-root --check` | `exit 0`，version `0.2.0`，`diagnostics: []`，active slot `[0]` | 隔离目录启动检查通过。 |
| `.venv\Scripts\python.exe -m petcore --check` | `exit 0`，输出保存至 `.scratch/petcore-refactor-final/default-check.json` | 默认检查本次正常退出；不等价安装器验收。 |
| Qt 屏幕/DPR 探针 | `screens=1`，`dprs=1.0` | 仅证明当前单屏 offscreen 探针；不能证明双屏/混合 DPI。 |
| 依赖探针 | `PyInstaller=False`、`cryptography=False`、`rapidocr=True`、`onnxruntime=True` | 未安装 PyInstaller，候选包构建不标记通过。 |
| 角色导入回归 | 真实本机临时文件系统执行；恶意 `../` 条目拒绝，重复 ID 不覆盖原角色 | 代码路径通过自动化与本机文件系统测试。 |

未做真实账号、真实凭据、真实 TTS/CDN、双屏拔出、macOS/Linux、候选安装器或公开 Release；没有修改系统安全策略、现有安装或用户账号。

## 自动化验证

### 本轮已完成的 petcore 门禁

- Ruff：`.venv\Scripts\python.exe -m ruff check petcore tests scripts` → `All checks passed!`。
- 编译：`.venv\Scripts\python.exe -m compileall -q petcore examples/petcore-mods/reminder.todo/host` → exit 0。
- 新增回归：`tests/test_petcore_refactor_final.py` → `6 passed in 1.00s`。
- 运行时/媒体/设置联合族 → `136 passed in 23.24s`。
- API/账户/设置关联族 → `95 passed in 52.08s`。
- 架构、文档、设置覆盖专项 → `318 passed in 4.46s`。
- CPU 高负载三轮：每轮 `136 passed`，详见上方性能表。
- 文档收口后的 petcore-only 全量：显式展开 `tests/test_petcore_*.py` 后 **1479 passed in 132.94s (0:02:12)**；petcore 架构/文档/设置覆盖/交付纪律门禁 **302 passed in 4.03s**；Ruff `All checks passed!`。

### 历史证据（不作为后续门禁）

在用户将后续门禁收窄为 petcore-only 之前，已实际运行一次：

```text
.venv\Scripts\python.exe -m pytest -q
9957 passed, 20 skipped, 15 warnings in 3048.17s (0:50:48), exit 0
```

该结果说明当时整仓可以正常退出，但后续不再重复执行旧 `pet` 实现测试；不将此条外推为本轮所有跨平台或候选包均已验收。

## 未完成与验证缺口

1. `.venv` 未安装 PyInstaller，未构建或隔离安装候选包；不切换默认入口。
2. 当前只有单屏/DPR 1.0，双屏、混合 DPI、屏幕拔出和跨屏动作待有条件环境验证。
3. macOS/Linux、真实外部 TTS/CDN/余额服务未验证；网络代理行为不以 fake service 代替。
4. `petcore/media` 与 `petcore/content/legacy.py` 的兼容边界仍保留，未删除旧实现；VPet LPS/PNG、角色远程下载、Agent 写端、灵动岛二阶段和 Core 自更新不在本轮。
5. 未上传 GitHub Release/CDN，不生成公开可下载结论。

## 回滚与交付

代码提交可按以下顺序独立回滚（不使用 reset/force push）：

```text
git revert 42856889
 git revert c456ff56
 git revert da107abe
```

最终文档提交只包含证据和状态文件，可单独 revert。远端同步按 SSH over 443 使用 `git merge --ff-only`；若远端出现新提交，先同步并重新运行 petcore-only 门禁，再推送 `origin/feat/petcore-vpet-architecture`。本报告不代表公开发布或默认入口切换已完成。
