# petcore P1：配置作用域与迁移基础——修改文件说明、性能分析、实机运行记录

> **基线**：P0 提交 `18e5546`
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-22
> **范围**：petcore 配置、设置、feature 端口、宠物管理和回归测试
> **关联**：[审查报告](PR-REPORT-PETCORE-AUDIT-2026-10-22.md)、[交接计划](PETCORE-HANDOFF-PLAN-2026-10-22.md)

## 一、核心特性

设置窗口现在绑定打开它的宠物。每宠配置通过 `ScopedConfig` 写入当前 slot，全局配置仍写入主配置。旧 standalone 配置和 slot 档案会迁移到新目录，并先保存备份。

**红线 / 不变量**：子宠设置不能改主宠；全局设置必须能作用到所有宠物；旧配置源文件不能被迁移器改写。

## 二、修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `petcore/config.py` | +206 / −13 | 全局键集合、旧键映射、standalone/slot 迁移、备份和 `ScopedConfig`。 |
| `petcore/paths.py` | +22 / −0 | 扫描旧 standalone 变体目录。 |
| `petcore/ui/settings/dialog.py` | +26 / −5 | 设置对话框按目标宠物建立配置代理并更新标题。 |
| `petcore/ui/app.py` | +33 / −12 | 实时应用按每宠配置读取；全局设置仍广播；打开设置传入目标窗口。 |
| `petcore/ui/pet_manager.py` | +20 / −29 | 只同步真正全局键；新宠播种完整每宠配置；通知 feature 宠物生命周期。 |
| `petcore/ui/pet_window.py` | +1 / −1 | 从当前窗口打开设置。 |
| `petcore/ui/ports.py` | +1 / −0 | PetHandle 暴露当前宠物配置。 |
| `petcore/mods/feature.py` | +20 / −0 | 增加宠物加入/移除生命周期钩子。 |
| `petcore/builtin/features/fun.click-talk/host/factory.py` | +4 / −1 | 点击台词读取被点击窗口的配置。 |
| `petcore/builtin/features/fun.self-talk/host/factory.py` | +50 / −11 | 自言自语按宠物独立排程并收口 timer。 |
| `petcore/ui/settings/pages_core.py` | +3 / −3 | 全局设置行明确“影响所有桌宠”。 |
| `tests/test_petcore_config_scope.py` | +70 / −0 | 作用域、快照恢复、保存和迁移回归。 |
| `tests/test_petcore_click_listeners.py` | +12 / −3 | 主宠和子宠使用各自点击台词。 |
| `tests/test_petcore_settings.py` | +22 / −0 | 真实 Qt 设置对话框绑定子宠。 |

## 三、实现要点

- `ScopedConfig` 维持现有 `Config` 形状，未知新键默认归当前宠物，显式全局键才写主配置。
- 设置窗口为当前目标窗口创建代理，标题显示主宠或子宠。
- `CoreHost._apply_live_to()` 对每个窗口读取自己的 pet config，对全局键读取主配置。
- standalone 迁移只读取旧目录；目标配置写入临时文件后原子替换，旧配置复制到 `migration-backup/`。
- 自言自语 runtime 为每个宠物保存独立 timer；子宠恢复/生成时通过 feature 生命周期钩子补排程。

## 四、性能分析

方法：PowerShell 临时 Python 脚本，Windows 工作站，Python `.venv`，临时配置目录，`timeit.repeat` 最优轮次。

| 指标 | 实测 | 归属 |
|---|---:|---|
| `ScopedConfig.get("character")` | 0.14 µs/op，n=50,000 | 新增设置读取路径 |
| `ScopedConfig.set("character")` | 12.75 µs/op，n=5,000 | 新增配置归一化路径 |
| `ScopedConfig.snapshot()` | 34.08 µs/op，n=500 | 设置打开/取消路径 |
| 新增常驻线程 | 0 | 作用域和迁移不创建线程 |
| 新增网络请求 | 0 | 本阶段不接入网络 |
| 新增磁盘写入 | 仅保存/迁移触发 | 不在逐帧路径 |

## 五、实机运行记录

环境：Windows 工作站，PowerShell，Python `.venv`，Qt offscreen。

```text
pytest tests/test_petcore_config_scope.py -q -> 4 passed in 0.51s
P1 聚焦 -> 43 passed in 4.64s
petcore 全套 -> 608 passed in 23.17s
petcore + architecture/report/CI -> 907 passed, 5 skipped in 29.41s
ruff check pet/ tests/ petcore/ -> All checks passed!
python -m petcore --check -> exit code 0
```

自动探针确认：旧配置和 `config-slot-1.json` 迁移后分别写入主配置与 `config-pet-1.json`，并生成 `migration-backup/`；旧源文件仍存在。真实双屏、安装器升级、声卡和非 Windows 窗口行为留给后续人工验收。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| P1 聚焦 | `pytest test_petcore_config_scope/self_talk/click_listeners/settings` | 43 passed |
| petcore 全套 | `pytest tests/test_petcore*.py` | 608 passed |
| 架构/报告/CI | `pytest petcore + guards` | 907 passed, 5 skipped |
| 静态检查 | `ruff check pet/ tests/ petcore/` | 通过 |
| 启动检查 | `python -m petcore --check` | 退出码 0 |

## 七、已知限制与后续

- 会话、待办独立文件、API 服务规格和钥匙串引用尚未迁移；这些文件需要对应消费者和敏感字段清洗，将在 P3/P4 处理。
- 播放速率保持 `0.5–2.0x`，这是已确认的有意差异。

## 八、风险与回滚

本阶段提交可直接 `git revert`。新配置写入新 petcore 数据目录，旧 standalone 配置不被修改；回退时删除新目录或恢复 `migration-backup/` 即可。
