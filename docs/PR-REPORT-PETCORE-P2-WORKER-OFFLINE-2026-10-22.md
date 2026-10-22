# petcore P2：WorkerHost、离线扩展默认安装与角色导入——修改文件说明、性能分析、实机运行记录

> **基线**：P1 提交 `b3f52e8`
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-22
> **范围**：WorkerHost、角色导入、动画 Graph 映射、安装器默认扩展和测试
> **关联**：[P1 报告](PR-REPORT-PETCORE-P1-SCOPE-2026-10-22.md)、[交接计划](PETCORE-HANDOFF-PLAN-2026-10-22.md)

## 一、核心特性

P2 增加了可运行的统一 WorkerHost：真实子进程、JSONL 握手、配置推送、取消、错误回调、
退出回收、所有者替换和心跳超时；CoreHost 在退出时收口所有 worker。安装包的 5 个官方
离线 feature 明确默认选中，设置页增加角色目录导入，旧素材目录增加 VPet Graph 类别映射。

**红线 / 不变量**：worker 不创建 Qt 对象；mod 只通过 WorkerPort；子进程退出后不能持有
Core 管道；取消、超时和关闭必须有界。

## 二、修改文件说明

| 文件 | 改动意图 |
|---|---|
| `petcore/platform/worker.py` | 新增 WorkerSession/WorkerHost、管道线程、心跳监测和退出收口。 |
| `petcore/contracts/worker.py` | 增加 CANCEL/REQUEST_ID 协议字段。 |
| `petcore/ui/app.py` / `petcore/ui/ports.py` | CoreHost 持有 WorkerHost，并向 HostPorts 注入。 |
| `petcore/content/importer.py` | 新增角色目录打包并安装的 UI 接缝。 |
| `petcore/ui/settings/pages_core.py` | 常规页增加角色资源目录导入按钮和反馈文案。 |
| `petcore/content/legacy.py` | 增加 Touch_Head/Say/Sleep/StartUP/Work/Raised Graph 文件夹映射。 |
| `packaging/petcore.iss` / `examples/petcore-mods/README.md` | 明确 5 个官方 feature 默认安装且可取消。 |
| `tests/test_petcore_worker.py` | 真实子进程握手、配置、取消、替换、错误和关闭测试。 |
| `tests/test_petcore_character_pack.py` | 角色 UI 安装接缝和 Graph 类别测试。 |
| `tests/test_petcore_installer.py` | 默认任务选择测试。 |

## 三、实现要点

- WorkerHost 使用 `subprocess.Popen`、独立 stdout/stderr reader 和写锁；回调不直接触碰 Qt。
- `WorkerSession.shutdown()` 先发协议关闭，再按超时 terminate/kill，避免退出挂死。
- 运行时 worker 仍需业务 mod 声明和端到端场景，本阶段只完成宿主基础设施。
- 媒体后端仍保留旧 `pet` 适配层；独立媒体实现留给后续阶段。

## 四、性能分析

方法：Windows 工作站，Python `.venv`，真实 `sys.executable -u -c` worker，pytest 事件同步。

| 指标 | 实测 | 归属 |
|---|---:|---|
| Worker 聚焦测试 | 3 passed / 1.93s | 新增真实子进程路径 |
| P2 相关测试 | 21 passed / 1.54s | 新增/既有 |
| 常驻 Worker 线程 | 每个 worker 2–3 个 daemon 线程 | 新增，仅按 worker 数量触发 |
| 新增网络请求 | 0 | 本阶段不接网络 |
| 新增磁盘写入 | 角色导入时写临时 pack 和 mods | 用户显式导入时触发 |

## 五、实机运行记录

```text
pytest test_petcore_worker.py test_petcore_character_pack.py test_petcore_installer.py test_petcore_architecture.py -q
21 passed in 1.54s

pytest <petcore + architecture/report/CI> -q
915 passed, 5 skipped in 27.15s

ruff check pet/ tests/ petcore/
All checks passed!
```

真实子进程探针确认 READY、CONFIG_PUSH、CANCEL、替换同 owner、SHUTDOWN 和 malformed JSON
错误回调均可收口。真实安装向导、双屏、媒体大素材和声卡仍需人工验收。

## 六、测试与验证

| 门 | 结果 |
|---|---|
| Worker/角色/安装器/架构 | 21 passed |
| petcore + 架构/报告/CI | 915 passed, 5 skipped |
| ruff | 通过 |

## 七、已知限制与后续

- WorkerHost 尚未接入 AI/识屏/Agent 业务；业务 worker 放在 P3/P4。
- `petcore/media/backends.py` 仍通过旧 `pet` 适配 WebM/GIF；媒体解耦尚未完成。
- 安装器真实安装/升级/卸载和默认扩展加载仍需人工验收。

## 八、风险与回滚

本阶段可 `git revert`。默认扩展只改变安装向导初始勾选，不改变已安装用户的数据目录；
WorkerHost 未启动时不创建线程或子进程。

---

## 追加修正（2026-10-22）：官方离线扩展恢复「默认不勾选」

### 修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `packaging/petcore.iss` | +6 / −6（numstat） | 5 个 `mod_*` 任务加 `Flags: unchecked`，注释改成「默认不勾选」。 |
| `tests/test_petcore_installer.py` | +3 / −3 | 用例改名 `..._opt_in`，断言由「不得有 unchecked」反转为「必须有」。 |
| `examples/petcore-mods/README.md` | +2 / −2 | 措辞回到「默认不勾选」；安装位置从 `%APPDATA%…` 修正为 `{app}\mods\<id>`。 |
| `docs/{PETCORE-FUNCTION-MATRIX,PETCORE-HANDOFF-PLAN,PETCORE-SPEC,PETCORE-ROADMAP,PETCORE-MAIN-PARITY-BACKLOG}` | 各 1–2 行 | 把「默认安装/默认选中」统一改成「可选安装（默认不勾）」。 |
| `petcore/AGENTS.md` | +1 / −1 | 红线补「默认不勾选（`Flags: unchecked`）」。 |
| `docs/PETCORE-LOG.md` / `PETCORE-LOG-INDEX.md` | +68 / +6（含 L035） | L034 记录本次回退，L035 记录编号统一。 |

### 为什么回退

用户口径（本轮重构的原始需求）：安装向导里可勾选，**不勾选就真不会安装到本地**。
P2 把 5 个任务改成默认选中，虽然仍可取消，但默认行为与口径相反，且会让「core 保持
最小、业务功能按需装」的边界被默认值模糊掉。

### 性能分析

只改 Inno Setup 任务的初始勾选状态，不影响打包体积、安装步骤、运行时依赖，也没有
新增 IO/线程/网络。安装后的行为差异仅是「默认少写 5 个目录」，磁盘占用只会更小。

### 实机运行记录

```text
pytest tests/test_petcore_installer.py -q          → 7 passed in 1.93s
pytest tests/test_petcore_*.py tests/test_architecture.py \
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
                                                   → 985 passed in 62.44s
ruff check pet/ tests/ petcore/                    → All checks passed!
python -m petcore --check                          → exit 0
```

安装器重新出包（增量 `-Installer`）：`dist/dsh-pet-core-setup.exe` **192,675,082 字节**，
主 exe `Subsystem=2`，打包后 `--check` exit 0、`menu_template=json`、`diagnostics=[]`、
`self_talk_images.readable=24`；冻结包内 `market --offline list` 与 `market doctor` 正常。
向导勾选框的**实际初始状态**仍需在真实安装时人工确认一次（iss 语义测试只校验源码文本）。
