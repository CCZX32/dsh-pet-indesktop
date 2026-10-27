# petcore 灵动岛 × 桌宠碰撞回归 + C 盘剩余段（2026-10-26）

> 用户需求：「灵动岛和桌宠的碰撞（原主分支的颠勺和相互碰撞）加回来；给灵动岛加一个可选的
> C 盘剩余空间显示选项（确保添加这个之后这个模块性能占用不高）。」
> 批次记录：[`PETCORE-LOG.md` L103](PETCORE-LOG.md)；契约见 [`PETCORE-SPEC.md` §29.6](PETCORE-SPEC.md)。

## 修改文件说明

新增文件行数来自 `wc -l`；已跟踪文件的行号是**工作区累计**（`git diff --numstat`），
其中 `ui/island.py`、`ui/pet_window.py`、`ui/app.py`、`config.py`、`pages_core.py`、
`tests/test_petcore_island_window.py` 还含同一工作区里尚未提交的 L101（图标/去头标）与
L102（点击台词排队）的改动，本轮部分在「改了什么」一列里说明。

| 文件 | 增/删 | 改了什么 + 为什么 |
|---|---|---|
| `petcore/engine/island_field.py` | 新增 328 行 | 岛 × 桌宠碰撞的**全部数学**（零 Qt）：胶囊体育场 `min(高,44)`、`rect_radial`、`push_out`（中心在轴上强制向上）、`relative_approach`、`impulse_velocity`（`-(1+e)vn`，硬上限 6000）、`reflect_velocity`（`e<1` 且已在离开时不反射）、`tracked_velocity`（首次/`dt` 非法/坐标跳变一律 0）、`sample_island_velocity`（7 道闸门的状态机）。搬自主分支 `pet/island_collision.py` 与 `pet/island_bridge.py`，只把「窗口」抽象成数据。 |
| `petcore/ui/island_collision.py` | 新增 361 行 | Qt 协调器 `IslandField`（挂在 `host.island_field`）：`stadium()`（墙的开关矩阵）、`clamp()`（位置出口：推出 + 真撞冲量 + 轻贴收计划）、`reflect_throw()`（抛掷反射 + 落岛当落地，返回 `ThrowResolution`）、`on_geometry_changed()`（岛速采样 + 推出被压住的桌宠）、`notify_hit()`（挤压/音效/岛果冻的**单一 0.25s 闸**）、`reset()`。**不建定时器、不建线程**。 |
| `petcore/platform/diskmon.py` | 新增 166 行 | C 盘剩余采样（零 Qt）：`clamp_interval`（[5,60]）、`volume_path`（`%SystemDrive%` 回退 `/`）、`read_usage`（一次 `shutil.disk_usage`，失败给原因**不给 0**）、`format_size`（≤4 列，0.95T 起走 T，避免 "1000G" 撑破段盒）、`DiskSample`（`text`/`note`）、`DiskMonitor`（`SamplingLoop`，5s，线程名 `petcore-disk-monitor`，`runtime_metrics.inc("disk_samples")`）。 |
| `petcore/ui/island.py` | +197 / −30（含 L101） | 本轮：`collision_rect()`（只覆盖胶囊本体；隐藏/细条/动画中返回 None）、`dragging` / `geometry_animating` 属性、`bump()`（果冻冲量 + 定向 kick，展开/细条态忽略）、kick 弹簧通道（钳 ±3px，进 `_animating()` 与复位路径）、绘制层 kick 位移、`moveEvent`/`resizeEvent`/显隐/动画落定都 `_emit_geometry_changed()`、`_emit_geometry_changed` 用 `getattr`（构造期安全）、C 盘段（`disk_monitor` + `_disk_segment` + `_metric_segments` 分支 + `_sync_sampling` + `stop()`）、`CARD_NAMES["disk"]`、卡片行读 `detail["note"]`。 |
| `petcore/ui/pet_window.py` | +111 / −12（含 L102） | 本轮：`_clamp_position` 拆成 `_clamp_to_screen`（原逻辑原样搬走）+ 岛墙（`host.island_field.clamp`），并新增 `island_hit_feedback()`（挤压 + 碰撞音效，节流由碰撞层持有）。 |
| `petcore/ui/motion.py` | +28 / −1 | `_tick_throw` 接 `field.reflect_throw()`：反射/钉位/落岛 `stop()`；撞岛反馈走 `field.notify_hit()` 并做「上升沿 + 速度门」抑制（贴墙滑行不会每帧响）；`_island_touching` 在 `set_velocity`/`begin_throw`/`stop` 里复位。 |
| `petcore/ui/app.py` | +51 / −1（含 L101） | 本轮：`island_field` 槽位、`_build_island_field()`（建协调器 + 接几何回调）、`_island_pets()`（宠物表懒加载，回调现取）、关岛时 `reset()`、退出时 `reset()`、`_avoid_island_overlap` 在碰撞开启时直接 return。 |
| `petcore/island/segments.py` | +6 / −1 | 新增 `DISK = "disk"` 并进 `BUILTIN_SEGMENT_IDS`（第三方不得同名）；**不进** `ALERT_THRESHOLDS`（现表语义「越高越危险」，剩余空间方向相反）。 |
| `petcore/config.py` | +14 / −4（含 L101/L102） | 本轮：`island_collision`（默认 `True`）进 `DEFAULTS` + `GLOBAL_CONFIG_KEYS` + `_normalize`；`ISLAND_METRIC_IDS` 加 `"disk"`（与 `BUILTIN_SEGMENT_IDS` 双白名单）。 |
| `petcore/performance.py` | +1 / −0 | `PerformanceSnapshot` 加 `disk_samples`。 |
| `petcore/ui/settings/pages_core.py` | +32 / −9（含 L101/L102） | 本轮：「灵动岛」卡加「与桌宠碰撞」行（`island_collision`）、「指标段」加「C 盘剩余」复选、`_island_metrics()` 顺序同步、提示句写清 5 秒采样。 |
| `tests/test_petcore_island_field.py` | 新增 259 行 | 33 例纯函数：体育场截断/非法矩形、推出幂等、侧壁用半宽、中心在轴上向上、冲量上限、反射不放大、接触速度跳变守卫、7 道岛速闸门。 |
| `tests/test_petcore_island_collision.py` | 新增 810 行 | 39 例：墙的四态闸门、推出稳定、走路只挡不弹、高速真撞切 thrown + 三档反馈各 1、冷却/反馈节流、拖拽只推、抛掷反射/落岛/贴顶滑行、岛扫过静止宠、动画不采样、配对上报、停下清零、松手闸、长暂停、瞬移、超速钳制、`reset`、**无新增 QTimer**、`bump` 钳位与收敛、三个真实挂接点（`_clamp_position`、无场时逐像素不变、`_tick_throw` 反射）。 |
| `tests/test_petcore_disk_segment.py` | 新增 282 行 | 40 例：格式化（含 1000GiB→1.0T 的 4 列边界）、区间钳制、读失败不给 0、停采不清值、线程命名与停止、段的盒宽/标签/状态、卡片 note/error、隐藏与折叠停采、展开态例外、配置白名单与默认值。 |
| `tests/test_petcore_island_window.py` | +28 / −1 | fixture 停掉 disk monitor；`test_monitors_are_real_objects` 同口径。 |
| `petcore/AGENTS.md` | +23 / −9 | 「宠-宠碰撞只走 PetManager tick」改口径；新增 6 条红线：岛墙挂 `_clamp_position`（不许改写 16ms tick）、闸门一条都不能少、岛速采样照桥、撞岛反馈单闸、落岛=落地、碰撞开启不做避让、磁盘段（5s/不许写 0/不进告警表）。 |
| `docs/PETCORE-LOG.md` / `PETCORE-LOG-INDEX.md` | +? | 新增 `L103` 与索引行。 |
| `docs/PETCORE-SPEC.md` | +17 / −4 | §29 配置键 15→16（加 `island_collision`）、`island_metrics` 加 `disk` 与口径、新增 §29.6「岛 × 桌宠碰撞」三条不变量 + 闸门 + 采样 + 反馈，P5-a2 状态表订正。 |
| `docs/PETCORE-ARCHITECTURE.md` | +9 / −0 | §18 补「岛 × 桌宠碰撞（L103）」：几何/接线/三个入口/采样/反馈/避让口径。 |
| `docs/PETCORE-ROADMAP.md` / `PETCORE-MAIN-PARITY-BACKLOG.md` | +2 / −2、+2 / −2 | 「灵动岛碰撞未做」改为已回补并写清仍未做的项（岛聊天、隐藏后唤起对话）。 |
| `docs/SETTINGS-CHANGE-GATES.md` | +20 / −0 | 新键准入记录（`island_collision` + `disk` 段），含默认值/作用域/实时预览/迁移/性能/测试。 |

## 复核修复（子代理只读复核 9 条发现，逐条处理）

| 级别 | 发现 | 处理 |
|---|---|---|
| P1 | 漫游发起时对 60–240px 外**目标点**的预钳被当成真撞（`dt` 0.12–0.5s 时躲过 2000px/s 守卫），站着不动的桌宠被凭空切 thrown，且与移动计划并存 | 新增 `clamp(..., settle=False)`：只算几何不结算；`_begin_move` / `_finish_move` 的目标钳改用该入口（+2 例） |
| P2 | 折叠→展开/隐藏→显示后 C 盘段闪 5 秒 `--`（`SamplingLoop.start()` 清快照，首读要等一个间隔） | `DiskMonitor` 保留最后一份样本兜底 `snapshot()`（+1 例） |
| P2 | 落岛收手后岛被拖走 → 桌宠悬空（normal 态没有重力） | `_resting` 记住停稳位置，岛移开且该宠没被用户挪走时补一次自由落体（+2 例） |
| P2 | 宠-宠分离用 `set_velocity` 覆盖了撞岛刚写下的冲量 | `_apply_body` 加 `not motion.thrown` 守卫（+1 例） |
| P2 | 快速拖岛停住但没松手时，停手前速度留在表里 → 旁边走进来的桌宠被凭空拍飞 | `dt<0.01` 分支补「非拖拽且 rect 没动 → 清零」（+1 例） |
| P3 | `9.96 GiB → "10.0G"`、`9.99 TiB → "10.0T"` 是 5 列，会撑破 `888G` 段盒 | 两条 `.0f` 门改 9.95，T 档起点 0.975T（+3 个取值） |
| P3 | 几何动画每帧 `reset()` 把冷却/反馈表也清了 → 0.25s 单闸被 60 次/秒关掉 | 拆 `reset_velocity()` / `reset()`（+2 例） |
| P3 | `id(window)` 键在桌宠关闭后不复用清理 | `_prune_stale_keys()`（+1 例） |
| P3 | 设置页缺 `island_collision` / `disk` 的用例 | 补 1 例（默认开、切换即写配置、勾上 disk 落 `island_metrics`） |

没找到问题的类别（复核原文）：坐标/DPR 口径、`moveEvent` 回调风暴与递归、`bump`/kick 钳位与
收敛、C 盘段的 error/闸门/生命周期、配置白名单与取消语义、文档与代码一致性。

## 性能分析

命令与环境：`.venv/Scripts/python .scratch/bench_island_collision.py`
（Windows 11 / PySide6 / 同一进程内 `timeit.repeat(number=N, repeat=5)` 取最好值；
`QT_QPA_PLATFORM=offscreen`；真 `DynamicIsland` + 4 只替身桌宠）。
原始输出：[`.scratch/accept/bench-island-collision.txt`](../../.scratch/accept/bench-island-collision.txt)。

| 路径 | 实测 | 触发频率 | 说明 |
|---|---|---|---|
| `island_field.push_out` 命中 | **1.58 µs/次** | 每次位置出口调用一次 | 纯算术：2 次 hypot + 若干乘除 |
| `island_field.push_out` 未命中 | 0.85 µs/次 | 同上 | 绝大多数调用走这条（不在岛附近） |
| `IslandField.clamp` 命中 | **6.34 µs/次** | 最多 60 Hz/只 | 含推出 + 接触表 + 反馈判定；命中时才 6µs |
| `IslandField.clamp` 关掉/隐藏 | **0.79 µs/次** | 同上 | 一个 `config.get` + 属性读，等价于重构前 |
| `on_geometry_changed`（4 只宠） | **28.1 µs/次** | 只在岛移动/改尺寸时（拖拽 ≤125 Hz、静止 0） | 岛拖拽最坏 125Hz × 28.1µs ≈ 3.5 ms/s = **0.35% 单核**；比首版 18.6µs 多了两趟簿记（落岛悬空兜底 + 陈旧 id 清理） |
| 新增 QTimer | **0** | — | 岛窗口 8 个定时器，接线前后不变；协调器自身无定时器属性 |
| 新增常驻线程 | **0** | — | 全事件驱动 |
| 新增内存 | 每只桌宠 1 条接触记录（3 个 float）+ 2 个时间戳 | — | 清理由 `reset()`/隐藏态推出 |
| `shutil.disk_usage("C:\\")` | **37.7 µs/次** | **5 秒一次**（0.2 Hz） | `GetDiskFreeSpaceEx`，不产生磁盘 IO |
| 磁盘监控线程 CPU | **25 秒内 0.000 s**（进程 CPU 增量） | — | 线程 25s 里只被唤醒 4 次，其余时间 `Event.wait` |
| 25s 内磁盘采样次数 | **5 次** | 5s 间隔，期望 4–5 | 首拍在第一个间隔之后（两次跑分别 4 / 5 次） |
| 磁盘段稳态内存 | 1 个不可变 `DiskSample` | — | 无历史、无缓存增长 |

结论：碰撞层在**每秒一次**的常态下开销 ≈ 0（无墙时 0.79µs × 调用次数）；岛被拖拽时最坏
0.35% 单核；磁盘段是 0.2Hz 的单次 syscall，没有轮询、没有磁盘 IO、折叠/隐藏即停采。
四条「无」——无新定时器、无新线程、无网络、无磁盘写入——都有脚本断言（测试
`test_the_collision_layer_creates_no_timer` 与 `bench` 的 P4 段）。

## 实机运行记录

环境：Windows 11、本机 150% 缩放、`.venv` 内的 PySide6；**真 QApplication + 真
`DynamicIsland` + 真 `PetWindow`（shenshen 角色包）+ 真 16 ms `MotionController` 定时器**，
不是 mock。两套平台各跑一轮（`QT_QPA_PLATFORM=windows` 与 `offscreen`），结论一致。

### A1–A6（`.scratch/verify_island_collision.py`）

```
屏幕 = QRect(0, 0, 1280, 800)          # QT_QPA_PLATFORM=windows（真桌面平台）
胶囊球馆 = Stadium(x0=422.0, x1=678.0, axis_y=322.0, radius=22.0, height=44.0)
桌宠身体框（窗口局部）= (106, 30, 108, 135)

== A1 把桌宠拖向胶囊 ==
被挡住的帧 = (78, 315, 306)；进入重叠的帧数 = 0
body 中心 = (550, 412)；thrown=False；音效=0；挤压=0                          → PASS
== A2 岛以 750px/s 扫向静止桌宠 ==
岛速 = (0, 750) px/s；切 thrown 的步 = 1；速度 = (0, 1310)
音效=1；挤压=1；撞岛瞬间 果冻 _squish_v=-1.91、kick_v=(0,-182.85)、动效预算=0.90s  → PASS
== A3 以 900px/s 抛向胶囊 ==
反射帧 = (6, (-593.4, 207.9), 628.7)；重叠帧数 = 0/257；4.02s 回 normal         → PASS
== A4 从上方小速度落下 ==
收手帧 = 5/5；mode=normal；落点中心 = (550, 232)；重叠 = False                  → PASS
== A5 island_collision=False ==
关掉时 = [(390,284),(391,284),(392,284),(393,284),(394,284)]
无碰撞层 = 同上                                                                → PASS
== A6 隐藏 / 细条 / 几何动画中 ==
墙生效时 = (390, 315)（输入 (390, 244)）；隐藏=细条=动画中=(390, 244)            → PASS
汇总：{'A1': True, 'A2': True, 'A3': True, 'A4': True, 'A5': True, 'A6': True}
```

（岛速/出射速度会随机器负载小幅浮动——每步 12px 是按 16ms 计划推进的，实测 dt 有抖动；
在所有跑过的一轮里，结论——切 thrown、出射 ≤ 0.7 入射、重叠帧 0、4s 级回 normal——都一样。）

完整输出：[`.scratch/accept/island-collision-sequence.txt`](../../.scratch/accept/island-collision-sequence.txt)
（offscreen 同结论：[`…-offscreen.txt`](../../.scratch/accept/island-collision-sequence-offscreen.txt)）。

### 行走步速（决定「真撞门」不用加第二道闸）

`.scratch/measure_move_speed.py`：shenshen 全部 MOVE 素材，scale 0.5/0.72/1.0 →
**4.5–24 px/s**（stride 45–240px / 单圈 10.04s）。真撞门 80px/s 远在其上，所以
「走路撞岛」只会被挡住 + 收掉移动计划，不会被弹飞（A1 的实测就是这条）。

### C 盘剩余段的真实渲染

`.scratch/verify_island_disk_visual.py`（**必须 `QT_QPA_PLATFORM=windows`**：本机 offscreen
后端渲染不出字形，整条胶囊都是缺字方框，会被误判成「文案坏了」）：

- `.scratch/accept/island-disk-capsule-dark.png` / `-light.png`：
  `鲸鱼娘彩蛋 21:33 | CPU -- | 内存 71% | C 盘 412G ●`（替身读数 412G/2.0T）
- `.scratch/accept/island-disk-card-dark.png` / `-light.png`：卡片行
  `C 盘 / 412G · 总 2.0T · 已用 1.6T`
- `.scratch/accept/island-disk-real.png`：**真读一次 C:** → `鲸鱼娘彩蛋 21:33 | C 盘 118G`
  （`DiskSample(free_bytes=126257143808, total_bytes=214752555008, error='', source='C:\\')`）

### 门禁

- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py
  tests/test_architecture.py tests/test_pr_report_discipline.py -q` → **2247 passed**
  （208.7s，含本轮新增 112 例）
- `.venv/Scripts/ruff check pet/ tests/ petcore/` → `All checks passed`
- `.venv/Scripts/python -m petcore --check` → 退出码 0
- 全量 `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest -q` →
  **10424 passed, 18 skipped**（1829s，0 失败；19 条 DeprecationWarning 是既有的）

### 未能自动验证 / 已知限制

- **真实鼠标拖拽手感**（拖动胶囊扫过桌宠的那一下）只能由用户实机确认；自动化覆盖到的是
  几何、速度、反馈计数与「不重叠」。
- 岛从桌宠**身体中线**继续推过去时，法线会从下翻到上，桌宠被甩到另一侧——这是主分支同一
  份几何的退化行为（没有扫掠解算），不是穿模（A1 重叠帧数恒为 0）。
- `offscreen` 后端没有字形，任何「岛/菜单文案」截图都必须用 `QT_QPA_PLATFORM=windows`。
- 磁盘段只统计系统盘（`%SystemDrive%`，默认 C:），不支持自选盘符。
- tilt（旋转）通道刻意不做：44px 高的窗口没有旋转裁切余量，果冻 + 定向 kick 已足够表达撞击。
