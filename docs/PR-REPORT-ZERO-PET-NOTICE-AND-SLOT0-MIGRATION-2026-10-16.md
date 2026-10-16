# PR 报告：零宠物启动不再静默 + slot0 迁移不再「既没迁走又删掉」

> **基线**：`6a68570`（`origin/main` 顶端，含 #272/#274/#276–#281/#285；
> 本片开工时是 `0b7152d`，收口前合入了 `6a68570`）
> **分支**：`fix/zero-pet-notice-and-slot0-migration`　**日期**：2026-10-16
> **范围**：实现 3 个文件（`+92 / −9`）、测试 2 个文件（1 个新增，`+225 / −0`）、
> 文档 2 个文件（`docs/INDEX.md` 登记、本报告）
> **关联**：GitHub issue [#286](https://github.com/MerZlin/dsh-pet-indesktop/issues/286)；
> 相关既有报告 [`PR-REPORT-CURSOR-PASSTHROUGH-2026-10-15.md`](PR-REPORT-CURSOR-PASSTHROUGH-2026-10-15.md)（#277）、
> [`PR-REPORT-SLOT0-SETTINGS-271-2026-10-15.md`](PR-REPORT-SLOT0-SETTINGS-271-2026-10-15.md)（#274）、
> [`PR-REPORT-SETTINGS-POLISH-2026-10-16.md`](PR-REPORT-SETTINGS-POLISH-2026-10-16.md)（全量红先例）

## 一、核心特性

issue #286 的现场是「**进程在、托盘在、桌面上什么都没有**」，而且从用户侧完全无法自查：
日志停在 `进入事件循环`、CPU 累计 **0.72 s 且 5 s 不增长**、无线程活动、无子进程、无 TCP
连接——观感等同于「启动失败或被安全软件拦了」。根因不是某个异常被静默吞掉（报告者这一点
的推断不成立，见 §三），而是**「一只宠物都没有」这个合法状态本身不报错、不打日志、不给任何
提示**。本片把它变成可观测的，并顺手修掉同一族数据卫生问题：slot0 迁移在目标档案已存在时
**不写目标却照样清源**。

| # | 能力 | 说明 |
|---|---|---|
| 1 | overlay 零宠物不再静默 | 启动收口处若一只 sprite 都没有：WARN（含活跃集合与配置目录）+ 托盘 tooltip 说实话 + 恢复窗开着且空白时补一句说明 |
| 2 | legacy 零宠物不再静默 | `_build_empty_pet_tray`（只剩托盘、没有捕获窗那条路）补同样的 WARN + 托盘 tooltip |
| 3 | slot0 迁移不再丢数据 | `already-exists` 支不再清源；未迁走的每宠键如实登记在 `retained_keys`，`copied_keys` 只记真写进档案的 |

**红线 / 不变量**：

1. **零宠物仍是合法状态**，本片**不**替用户造宠物、**不**改活跃集合、**不**碰任何档案
   ——只陈述与指路（与 `PR-REPORT-SLOT0-SETTINGS-271` 的「不覆盖、不自动修复」同口径）。
2. **`_slot0_profile_diagnosis` 一个字节都不写**。它是"slot0 档案降级"的专用诊断源，
   被 `_spawn_failure_text`、托盘 tooltip、恢复窗三处读；往下塞别的东西会顶掉坏档案路径
   （见 §三「自查到的一处自伤」）。
3. **迁移的目标档案在 `already-exists` 支一个字节都不许动**（既有用例
   `test_slot0_migration_never_overwrites_existing_profile` 逐字节钉死）。本片只做减法：
   不再删源，绝不新增对目标的写入。
4. **空合成窗必须处处穿透**（零 sprite 时逐像素判据恒为 `True`）。这是既有设计，本片钉住
   它而不是改动它——一个看得见又不可穿透的全屏置顶窗才会造成"整个桌面点不动"。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `pet/overlay_shell.py` | +54 / −0 | ① `_build` 尾段（`_slot_signature_cache` 之后）新增一行调用 `self._announce_no_pets_if_empty()`——放在 `_build_tray()` **之后**，因为托盘是零宠物态下唯一的可见入口，提示要能改到它；② 新增 `_announce_no_pets_if_empty`（`_all_sprites()` 非空即返回；否则 WARN + 托盘 tooltip + 恢复窗**空白时**补文案）与 `_no_pets_reason`（按三条已知入口如实陈述原因，**不猜**：优先用 slot0 降级诊断，其次"活跃清单为空"，最后"清单里的宠物都没能建起来"）。整段是**一个 hunk**，不含任何多屏几何改动。 |
| `pet/app.py` | +14 / −0 | `_build_empty_pet_tray` 补 docstring 说明"这里必须留一条 WARN"、补 WARN（含活跃集合与配置目录）与托盘 tooltip 实话化；菜单与恢复窗的既有可见入口一字未动。 |
| `pet/pet_profiles.py` | +24 / −9 | `migrate_slot0_profile`：`already-exists` 支**不再清源**（旧口径"不写目标却照样清源"= 把源每宠值直接删掉且无处可读）；`retained_keys` 登记未迁走的那批键、`copied_keys` 只记真写进档案的；模块头与函数 docstring 同步改口径。`retained` 显式初始化（首版漏了，`created` 支会 `UnboundLocalError`，见 §五）。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---:|---|
| `tests/test_no_pet_startup_notice.py`（新增） | +201 / −0 | 7 项：overlay 零宠物 WARN + 点名配置目录、恢复窗说明与托盘 tooltip、有宠物时不打该 WARN（对照）、**空合成窗处处穿透**守卫、**零宠物不得占用 slot0 诊断源**（含下游契约：生成失败仍须带该槽档案路径）、legacy 零宠物 WARN + 点名配置目录、legacy 恢复入口不许被日志改动挤掉。 |
| `tests/test_pet_profiles.py` | +24 / −0 | `already-exists` 时目标字节不变 **且** 源每宠键原样保留、`retained_keys` 如实登记、`copied_keys` 为空。 |

### 未改动（明确不做）

- `pet/window_placement.py`、`pet/pet_sprite.py`、`pet/overlay_window.py`、`pet/platform_win.py`：
  **一个字没动**。issue #283（多屏拖拽在 sprite 世界回归）的修复已从本片**拆出**单独留存，
  不在本提交内——它的核心能力本机单屏无法真机验证，不该与本片一起进。
- `tests/test_overlay_shell.py` 等既有 overlay 用例：**一条都没改**。
- 全量里那 5 条既有红（`test_module_level_validation` ×2、`test_overlay_instance_gate` ×1、
  `test_settings_stale_form_exit` ×2）：本片不修，归因见 §六。

## 三、实现要点

**为什么修法是「说出来」而不是「强行造一只」。** 零活跃宠物是**合法**状态，有三条真实入口：
用户点过托盘「退出这只」并持久化、`overlay-active-pets.json` 损坏或版本不认识（
`load_active_set` 返回空列表）、slot0 档案降级被剥出活跃集。强行生成等于替用户改意图，也与
"不覆盖、不自动修复"的档案纪律冲突。能做的补偿是**可观测**：日志给排查（含活跃集合与配置
目录这两个最能定位的字段），托盘 tooltip / 恢复窗给用户。这也正是报告者唯一的明确请求
（"请至少把这几步的异常输出到 WARN/ERROR"）。

**报告者的推断哪里不成立。** 他列的四条初始化日志（`素材加载完成` / `恢复位置` /
`全屏监视线程` / `[VIS] 桌宠显示`）**全是 legacy 专属**，overlay 拓扑根本不打印（唯一可
grep 的拓扑行是 `pet/app.py` 的 `渲染拓扑: overlay(单合成窗)`）。所以"异常被静默吞掉"这个
方向偏了：真问题是**没有一只宠物这件事本身不报错**。另外 `PET_RENDER_TOPOLOGY=layered`
**从来不是合法值**——只有大小写不敏感的 `legacy` 判 legacy，其余任何非空值都判 overlay，
全历史从未存在过 `layered` 这个取值；他把 `layered` 当逃生门用属误解，本片不改这个判定
（改它等于改 env 契约），只把事实写清。

**为什么迁移选择「不清源」而不是「把源值合并进目标」。** 目标档案在 `already-exists` 支上
**不许被写**（既有用例逐字节钉死），所以"补目标缺的键"这条路会破掉一条已发布的契约。
不清源是纯减法（只是不再删东西），零写入风险；而"源全局键暂留"本就是既有设计承认的过渡
状态——见 `test_migrated_profile_is_the_truth_not_the_retained_global_keys` 的 docstring：
"读侧真值只有档案"。

### 自查到的一处自伤（保留对照）

零宠物提示的**首版**把"没有可显示的桌宠：…"也写进了 `OverlayShell._slot0_profile_diagnosis`。
那一条属性是**专用诊断源**——`_spawn_failure_text` 在它非空时优先引用它，从而让"生成失败"
的说明带上坏档案路径（`pet/overlay_shell.py:4480-4481`）。塞进一句笼统文案等于把那条线索
顶掉：`tests/test_slot0_lifecycle.py::test_spawn_failure_reaches_the_recovery_window_when_no_pet_is_visible`
当场红（全量分片里抓到的，基线该文件 51 passed → 本片 1 failed）。

定性：**不是测试太严，是我的改动越权**——把一个属性的语义边界跨用了。修法是收敛到"只走
日志 + 托盘 tooltip + 恢复窗**空白时**补一句"，`_slot0_profile_diagnosis` 一个字节不写。
同一轮补了两条守卫：一条钉"零宠物不得占用 slot0 诊断源"，一条把下游契约直接钉住
（零宠物之后 `_spawn_failure_text(0, exc)` 必须**仍然带该槽档案路径**）。

教训：**给"诊断/状态"这类共享字段写入前，先找全它的读方。** 与既有先例同源
（[`PR-REPORT-ISLAND-HOVER-OSCILLATION-2026-10-13.md`](PR-REPORT-ISLAND-HOVER-OSCILLATION-2026-10-13.md)
的"给悬停触发写判据前必读"）。另一个副产物：单跑聚焦族（当时 203 passed）**发现不了**这类
跨文件的字段跨用，只有全量门能。

## 四、性能分析

**方法（可复现）**：

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 \
  .venv/Scripts/python.exe .scratch/probe_perf_nopet.py
```

环境：Windows 11，Python 3.12.10，PySide6/Qt 6.12，offscreen，n=20000×5（稳态）/
n=2000×5（异常态）取中位。

| 路径 | 归属 | 实测 | 触发频率 |
|---|---|---|---|
| `_announce_no_pets_if_empty` 早退（有宠物） | 新增（稳态） | **0.233 µs/次** | 每次构建一次 |
| `_announce_no_pets_if_empty` 全路径（零宠物，含一次 `logging.warning`） | 新增（异常态） | **53.233 µs/次** | 仅"确实一只都没有"时，一次性 |

legacy 侧的 WARN 是一条 `logging.warning`（`_build_empty_pet_tray` 本来就要建托盘与菜单，
日志相对那次托盘构造可忽略）。逐条回答模板四问：

1. **稳态开销**：有宠物时新增路径就是一次 `self._all_sprites()` 判空 —— **0.233 µs**，
   每次构建触发一次（不是每帧、不是每次 tick）。相对构建期（`_build` 建行为/碰撞/物理/
   探头/彩蛋/托盘，毫秒级）完全在噪声内。
2. **新增路径成本与触发频率**：零宠物时才走全路径，**53.2 µs**（几乎全部是那一次
   `logging.warning` 的格式化与写盘），每次构建一次。零宠物是异常态、不是常驻态。
3. **有无新的系统调用/网络/磁盘/线程**：**没有**。新增的是一次日志写入与一次
   `setToolTip`（Qt 内存态）。迁移侧反而**减少**一次 `cwl.atomic_write_json(src)`——少一次
   磁盘写与一次锁内落盘，这是本片唯一的 I/O 净变化。
4. **内存与缓存**：零新增容器与缓存；`_announce_no_pets_if_empty` 只在栈上拼一个字符串，
   `_no_pets_reason` 返回一个新字符串。`retained_keys` 是结果对象上的一个元组（既有字段，
   此前恒为空）。

## 五、实机运行记录

本机 Windows 11，真实环境（非 CI、非 mock）。**如实登记：issue #286 的现场无法在本机复现**——
报告者是 Windows 11 + 2560×1600 @150% 从 v4.2.1 覆盖升级，且失效当下的状态需要用
`GetWindowLongW(hwnd, GWL_EXSTYLE) & 0x20` 取一次读数才能分辨"穿透态"与"吞点击态"；
本机是单屏、且没有那台机器的历史配置目录。本片能取到的是**代码级与断言级**的确定性证据：

- **零宠物状态确实存在且可达（源码级）**：`load_active_set` 对 `corrupt` /
  `unsupported-version` / `unreadable` 一律返回 `()`（`pet/pet_profiles.py:539-544`），
  而 `_build` 里 `if 0 in self._remembered_active:` **没有 else**——这一支在改造前既不报错
  也不打日志。新增用例构造的就是这个状态（空活跃集合 + 坏 `config-slot-0.json`）。
- **红→绿取证（撤掉产品改动即红）**，两批分别执行：

  | 产品改动 | 撤掉后 | 断言 |
  |---|---|---|
  | `pet/pet_profiles.py` | 1 failed | `assert remaining[key] == source[key]`（源每宠键被删掉） |
  | `pet/overlay_shell.py` + `pet/app.py` | 3 failed / 3 passed | WARN 与诊断缺失；3 个守卫（有宠物不报警、空窗穿透、legacy 恢复入口）前后皆绿 |
  | 零宠物提示首版（越权写 `_slot0_profile_diagnosis`） | 3 failed | 含 `tests/test_slot0_lifecycle.py` 那条既有用例，见 §三「自伤」 |

- **实现过程中自己踩到并修掉的两个真实缺陷**（都留在报告里不删）：
  1. `retained` 未在 `created` 支初始化 → `UnboundLocalError`，被
     `tests/test_pet_profiles.py` 当场抓出（首轮 `6 failed`）。
  2. 零宠物提示越权写共享诊断字段 → 被全量分片抓出（见 §三）。
     两次都是"跑门禁才暴露"，不是 review 出来的。
- **用户可见行为的确认**：无。本机没有真实用户参与，也没有 #286 报告者那台机器；
  托盘 tooltip / 恢复窗文案的可见性由 offscreen 下的 `QLabel.text()` 与
  `QSystemTrayIcon.toolTip()` 断言覆盖（能证明赋值正确，**不能**证明用户在真桌面上看得见）。
  `#286` 的最终确认应由维护者在下一个版本包上请报告者复测（见 §七）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet/ tests/` | **All checks passed!** |
| 聚焦（本片） | `pytest -q tests/test_no_pet_startup_notice.py tests/test_pet_profiles.py tests/test_slot0_lifecycle.py` | **124 passed** |
| 受影响族 | `pytest -q tests/test_no_pet_startup_notice.py tests/test_pet_profiles.py tests/test_slot0_lifecycle.py tests/test_overlay_shell.py tests/test_overlay_window_capabilities.py tests/test_overlay_peripherals.py tests/test_overlay_tray_icon.py tests/test_overlay_tray_routing.py` | **226 passed** |
| 受影响时序族满载 3 遍 | 16 个 CPU 繁忙进程打满 16 逻辑核后重跑上一条 | **226 passed × 3**（wall 30 / 27 / 30 s） |
| 全量 | `python scripts/ci_shards.py`（四分片，Windows 已知 access violation 的既有处置） | **5 failed / 7727 passed / 17 skipped**——5 条**全部**是既有的上下文脆弱，见 §八 归因 |
| 架构红线 + 文档纪律 | `pytest -q tests/test_architecture.py tests/test_pr_report_discipline.py` | **176 passed** |

**断言有效性**：三批红→绿证据已在 §五 逐条登记。三条守卫（有宠物时不打该 WARN、空合成窗
处处穿透、legacy 恢复入口仍在）在产品改动前后**都绿**——它们防的是"为了消灭静默而误报"
与"为了让空窗可点而改坏穿透"，属于必须双向成立的断言。

## 七、已知限制与后续

1. **`#286` 的「整屏鼠标失效」没锁定到唯一状态**。报告者同时说"exstyle 含
   `WS_EX_TRANSPARENT` 常驻"与"整屏鼠标失效"，这两句互相冲突：前者是穿透态（桌面正常、
   宠物点不到），后者是 `_press_global` 卡死导致的"全屏吞点击"态。
   `GetWindowLongW(hwnd, GWL_EXSTYLE) & 0x20` 一位就能分辨，但**需要报告者在失效当下取
   一次读数**。本片做的是让零宠物状态可观测（本片）+ 基线已自带 #277 的穿透卡死修复与
   #274 的 slot0 路由修复（**未发布**，v4.3.0 里没有）——所以下一步是发布一个带它们的版本
   请报告者复测，而不是继续盲改状态机。
2. **零宠物时本片不隐藏那个全屏空窗**。改动它需要同时处理"后来生成宠物时把窗显示回来"
   的耦合，且本机单屏无法验证真桌面观感；而空窗在既有实现下**恒为穿透**（本片已用守卫钉住），
   即不会吞桌面点击。触发条件是有人报告零宠物时桌面受影响，届时应做的是"零 sprite 不 show
   窗口 + 生成时补 show"。
3. **采集到的诊断只在有日志/托盘/恢复窗时可见**。若用户既没有托盘又看不到恢复窗（极端
   环境），这条 WARN 是他唯一能提供的证据——这是刻意的取舍，不额外造第四个入口。
4. **issue #283（多屏拖拽在 sprite 世界回归）与 #275（macOS legacy 三缺陷）不在本片**。
   #283 的修复已完成并单独留存（`.scratch/keep-283/`：完整 diff、两个测试文件、报告全文），
   它的核心能力本机单屏无法真机验证，应单独走一次带假屏证据的 PR；#275 需要 macOS 真机，
   且报告者的第二条机制经代码核对**不成立**（`was_dragging` 为真时 `_on_click()` 根本不会
   被调用，`pet/window.py:3278-3308` vs `:3309`）。

## 八、风险与回滚

**影响面**：overlay 与 legacy 两条拓扑在"零活跃宠物"时的日志与提示文案；slot0 迁移在
"目标档案已存在"时的源清理行为。**不影响任何正常路径**（有宠物时的稳态开销 0.233 µs，
迁移在 `created` 支逐位不变）。

**配置迁移**：**没有新增或修改任何配置键**，`docs/SETTINGS-CHANGE-GATES.md` 的门不触发。

**回滚**：`git revert` 本片即可，无残留状态。唯一需要留意的是**迁移侧**：回滚后
`already-exists` 又会清源，但因为本片不写源，回滚不会让已经保留下来的源键丢失
（旧行为只删不加，回滚等于恢复"会删"的旧语义，不影响已落盘数据）。

**分支与合并**：本片开工基线是 `0b7152d`，收口前已合入 `6a68570`（#285 播放器路径）。
合并冲突只有 `docs/INDEX.md` 一处（两方都在"PR 报告存档"表头下新增行），解法是**两行都留**：
upstream 的 `PR-REPORT-MUSIC-PLAYER-PATHS-2026-10-16.md` 行 + 本报告行。§六 的全部门禁数字
都是在**合并后的树**上重跑得到的。

### 交付补记（合并后重跑的门禁）

- `ruff check pet/ tests/`：**All checks passed!**；`git diff --check`：干净。
- 本片聚焦（notice + profiles + slot0_lifecycle）：**124 passed**。
- 受影响族：**226 passed**；满载 3 遍（16 个 CPU 繁忙进程打满 16 逻辑核）：
  **226 passed × 3**（wall 30 / 27 / 30 s）。
- 架构红线 + 文档纪律：**176 passed**。
- 全量四分片：**5 failed / 7727 passed / 17 skipped**
  （分片明细 1744+1971+1980+2032 passed，9+3+3+2 skipped）。本片新增的
  `tests/test_no_pet_startup_notice.py` 落在分片 2 且**通过**。

**全量红归因（跑基线对照，不靠推断）**：这 5 条与**同一套四分片跑在 `origin/main` 上**
的失败集合逐条相同、落点分片也相同，且**单独跑全过**、文件全在本片改动之外：

| 失败用例 | 本片（合并后） | 基线 `origin/main` | 归属 |
|---|---|---|---|
| `test_module_level_validation.py::test_catalog_animation_count_guard_survives_optimize` | 分片 2 红 | 分片 2 红 | 既有 |
| `test_module_level_validation.py::test_festival_id_guard_survives_optimize` | 分片 2 红 | 分片 2 红 | 既有 |
| `test_overlay_instance_gate.py::test_real_second_process_refused_on_overlay_topology` | 分片 3 红 | 分片 3 红 | 既有 |
| `test_settings_stale_form_exit.py::test_product_confirm_discard_reads_the_real_button_click` | 分片 4 红 | 分片 4 红 | 既有 |
| `test_settings_stale_form_exit.py::test_discard_unverified_notice_is_a_real_visible_box` | 分片 4 红 | 分片 4 红 | 既有 |

其中 `test_discard_unverified_notice_is_a_real_visible_box` 已有先例登记
（[`PR-REPORT-SETTINGS-POLISH-2026-10-16.md`](PR-REPORT-SETTINGS-POLISH-2026-10-16.md) §六之一：
"0ms 探针 + 前序用例事件循环污染"，并给了"基线只加 30ms sleep 也复现同一条红"的对照）。
**本片不修这一族**；按 AGENTS.md 的 CI 纪律，该由维护者决定是隔离出主套件还是单独办。
基线全量日志：`.scratch/full-suite-baseline.log`；本片全量日志：`.scratch/full-suite-286-merged.log`。
