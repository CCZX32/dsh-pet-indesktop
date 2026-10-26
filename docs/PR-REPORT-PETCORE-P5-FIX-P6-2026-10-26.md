# petcore P5 修复 + P6 迁移收尾与 GPU/FPS 真探针（2026-10-26）

> **基线**：`1c1507f1`（P5 收口 + 远端复验）
> **分支**：`feat/petcore-vpet-architecture`  **日期**：2026-10-26
> **范围**：`petcore/`、`tests/test_petcore_*.py`、`scripts/build_petcore.ps1`、必要文档与 `petcore/AGENTS.md`；未修改旧 `pet/`，未上传 Release，未切换默认入口。

## 一、交付内容

本轮先把 P5 的「报告说做完、实际没接线」补齐，再做 P6 的两块：旧数据全量迁移、GPU(PDH)/FPS(PresentMon) 真实探针。

| # | 能力 | 结果 |
|---|---|---|
| 1 | 余额结果投递 | 已修：`QTimer.singleShot` 两参重载从工作线程不触发（已复现），改为 `QtScheduler` 信号排队；首次点击即有结果，失败原因能上屏 |
| 2 | 余额取消死锁 | 已修：`cancel()` 持锁调 `Future.cancel()` 会在同线程同步跑 done_callback 再抢同一把锁（已复现挂死）；改为锁外取消 |
| 3 | 菜单入口 | 已修：`show_balance` / `check_update` 注册了但不在模板里，永远不会渲染；现在分别落在「桌宠控制」与「工具与帮助」 |
| 4 | 岛避让 | 已修：改用桌宠 `body_rect()`（不再用整窗 `frameGeometry`），自动挪动**不落盘**，桌宠走开 3 拍后回原位 |
| 5 | 更新链路 | 已修：`check()` 可取消、排队期间的取消不再被 worker 开头的 `clear()` 吞掉、`install()` 重算摘要并靠校验侧车支持重启后安装、源码运行不给点亮安装按钮、每条状态只写一次消息 |
| 6 | 段语义 | 已对齐主分支：`unsupported`/未接入探针的 GPU/FPS **不占位**，原因写在卡片一行（原来会退化成 `--` + 告警红） |
| 7 | 性能计数出口 | 已修：计数器原来只写不读；`--check` 现在输出 `performance` 段，`coalesced_updates` 不再恒等于 `ui_updates` |
| 8 | `api_service_id` | 已修：原来只读不写；设置「API 与账户」新增「余额服务」下拉，按当前宠物落盘 |
| 9 | 旧数据迁移 | 新增 `petcore/migration/`：配置 / slot / 活跃集合 / 会话 / 待办 / API 规格 / 凭据引用七域，标记幂等、dry-run、回滚、`petcore migrate` 子命令与 `--check` 诊断 |
| 10 | GPU 真探针 | 新增 `platform/gpu.py`（ctypes PDH + DXGI 名字）+ `gpu_monitor.py`（1 Hz 硬下界）；本机真实读到 AMD Radeon 780M 的 3D 引擎占用 |
| 11 | FPS 真探针 | 新增 `platform/fps.py`（PresentMon 子进程 + 1 秒事件窗 + 进程级单会话）+ `fps_permission.py`（一次性 UAC 加 Performance Log Users） |
| 12 | 探针接线 | 新增 `ui/probes.py`：岛报「还需要哪些段」，宿主启停采样器并逐秒推快照；隐藏/折叠/关段即停采 |
| 13 | 设置与打包 | 岛的指标段放开 `GPU`/`帧率`；新增「游戏帧率权限」行；`build_petcore.ps1` 带 `resources/presentmon` 并过 `verify_presentmon.py` 三道门 |

**红线 / 不变量**：不修改旧 `pet`；`petcore/platform/*` 零 Qt、零网络库；只有 `ok` 带读数，其余一律 `None` + 具体原因（不伪造 0）；迁移只补缺不覆盖、原文件先备份、失败不写坏文件；密钥不落 `config.json`/`api.json`/日志/报告；不自动提权、不常驻提权助手。

## 二、修改文件说明

### 修改（`git diff --numstat`）

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `petcore/ui/island.py` | +116/−47 | 探针 `unsupported` 不占位、卡片原因行、避让不改写用户位置、探针启停回调、自动避让回原位 |
| `petcore/ui/app.py` | +76/−9 | `gui_dispatch` 投递通道、`QtScheduler`、避让用 `body_rect()`、探针 hub 接线、更新消息去重、安装门禁、余额错误可读 |
| `petcore/ui/settings/pages_core.py` | +84/−2 | 指标段放开 GPU/帧率、新增游戏帧率权限行（后台线程等 UAC） |
| `petcore/ui/settings/page_api.py` | +61/−0 | 余额服务下拉与状态提示（`api_service_id` 唯一写入点） |
| `petcore/ui/settings/page_about.py` | +14/−4 | 状态码翻中文、安装按钮按 `can_auto_install` 门禁、取消按钮覆盖检查态 |
| `petcore/update/service.py` | +67/−5 | `reset_cancel`、`check()` 可取消、`download()` 不清取消、校验侧车与摘要重算 |
| `petcore/update/model.py` | +31/−1 | `STATE_LABELS` / `describe_state`，界面不再外露 `idle` 这类内部串 |
| `petcore/update/__init__.py` | +9/−1 | 导出新符号 |
| `petcore/account/presenter.py` | +6/−1 | 锁外取消（死锁修复） |
| `petcore/cli.py` | +52/−0 | `migrate` 子命令、`--check` 的 `performance` 与 `migration` 段 |
| `petcore/performance.py` | +6/−1 | `as_dict()`、`gpu_samples`/`fps_samples` 计数 |
| `petcore/menu_templates/petcore-default-v1.json` | +2/−0 | 两个新菜单项落位 |
| `petcore/ui/menu_layout.py` | +2/−0 | 内置兜底布局同步 |
| `scripts/build_petcore.ps1` | +18/−0 | 打包 PresentMon 并在构建前/产物后各验一次 |

### 新增

| 文件 | 行数 | 说明 |
|---|---:|---|
| `petcore/migration/__init__.py` | 379 | 框架：域顺序、标记幂等、dry-run、备份/回滚映射 |
| `petcore/migration/config_data.py` | 238 | 全局配置、slot（含 slot0 并入全局）、活跃集合 |
| `petcore/migration/sessions.py` | 236 | 旧会话 ISO 时间 → schema 1 |
| `petcore/migration/todos.py` | 386 | `todo_items.json` → `reminder.todo` v2（写出前用扩展自己的 `validate()` 校验两遍） |
| `petcore/migration/accounts.py` | 513 | `chat.providers` → `api.json`；旧钥匙串 ref → 新 owner:key |
| `petcore/platform/gpu.py` | 1098 | PDH 读数器 + DXGI 名字 + `GpuSample` 不变量 |
| `petcore/platform/gpu_monitor.py` | 112 | `SamplingLoop` 采样器，间隔钳到 1–60 秒 |
| `petcore/platform/fps.py` | 1962 | 后端契约、命令行、1 秒事件窗、单会话生命周期、孤儿防护 |
| `petcore/platform/fps_permission.py` | 513 | 令牌/账户成员判定、一次性 UAC 授权、退出码映射 |
| `petcore/ui/probes.py` | 217 | 岛的探针 hub：样本 → 段快照、启停、前台目标解析 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---:|---|
| `tests/test_petcore_balance.py` | +91/−0 | 取消不死锁（daemon executor 复现原 bug）、工作线程投递真落到 GUI 线程 |
| `tests/test_petcore_update.py` | +98/−1 | 取消不被吞、`check()` 取消、校验侧车、换包被摘要拦下、无侧车拒装 |
| `tests/test_petcore_island_p5.py` | +55/−4 | 避让不落盘且回原位、`unsupported` 不占位 + 卡片原因 |
| `tests/test_petcore_menu_layout.py` | +9/−0 | 两个新动作必须真在模板里 |
| `tests/test_petcore_migration*.py` | +1139 | 框架/配置/会话/待办/API+凭据/整链七域 |
| `tests/test_petcore_gpu_probe.py` | +261 | 不可用语义、聚合口径、线程纪律、间隔钳制、真实读数 |
| `tests/test_petcore_fps_probe.py` | +544 | 1 秒窗、后端缺失、命令行、权限映射、会话复用 |
| `tests/test_petcore_probe_hub.py` | +150 | 启停闸门、样本翻译、按需集合 |

## 三、实现要点

### 余额投递与取消

`gui_dispatch(scheduler)` 是唯一投递入口：`QtScheduler` 用信号从工作线程排队到 GUI 线程，回调一定在 GUI 线程执行。`BalancePresenter.cancel()` 先在锁内摘掉 future 与代次，再在锁外 `future.cancel()`——`Future.cancel()` 对 PENDING 任务会在调用线程同步跑 done_callback，持锁调用必然自锁（退出路径上就是这一步挂死）。

### 更新链路

`reset_cancel()` 只在**提交任务时**调用，`check()`/`download()` 不再自己 `clear()`，否则排队期间按下的取消会被 worker 开场吞掉。`check()` 在每个源之前看取消。下载完成后写 `.verify.json` 侧车（name/size/sha256），`install()` 每次重算摘要——既支持重启后安装，也能挡住下载后被替换的包；源码运行与非 Windows 在 `install()` 与设置按钮两处都拒绝。

### 迁移

幂等只认 `<root>/migration.json` 的 `completed`，不认「目标文件不存在」（后者在第一次启动后永久失效）。`MigrationContext` 负责备份、原子写、失败记账与回滚映射（目标原本不存在时 backup 记空串 = 回滚删除）。配置域**只补缺**并直接写合并后的原始字典——如果走 `Config.save()`，`DEFAULTS` 会把每个键都填上，第二个域里就再也补不进去（这是本轮自查发现并修掉的坑）。凭据域只做钥匙串到钥匙串的搬迁，旧 `config.json` 里的明文 key 不搬。

### GPU

`GpuReader` 惰性建 query、query 属于创建线程、跨线程 `read` 明确拒绝（owner 线程已退出时由新线程接管并重建基线，否则「停采→恢复」会永久失效）。聚合口径与主分支一致：引擎级跨进程求和 → 适配器取 max → 跨适配器取 max。`GpuSample.__post_init__` 钉死不变量：词表外状态降 `error`、`ok` 却无有限读数降 `error`、非 `ok` 强制丢读数。

### FPS

后端是随包的 `PresentMon-2.6.0-x64.exe`，用 `--output_stdout` 的 CSV 行；命令行为「必需六参 + `--process_id/--process_name`」，禁 `--stop_existing_session/--restart_as_admin/--v1_metrics/--v2_metrics`；停止走官方 `--terminate_existing_session`，并用 Windows Job 的 `KILL_ON_JOB_CLOSE` 防孤儿。读数口径：`MsBetweenPresents` → `fps = 1000/mean(间隔)`，1 秒**事件时间**窗、至少 2 帧、至少 0.1 秒跨度，按 `(pid, swapchain)` 分窗取仍活着的最忙链。

### 岛与探针

岛只在 `_sync_sampling()` 里算出「还需要哪些段」（可见 + 已启用 + 未被折进 `+N`），通过 `set_probe_sync_callback` 交给宿主；宿主据此 start/stop 采样器，空集时同时清掉段快照。推送节拍 1 秒、只读缓存快照，GUI 线程不做 syscall。FPS 目标按前台窗口 pid 解析，最多每 5 秒一次，且排除桌宠自身进程。

## 四、性能分析

**方法**：Windows 11 / Python 3.12.10 / PySide6 6.12.0；`.venv` 直跑，offscreen Qt。原始输出见 `.scratch/petcore-full.log`、`.scratch/probe_gpu_real.py`、`.scratch/probe_fps_real.py`。

| 路径 | 实测 | 触发频率 | 结论 |
|---|---|---|---|
| GPU 单拍读取（稳态） | 2.14 / 3.16 / 3.49 ms（min/median/max，10 拍） | 1 Hz，且仅在岛可见 + 段启用 | 读取只在采样线程，GUI 只拿快照；1 Hz 下占用 < 0.4% 单核 |
| GPU 冷启首拍 | 283.6 ms | 每个 `GpuMonitor` 一次 | 落在采样线程，不进 GUI 线程；`poll()` 由调用线程付这笔成本，宿主只用 `start()` |
| FPS 采集 | 未起会话（权限 `missing`） | 段可见时 | 本机普通权限下 PresentMon 退出 `access denied`，样本 `state=error`，跳过采集 |
| 岛探针推送 | 1 次/秒（GPU + FPS 各一次段快照） | 段可见 | 与已有 1 Hz 采样同拍，不新增定时线程 |
| 迁移单域 | 配置/会话/待办/凭据均 < 0.1 s（`tmp_path` 端到端 41 测试 1.26 s） | 一次（标记后不再跑） | 只在显式 `migrate` 或首次启动跑；`--check` 只读标记，不跑迁移 |
| 新增线程 | GPU 1 条采样线程（随段启停）、FPS 1 条采样 + 每会话 1 条读取线程 | 段可见时 | 隐藏/折叠/关段即 `stop()`；无新增常驻线程 |

内存：GPU 常驻一只 PDH query（`stop()` 不关闭，反复开关不增长句柄）；FPS 未起会话时无常驻对象。未观察到随重启增长。

## 五、实机运行记录

### 门禁

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `./.venv/Scripts/ruff check petcore tests scripts` | `All checks passed!` |
| petcore 全量 | `QT_QPA_PLATFORM=offscreen pytest -q $(ls tests/test_petcore*.py)` | **1613 passed in 117.81s，exit 0**（本轮中途 1612 的差异是随后补的一条回滚回归） |
| Core 诊断 | `python -m petcore --root .scratch/check-mig --check` | exit 0，`menu_template=json`、`diagnostics=[]`、`performance` 与 `migration` 段存在 |

### GPU 真实读数（本机实体机）

```
dxgi adapters: 3
  0x00000000_0x0000DE43 AMD Radeon 780M Graphics software=False
  0x00000000_0x00019B1A AMD Radeon 780M Graphics software=False
  0x00000000_0x0000FDA8 Microsoft Basic Render Driver software=True
cold_first_read_ms: 283.6  state=sampling percent=None
t1: state=sampling percent=None
t2: state=sampling percent=None
t3: state=ok percent=5.256754413193459 adapter='AMD Radeon 780M Graphics' eng='3D'
t4..t6: ok 5.58 / 5.86 / 7.00
stop waited: True
```

前两拍是基线（`sampling`），第三拍起 `ok`；这是真实读数，不是伪造 0。

### FPS 真实路径（本机普通权限）

```
platform_supported: True
backend_state: ('', '')            # 后端文件在、sha256 与架构都对
permission check: missing           # 当前账户不在 Performance Log Users
foreground pid: 21224 process: Kimi Code.exe
t1..t4: state=error fps=None reason='PresentMon 权限不足：access denied —— 需要管理员权限或 "Performance Log Users" 组成员'
waited: True
```

与主分支 `docs/PR-REPORT-GAME-FPS-2026-10-11.md` 记录一致：没有授权时起不了 ETW 会话，所以**本轮不宣称 FPS 读数验收通过**；授予权限后需重新登录再看。界面侧已有「授予帧率权限」按钮（后台线程等 UAC，点「否」= 取消）。

### 未验证

- 冻结包的 PresentMon 是否被 PyInstaller 放到 `_internal/resources/presentmon`：构建脚本会在产物存在时二次校验，不存在只打警告；**本轮未重建安装包**。
- 真实桌面下的岛交互（拖拽、避让手感、卡片滚动）仍只有 offscreen Qt 覆盖。
- 授予 Performance Log Users 后的真实帧率读数（需要重新登录）。

### 迁移 dry-run 实机（本机真实旧数据，只读）

```
$ python -m petcore --root .scratch/mig-dry migrate --dry-run
legacy_roots: ['...\\dsh-pet-standalone', '...\\dsh-pet-standalone-webm-chat']
counts: {already_migrated: 1, migrated: 10, not_found: 4, skipped_invalid: 2}
  config      migrated   would-migrate:keys:always_on_top,animation_gap_seconds,click_through,...
  slots       migrated   would-migrate:keys:bubble_text_scale,character,click_sound,...
  active_pets not_found
  sessions    migrated   dropped:provider_id,system_prompt,pinned
  todos       not_found  slot:0
  api         migrated   dropped:temperature,max_tokens,thinking,reasoning_effort;balance:deepseek
  api         skipped_invalid dropped:default_system_prompt,web_search
  credentials migrated   （旧钥匙串 ref 命中，dry-run 不写）
  credentials not_found  missing
```

两个旧根都被识别；没有 `todo_items.json` 与 `overlay-active-pets.json` 的根如实报 `not_found`；丢弃项逐一列在 `detail` 里，没有静默。

## 六、风险与回滚

新增持久物只有三样：`migration.json`（迁移标记）、`migration-backup/`（备份）、`updates/<asset>.verify.json`（下载校验侧车）。删除 `migration.json` 等于允许重跑迁移；`petcore migrate --rollback` 按标记里的映射恢复目标文件（原本不存在的直接删除）。探针出问题就取消勾选「GPU」/「帧率」两段——采样器随即 `stop()`；再不行 `git revert` 本轮提交，旧 `pet/` 与本轮无交集。

## 七、最终状态

P5 的三处硬伤（投递、死锁、菜单入口）与四处口径问题（避让落盘、更新取消/摘要、段语义、计数只写）已修并有回归测试；旧数据七域迁移可 dry-run、可回滚、可诊断；GPU 真读数在本机跑通，FPS 受本机权限限制停在「明确原因」而非假读数。默认发布入口仍未切换，`pet/` 未改动。
