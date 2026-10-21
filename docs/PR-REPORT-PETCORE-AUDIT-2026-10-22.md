# petcore 审查报告：修改文件说明、性能分析、实机运行记录

> **基线**：主分支 `147170f`；重写分支 `0922b13`
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-22
> **范围**：只读代码/文档审查与测试验证，不改变运行时行为
> **关联**：[功能矩阵](PETCORE-FUNCTION-MATRIX-2026-10-22.md)、[交接计划](PETCORE-HANDOFF-PLAN-2026-10-22.md)

## 一、核心特性

本报告核对主分支 v4.3.4 的用户能力与 petcore 当前实现，确认当前桌宠交互体验可作为后续真值，同时列出配置作用域、迁移、Worker、账户、业务功能域、安装器和发布切换缺口。

## 二、修改文件说明

本阶段只新增审查文档并登记索引，没有运行时代码修改。

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `docs/PETCORE-FUNCTION-MATRIX-2026-10-22.md` | 新增 | 固定主分支功能域、petcore 状态、阶段归属和有意差异。 |
| `docs/PETCORE-HANDOFF-PLAN-2026-10-22.md` | 新增 | 把后续工作拆成可交接阶段，固定每阶段边界和验收。 |
| `docs/PR-REPORT-PETCORE-AUDIT-2026-10-22.md` | 新增 | 记录审查发现和本机验证证据。 |
| `docs/PETCORE-SPEC.md` | 更新 | 增加配置作用域、Worker、迁移和发布边界。 |
| `docs/PETCORE-ROADMAP.md` | 更新 | 增加 P0–P6 计划、依赖和用户效果。 |
| `docs/PETCORE-LOG.md` | 更新 | 追加本次审查条目。 |
| `docs/PETCORE-LOG-INDEX.md` | 更新 | 登记本次审查条目。 |
| `docs/PETCORE-MAIN-PARITY-BACKLOG.md` | 更新 | 标记配置作用域和迁移缺口。 |
| `docs/PETCORE-ARCHITECTURE.md` | 更新 | 记录宠物上下文和 WorkerHost 的目标边界。 |
| `docs/INDEX.md` | 更新 | 登记新增审查文档。 |

## 三、实现要点

- 当前 petcore 通过 51 个测试文件覆盖窗口、动画、碰撞、菜单、设置、mod 和打包契约。
- 结构守卫确认 `engine` 无 Qt、`contracts` 仅标准库、网络出口和 mod import 边界成立。
- 审查发现 `SettingsDialog`、内置 feature 和设置页使用 `host.config`，而 `PetManager` 同步多个每宠键；这使子宠设置不能满足主分支语义。
- `contracts/worker.py` 只有 JSONL 协议；`petcore/account/` 尚不存在，故不能把 API 设置页视为账户能力已经交付。

## 四、性能分析

本阶段不改运行时代码，因此没有新增热路径、线程、网络或磁盘开销。

| 指标 | 实测 | 归属 |
|---|---:|---|
| petcore 测试 | 603 passed | 既有测试 |
| petcore + 架构/报告/CI 守卫 | 900 passed, 5 skipped | 既有测试 |
| ruff | All checks passed | 静态检查 |
| `petcore --check` | exit 0 | 既有启动检查 |

## 五、实机运行记录

环境：Windows 工作站，PowerShell，Python `.venv`，`QT_QPA_PLATFORM=offscreen`。

```text
.venv\Scripts\python.exe -m pytest <51 个 test_petcore 文件> -q
603 passed in 37.60s

.venv\Scripts\python.exe -m pytest <petcore + architecture/report/CI> -q
900 passed, 5 skipped in 42.62s

.venv\Scripts\ruff.exe check pet/ tests/ petcore/
All checks passed!

.venv\Scripts\python.exe -m petcore --check
exit code 0; 输出角色、配置、mods、媒体后端和诊断信息
```

无法自动验证：真实双屏/混合 DPI、真实安装卸载、真实声卡、macOS/Linux 窗口行为和完整大素材导入需要物理设备或冻结包现场；这些限制已进入功能矩阵和阶段计划。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| petcore 聚焦 | `python -m pytest <test_petcore 文件列表> -q` | 603 passed |
| 架构/报告/CI | `python -m pytest <petcore + guards> -q` | 900 passed, 5 skipped |
| 静态检查 | `ruff check pet/ tests/ petcore/` | 通过 |
| 启动检查 | `python -m petcore --check` | 退出码 0 |

## 七、已知限制与后续

后续按 `PETCORE-HANDOFF-PLAN-2026-10-22.md` 执行。播放速率范围和 VPet LPS/PNG 支持属于明确有意差异。

## 八、风险与回滚

本阶段只新增文档，回滚可直接还原本阶段提交；没有配置迁移、网络调用或运行时状态残留。
