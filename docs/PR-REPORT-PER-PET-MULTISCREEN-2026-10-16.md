# PR 报告：每屏一窗的独立多屏 + 「允许桌宠跨屏」开关（`docs/PR-REPORT-PER-PET-MULTISCREEN-2026-10-16.md`）

> **基线**：`6a68570`（`origin/main`，含 #285 播放器）
> **分支**：`feat/per-pet-multiscreen`（worktree `D:/dsh-pet-wt-multiscreen`）
> **日期**：2026-10-16
> **范围**：累计 **33 个已跟踪文件 `+2931/−459`**（本分支相对 `origin/main`，含先前一片宿主化改造）
> + **3 个新增文件**（`tests/test_overlay_cross_screen_switch.py` 327 行、
> `tests/test_settings_cross_screen.py` 128 行、本报告）；
> 其中**本刀（开关 + 位置归属语义 + 夹具泄漏 + 文档）**= 15 个既有文件 `+198/−18` + 上述 3 个新增文件
> **关联**：[`AGENTS.md`](../AGENTS.md)（多屏段落 = 现行口径）、[`SETTINGS-CHANGE-GATES.md`](SETTINGS-CHANGE-GATES.md)（本刀新增设置的准入/准出记录）、[`INDEX.md`](INDEX.md)（本报告已登记）、
> `.scratch/per-pet-multiscreen/HANDOFF.md`（断点与未验清单）、多屏条目的 BACKLOG（`D:/dsh-pet-src/.scratch/BACKLOG.md`）；
> #284（整群搬屏）**不采用**、不混 DLC

## 〇、状态与边界（先读这一段）

- **本地提交，未 push、未开 PR**：留主代理按 ops5.5 + astra 一次盲审后处置。
- **真双屏未验**：本机 Qt 口径只有 **1 块活动屏**（§四之一），跨缝手感 / 异 DPI /
  负坐标拼接只有假屏逻辑证据（假屏不是 `QScreen`，见 §四）。
- **显存未测**：只给理论缓冲估算（§三之三），明确不是实测。
- **打包产物未构建**；macOS / Linux **未跑**（不推断）。

## 一、核心特性

用户 2026-10-16 定案：**直接采用「每块有桌宠的屏各一张合成窗」**（不再做 A/B 原型
对比），并新增一个**全局开关**控制这个能力。用户看到的变化：

| # | 能力 | 说明 |
|---|---|---|
| 1 | 每屏一窗 | 每块**被占用**的显示器各一张透明合成窗；进程、tick 时钟、音效池、联动、托盘、素材库仍只有一份 |
| 2 | 逐只独立跨屏 | 把某一只拖到另一块屏，只搬这一只；其余宠的屏、位置、边界、窗口一个像素不动 |
| 3 | 逐屏独立仿真 | 行为（漫游/落位钳制）/ 碰撞世界 / 抛掷物理 / 边缘探头**逐屏一份**：两块屏上局部坐标相同的两只宠在真机上相距上千像素，共用一个世界会被判成接触 |
| 4 | 位置记忆逐只独立 | `screen_name` + `rx/ry` 逐只落盘，比例相对**它自己那块屏**的可用区算；重启按各自记忆回各自那块屏 |
| 5 | **允许桌宠跨屏开关** | 新增全局键 `allow_cross_screen`，**默认关**、**重启生效**（进程快照）。关着时全部宠只留在启动那块屏、只有一张窗、拖不过去 |
| 6 | 关闭不丢多屏位置 | 关着（或某块屏临时拔掉）期间，位置比例照旧更新，**屏幕归属不被机械动作改写**；重新开启并重启，各宠回到各自那块屏 |

**红线 / 不变量**：

- **单屏 + 默认开关 = 旧行为逐位不变**：一张窗、一个宿主、一份控制器；关闭态没有
  任何多出来的窗口 / 线程 / 定时器。
- **共享面绝不复刻**：`TickDriver`（一个 QTimer）、音效、台词、托盘、素材库、媒体
  缓存、DSH 监视器都只有一份（`ShellOverlayWindow` 只是窗口，不持共享服务）。
- **屏归属不许被机械动作改写**：这是本刀新增的数据语义（§二之一）。
- **不做的三件事**：不 warp 鼠标、不加 native 几何兜底、不做 DLC。

## 二、修改文件说明

### 2.1 本刀新增：开关与位置归属语义

| 文件 | 改了什么 + 为什么 | ± |
|---|---|---|
| `pet/config.py` | 新增全局键 `allow_cross_screen`（默认 `False`）+ reload 白名单 + `_bool_or_default` 归一。默认关 = 存量用户行为不变 | +6 |
| `pet/overlay_shell.py` | ① 壳构造时**快照一次** `self._cross_screen_allowed`（重启级，运行期不重读，与 `stream_capture_mode` 同口径）；② `_host_for_restore` 开关闸：关着时全部宠落**启动那块屏**（不采纳记忆、不建第二张窗）；③ `route_drag_to_screen` 与 `move_sprite_to_screen` 开关闸：关着时拖拽/搬移一律拒绝；④ `_save_child_geometry` **不再无条件写 `screen_name`**，只在"本宠身上记着待写的归属"时与比例一起写；⑤ 新增 `_remember_sprite_screen`：有意换屏时唯一改屏归属的地方（`move_sprite_to_screen` 成功分支调用），**只把屏名记在这只自己身上、不在拖拽路径写盘**（单键写实测中位 3.4 ms、p95 4.2 ms，锁被占最长等 5 s，GUI 线程不为一次落盘停这么久），落盘由下一次几何自存与比例同一次原子写完成。④⑤ 合起来兑现"关闭再启动不覆盖原多屏位置" | +62/−4 |
| `pet/settings_pet_controls.py` | 新增 `CROSS_SCREEN_HINT`（行说明，末尾逐字带 `GLOBAL_SCOPE_NOTE`，由 `set_scope_note` 削到标注里）、`cross_screen_check` 控件（**非 overlay 拓扑置灰** + tooltip，理由写在行内注释）、`GLOBAL_SCOPE_ROWS` 登记（全局作用域标注） | +22 |
| `pet/modern_settings_dialog.py` | 常规域「窗口与系统」新增一行「允许桌宠跨屏」，排在窗口旗标类之后；claim 表加 id；保存回写 `allow_cross_screen` | +13/−1 |
| `pet/settings_default_marks.py` | 默认值标记映射 `cross_screen → allow_cross_screen`（出厂默认 False 可比） | +1 |
| `pet/settings_page_guide.py` | 「窗口与系统」组描述补一句"能不能拖到别的显示器上"（分组语义变了，描述同步） | +1/−1 |
| `AGENTS.md` | 多屏段落补：跨屏能力由 `allow_cross_screen` 门控、`screen_name` 是"屏归属"且只由有意换屏写、几何自存不写屏名 | +9/−1 |

**为什么把屏名从"无条件自存"里摘出来**（本刀最关键的一处：数据语义选择）

原先 `_save_child_geometry` 每次落盘都把 `screen_name` 写成"当前所在屏"。这条在
多屏下有两处会吃掉用户摆好的布局：

1. 关着跨屏启动 → 全部宠被摆到启动那块屏 → 退出自存把归属全改成那块屏；
2. 某块屏临时拔掉 → 宠被并到活着的屏 → 同样被改写。

两种情形都是**机械动作**（用户没动这只宠的屏归属），却会丢掉"这只属于哪块屏"的
记忆。改法取最小清晰语义：**`screen_name` = 屏归属，只由"有意换屏"改写**，且**与
比例同一次原子写落盘**（有意换屏时把这笔待写记在这只自己身上，退出/收尾的几何
自存把两者一起写）。这样：

- 单屏普通拖动的持久化**不受影响**（比例照旧逐次落盘，不是"关闭时一律禁写"）；
- 关闭 / 临时缺屏共**同一条**语义（用户要求"能共用就覆盖"）；
- round trip 可回归：关闭 → 拖动 → 保存 → 重新开启并重启 → 仍回各自那块屏；
- 拖拽路径（mouseMove → 跨屏路由）上**没有磁盘 I/O**：单键几何写实测中位
  **3.4 ms**（p95 4.2 ms、max 5.3 ms，n=200），且目录锁被别人占着时最长可等 `DEFAULT_TIMEOUT_S` = 5 s
  ——把这个写放进逐帧回调是不可接受的。

### 2.2 本刀修改的既有测试（都是契约随语义收紧，不是放宽）

| 文件 | 改了什么 + 为什么 | ± |
|---|---|---|
| `tests/test_overlay_hosts_multiscreen.py` | 夹具显式打开开关（本文件测的是"允许跨屏"下的合同；默认关时壳体只在启动那块屏建窗，多屏断言无从成立）；两处直接构造的 `CapConfig` 同样带上 | +8/−2 |
| `tests/test_overlay_independent_screens.py` | 同上（`_make_shell` 打开开关）；**修掉双屏夹具的 `QApplication` 实例 patch 泄漏**（只补类级 `QGuiApplication.screens/primaryScreen`——产品读的就是类级静态方法，补实例属性会在 PySide6 对象上留影子、`monkeypatch` 撤回时写回"已被补成假屏的值"，泄漏到下一条用例）；`test_each_pet_persists_its_own_screen_and_ratio` 改成新语义（没换过屏的那只档案里**没有** `screen_name`，但 `rx/ry` 照旧更新） | +21/−6 |
| `tests/test_config_schema.py` | 默认值 / reload 白名单快照加 `allow_cross_screen`（快照即现状文档化） | +1 |
| `tests/test_settings_compat_layering.py` | 「窗口与系统」行序期望补 `settingRow_cross_screen` | +1 |
| `tests/test_settings_ia_first_cut.py` | 同上：跨屏行排在窗口旗标类之后（原先断言"光标穿透是最后一行"） | +3/−1 |
| `tests/test_architecture.py` | `modern_settings_dialog.py` 行预算 2515 → **2526**（实测；带日期注释说明这 11 行是行装配 + claim + 保存回写，控件与文案落在 `settings_pet_controls`） | +6/−1 |

### 2.3 本刀新增文件

| 文件 | 内容 |
|---|---|
| `tests/test_overlay_cross_screen_switch.py`（327 行） | 开关的 8 条契约：默认关、重启级（**三进程往返**：运行中改配置不生效 → 重建后生效）、关着时全宠只在一块屏一张窗、`move_sprite_to_screen` 被拒、**真鼠标事件**拖到另一块屏仍不换宿主且被本屏钳住、关闭态普通拖动照旧落比例、**关闭→开启 round trip 回到各自那块屏**、屏临时缺失共用同一语义 |
| `tests/test_settings_cross_screen.py`（128 行） | 设置行 5 条契约：默认关 + 保存 round trip（重开对话框读回）、全局作用域标注（说明里那句被削到标注、可访问说明不丢）、非 overlay 拓扑置灰 + tooltip、默认值标记与单项重置入口、四组搜索词命中 |
| `.scratch/per-pet-multiscreen/probe_cross_screen.py` | 真机探针：`screens` 打印 Qt 屏枚举（活动屏唯一权威）；`switch` 用**三个独立子进程**在隔离 `APPDATA` 下各跑一次"写 config → 建壳" |
| `.scratch/per-pet-multiscreen/bench_hosts.py` | 同屏模拟成本实测（一宿主 vs 两宿主，A/B/A 交替多轮 + 噪声带；宿主创建/show 一次性成本；RSS/USS；理论帧缓冲估算） |
| `.scratch/per-pet-multiscreen/bench_profile_write.py` | 单键几何写的成本实测（n=200，中位/p95/max）——"屏归属不进拖拽路径"这条结论的依据 |

### 2.4 累计（本分支相对 `origin/main`，含先前一片宿主化改造）

| 文件 | ± | 一句话 |
|---|---|---|
| `pet/screen_host.py`（新） | +83 | 屏宿主：overlay + 屏局部可用区 + 该屏的行为/碰撞/物理/探头/彩蛋控制器组；`host_for_collision` 反查点 |
| `pet/overlay_shell.py` | +1256/−398 | 宿主表 + `hosts()`/`host_for_sprite`/`host_for_screen`/`_host_of`；`_create_host`/`_wire_host`/`_release_host`/`_reap_empty_hosts`；跨屏移交 `route_drag_to_screen`/`move_sprite_to_screen`/`_transfer_sprite`/`_place_sprite_in_host`；逐屏几何同步与屏事件处置；一切"整组"动作改遍历 `_hosts`（显隐/停止/关闭/整窗能力/气泡/岛墙/投喂/音效/位置监听） |
| `pet/overlay_window.py` | +59/−11 | `detach_sprite_for_transfer`（摘出但**不**广播移除、**不**释放 clip）、跨屏后的坐标换算钩子（`_sprite_event_pos`/`_follow_overlay`）、按 sprite 当前宿主取行为/探头 |
| `pet/tick_driver.py` | +45/−10 | 仿真段按宿主分组（同 tick、同 QTimer，每屏只跑自己的世界）；`hosts` 只读视图；裸 overlay（单世界装配）语义逐位不变 |
| `pet/pet_sprite.py` | +23 | `translate_frame(delta)`：拖拽中换局部坐标系时把绝对坐标类样本（弹簧目标、轨迹）整体平移；`_drag_offset` **不平移**（差值，平移反而错位） |
| `pet/sprite_behavior.py` | +7 | `forget()` 一并交还圈末回调挂接权（否则跨屏交出去的 sprite 在新世界里圈末续播永不接管） |
| `pet/sprite_sound.py` | +9/−5 | `on_collision(..., world=)`：多屏下按撞出事件的那个世界取阈值（单世界口径不变） |
| `tests/test_overlay_hosts_multiscreen.py`（新） | +637 | 宿主公开面、同局部坐标不碰撞、跨屏拖拽只迁一只、换屏不改手感（松手初速）、移交不是退出（clip/成员不注销）、DPR 跟随目标屏、关一张窗不停整组时钟、屏事件、逐宠位置记忆 |
| `tests/test_overlay_independent_screens.py`（新） | +529 | 逐只迁移合同 + 反例（另一只不动 / 空屏不留窗 / 同屏必撞对照 / 单 timer 不双重推进 / 逐只落盘与复活） |
| 其余 11 个既有测试文件 | +79/−37 | 断言随"一屏一宿主"调整（宿主枚举、窗口数、能力下发目标等） |

## 三、性能分析

**环境**：本机 Windows，Python（本仓库 `.venv`），真机唯一的活动屏 = `H27T22S`
2560×1440 / DPR 1.0 / 170Hz（Qt 枚举，见 §四之一）。同屏模拟与 CPU 数字来自
`.scratch/per-pet-multiscreen/bench_hosts.py`（offscreen 平台 + 两块几何相同的假屏），
真平台启动数字来自 §四的隔离探针。

### 3.1 稳态开销（受影响路径）

| 口径 | 1 宿主（= 默认关 / 单屏） | 2 宿主（同屏模拟） |
|---|---|---|
| `tick_sim` 每帧 | **0.212 ms**（min 0.151 / max 0.299，5 轮取中位，N=600 帧/轮，预热 200 帧） | **0.140 ms**（min 0.117 / max 0.204） |
| 多一张宿主的边际 | — | **−0.072 ms/帧**，本 harness 噪声带 **0.148 ms** ⇒ **偏移在带内，等于测不出** |

数字方向为负的解释（不作为性能结论）：拆成两块世界后每块世界里只有一只宠，成对
碰撞判定归零；同一进程里 A/B 交替跑多轮就是为了把漂移摊平，但 offscreen 平台没有
真实上屏，**painting/GPU 合成成本根本没被量到**。诚实结论：**宿主拆分在仿真段没有
可测出的每帧增量**，真实多屏的合成成本**未测**。

### 3.2 新增路径的一次性成本与触发频率

| 路径 | 触发频率 | 实测 |
|---|---|---|
| 新建一块宿主（窗 + 三控制器 + 碰撞世界） | 只在"这只宠第一次落到某块屏"那一次 | `_create_host` **0.4 ms**；该窗 `show()` **2.0 ms** |
| 有意换屏记屏归属（`_remember_sprite_screen`） | 每次用户主动跨屏拖拽落点 | **0 次写盘、0 ms**（只在这只身上记一个字符串；写盘并进下一次几何自存） |
| 单键几何写（`write_profile_geometry`，屏幕归属原先会走的路径） | 有意换屏若立即写盘会是每次 1 写 | **中位 3.423 ms / p95 4.234 ms / max 5.299 ms**（n=200，`.scratch/per-pet-multiscreen/bench_profile_write.py`）——这正是把它挪出拖拽逐帧路径的理由 |
| 位置自存（`_save_child_geometry`） | 拖动收尾 / 退出 / 开局落位 | 与改动前**同样一次写**（不再写 `screen_name` 这个键，文件字节略小；有意换屏时把屏名并进同一次写，而不是多一次写） |
| 跨屏路由判据（`route_drag_to_screen`） | 拖拽中每帧一次 | 关闭态是**一次布尔判断**后立即返回；开启态沿用原有判据 |
| 新增线程 / 定时器 / 网络 | **0** | `TickDriver` 仍只一个 QTimer；无新线程、无网络、无新系统调用 |

### 3.3 内存

| 口径 | 数值 |
|---|---|
| RSS：1 宿主 → 2 宿主 → 回 1 宿主 | 93.7 MB → 93.7 MB → 93.7 MB |
| USS：同上 | 64.41 MB → 64.41 MB → 64.41 MB（Δ **+0.00 MB**） |
| 理论帧缓冲/窗 | 面积 2560×1440 × 4 B × DPR 1.0² = **14.1 MB**（4K 2560×1440→3840×2160 时约 33.2 MB） |

**必须如实说明**：offscreen 平台不为窗口分配真实后端缓冲，所以这里的 Δ≈0 **不能**
读成"真实多屏下第二个窗口不占内存"。真实成本主要是每窗一块合成缓冲，上面给的是
**理论估算**；**显存占用本机没有可读计数器，未实测**。

### 3.4 开关关闭态（默认态）的净开销

关闭时只有一个宿主，与改动前**逐位相同**的一张窗 + 一组控制器；新增代码只有三处
布尔闸（壳构造一次、拖拽每帧一次、搬移调用一次）与"少写一个键"。**没有新的定时器、
线程、窗口或磁盘写入**。

### 3.5 测试证据

- 本刀新增 focused：`tests/test_overlay_cross_screen_switch.py` **8 passed**、
  `tests/test_settings_cross_screen.py` **5 passed**。
- 多屏两个姊妹文件：`tests/test_overlay_hosts_multiscreen.py` +
  `tests/test_overlay_independent_screens.py` **28 passed**。
- 设置侧守卫（默认值快照 / reload 白名单 / 行预算 / 分组归属 / 作用域 / 搜索 / 文案 lint）：
  全部转绿（改动前它们按预期红）。
- **受影响的真实时序族 3 连跑**（跨屏拖拽 / 宿主生命周期 / tick 驱动器 / 屏迁移 /
  设置行那一族，命令与日志见 `.scratch/per-pet-multiscreen/family-rerun.log`）：
  **3 遍都是 193 passed / 0 failed**（23.01s / 21.28s / 35.07s，`EXIT=0`）。按项目纪律本应"本地 CPU 打满跑 3 遍"，本轮**只做 3 遍串行、
  不加背景负载**——用户明确要求不要把 CPU 打满（同一台机器上还有用户自己的活）。
- **先红后绿（消融）**：逐条撤产品改动都精确令对应用例变红——
  撤 `_host_for_restore` 闸 → 2 红；撤拖拽/搬移闸 → 3 红；把快照改成运行期实时读 → 1 红；
  几何自存重新写 `screen_name` → 4 红（+姊妹文件 1 红）；撤设置页拓扑置灰 → 1 红；
  撤作用域登记 → 1 红。
- **全量套件**：`QT_QPA_PLATFORM=offscreen python -m pytest -q --timeout=300` →
  **7835 passed / 15 skipped / 0 failed / 0 error，23:17**（`EXIT=0`，日志
  `.scratch/per-pet-multiscreen/full-suite.log`）。这是**冻结改动之后**跑的整棵树，
  不是改动中途的结果。

## 四、实机运行记录

### 4.1 屏数证据（活动屏以 Qt 为准）

```
$ python .scratch/per-pet-multiscreen/probe_cross_screen.py screens
platform=windows screens=1
  [0] name='H27T22S' geo=(0,0,2560x1440) avail=(0,0,2560x1392) dpr=1.0 primary=True refresh=170.0
PRIMARY: H27T22S
```

⇒ 本机**只有一块活动屏**（设备管理器里的显示器列表不代表活动屏）。因此：
"宠拖到另一块显示器上"这一条在本机**无法实机验证**；逻辑证据是 §3 的假屏用例
（真壳 + 真 `PetSprite` + 真鼠标事件序列 + 假屏），手感想、异 DPI 观感、错位拼接的
负坐标行为**未验**。

### 4.2 开关与重启级语义（隔离 APPDATA，真 `windows` 平台，三个独立进程）

```
$ python .scratch/per-pet-multiscreen/probe_cross_screen.py switch
isolated base = C:\Users\me\AppData\Local\Temp\pet-probe-cvemyvec
STEP value=absent key_written=False snapshot=False hosts=1 host_screens=['H27T22S'] overlays=1 sprites_in_home=1 visible=[True] start_ms=485.5 tick_ms=0.033
STEP value=true   key_written=True  snapshot=True  hosts=1 host_screens=['H27T22S'] overlays=1 sprites_in_home=1 visible=[True] start_ms=404.8 tick_ms=0.028
STEP value=false  key_written=False snapshot=False hosts=1 host_screens=['H27T22S'] overlays=1 sprites_in_home=1 visible=[True] start_ms=409.8 tick_ms=0.026
FAILURES: 0
```

- **旧配置（没有这个键）→ 默认关**：升级用户不因本刀改变呈现；
- 写 true / false 各起一次**独立进程**：快照跟着磁盘走 → 这就是"重启生效"的进程级证据；
- 三次都是 **1 张窗、1 个宿主、窗真的上屏**（`visible=[True]`，真平台插件）；
- `start_ms` 是**整壳启动**（含首次建库），不是本刀的增量；`tick_ms` 是该替身素材库
  下的仿真段耗时，仅作同环境对照。
- 探针全程 `APPDATA`/`LOCALAPPDATA` 指向临时目录：**没有读写用户真实配置**，没动
  CU，没有鼠标 warp。

### 4.3 用户可见行为确认

| 项 | 结论 | 证据 |
|---|---|---|
| 单屏 + 默认关：仍是一张窗、宠物照常显示 | ✅ 实机 | §4.2 三次 `overlays=1 / visible=[True]` |
| 勾选后面板出现、文案说清"重启生效 / 关闭时只有一块屏 / 记忆不会被清掉" | ✅ 程序化（真控件 + 真 `Config`） | `tests/test_settings_cross_screen.py`（默认值、round trip、作用域标注、置灰、搜索） |
| 关着时拖不过去、不多开窗、宠被本屏钳住 | ✅ 假屏 + 真鼠标事件 | `test_off_keeps_a_cross_screen_drag_inside_the_single_window`（含"光标确实落在另一块屏"的前提断言） |
| 关闭 → 开启后回到各自那块屏 | ✅ 假屏 + 真档案文件 | `test_off_and_on_round_trip_returns_pets_to_their_own_screens` |
| **真双屏手感 / 异 DPI / 交叉区** | ❌ **未验** | 本机只有 1 块活动屏（§4.1） |
| **显存占用** | ❌ **未测** | 无可读计数器；$3.3 只给理论估算 |

### 4.4 待审风险点（留给盲审）

1. `_remember_sprite_screen` 的**屏归属语义**是否与"本宠 reset 保位置"、
   `overlay_spawn_state` 的兼容包装、以及设置页 `screen_name` 相关文案一致；
2. 宿主生命周期：`_release_host` / `_reap_empty_hosts` 在**活跃 grab** 与
   **拖拽落点在缝上**的收尾路径（本刀未改动，但开关改变了可达性）；
3. 关闭态下 `handle_screen_removed` 走到 `_migrate_to_screen` 时，主宿主换屏是否会
   误写任何屏归属（本刀口径：不写）；
4. 设置页把开关放在「窗口与系统」而非新分组，披露层级 = primary 是否可接受。

## 五、已知限制、后续与回滚

**已知限制**

1. **真双屏没验**（本机只有 1 块活动屏）：跨缝手感、"两只窗各裁一半"的瞬间观感、
   异 DPI 缩放、上下错位拼接（负坐标 / 空洞）只有假屏逻辑证据。
2. **显存/合成缓冲没测**：只有理论估算（§3.3）。offscreen 平台不为窗分配后端缓冲，
   所以那里的内存差值不能外推到真机。
3. **打包产物未构建**：本刀不动构建脚本，但也没有产出过含本特性的包。
4. **legacy（捕获模式）下开关置灰**：那边本来就是真窗口、能跨显示器，本开关对它
   没有第二个读点；置灰 + tooltip 是如实呈现，不是功能缺失。
5. 首次跨屏时新建宿主有一次 0.4 ms + show 2.0 ms 的开销（§3.2）；这是"多一块屏"
   的固有成本，未做预热。

**后续（不由本刀决定）**

- 主代理派 ops5.5 + astra 一次针对实际风险的盲审（§4.4 的四条）；
- 盲审通过后按用户口径"每有宠屏一窗即推 PR"开 PR（本刀不 push）；
- 有真双屏的环境补一次实机验收（跨缝手感 + 混合 DPI）。

**风险与回滚**

- **影响面**：`allow_cross_screen` 默认关 ⇒ 存量用户的呈现、窗口数、位置写入
  与改动前一致（§3.4）；受影响的是"打开开关之后"的行为与 `screen_name` 的写入时机。
- **配置迁移**：只有新增键，无旧键改写；`Config.reload` 白名单与归一同步登记。
  用户回退版本时该键成为未知键（被读入即保留、不参与任何判定），不产生半套状态。
- **回滚**：`git revert`（或丢弃本分支）即可；没有数据需要修复——多屏归属写在
  各宠自己的 `config-slot-N.json` 的 `screen_name` 里，旧版本不读该键的使用方式
  与本刀不同（旧版本会把它当作位置的一部分在退出时改写），但不会因此启动失败。
- **开关作为运行期降级口**：若真机上出现多屏异常，用户可以关掉跨屏开关并重启，
  回到"单屏一张窗"的旧行为，无需回滚版本。
