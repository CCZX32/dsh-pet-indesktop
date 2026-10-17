# DLC AI 包窗口通知与设置回调

> 基线：`f824289e8facb725f552b1b2168bf3400b38e9c8`（`upstream/dlc/mod-center-port`）。
> 分支：`dlc/ai-runtime-callbacks`。开始日期：2026-10-15；复审全量完成：2026-10-16。
> 范围：[交接文档 §6.2 第 1 项](DLC-HANDOFF-2026-10-15.md#62-小包接线三件同源后续片可一起做建议作为上手第一批)。
> 状态：已修复复审 R1/R2；最终全量 8502 passed / 20 failed / 73 skipped，失败与修复前相同、均见于基线。默认发布门未满足；未推送或开 PR，没有合并授权。

## 一、核心特性

AI 扩展未保存 Key 时，发送前保留输入和会话，在原状态标签显示「打开 API 设置」。
鼠标或键盘可进入 `official.ai-chat` 自己的设置面板。后台请求认证失败时使用 Core
现有桌面通知；点击进入同一面板。停用、卸载或关闭运行时后，旧通知不能重新开窗。

重复导航保留当前面板、最大化状态及未保存草稿；已有独立设置进程也接收 AI owner 跳转。
通知派发时读取最新保存的包通知开关，不采用未保存草稿。设置进程使用全局配置身份创建扩展宿主，避免
从槽位页保存的凭据引用被进程级 AI 运行时以 `scope_denied` 拒绝。
内置 `pet/chat/`、内置 `open_chat*` 和内置配置/凭据不变；不新增持久设置。
本次没有涉及包 UI 整体对齐、文件解读、官方包安装按钮或 5A 的方向决策。

## 二、修改文件说明

基于 `git diff --numstat f824289e8facb725f552b1b2168bf3400b38e9c8`；新增文件另列。

| 文件 | 增删 | 修改及原因 |
|---|---|---|
| `features/ai-chat/host/runtime_mount.py` | +37 / −1 | 惰性取 Core 回调，传给 `AiRuntime.create_window`；派发与通知点击均检查包生命周期。 |
| `features/ai-chat/host/chat/request_config.py` | +3 / −1 | 仅可通过设置恢复的配置错误可产生本地链接，其他错误保留原因。 |
| `features/ai-chat/host/chat/widgets.py` | +11 / −3 | 包内现代窗口链接、原错误 tooltip、停用守卫；按最新保存值判定通知。 |
| `features/ai-chat/host/chat/legacy_widgets.py` | +11 / −3 | 包内经典窗口遵守同一链接与通知契约。 |
| `features/ai-chat/host/config.py` | +5 / −0 | 增加只读的已提交通知开关查询，保留草稿与 CAS 版本。 |
| `pet/ai_bindings.py` | +15 / −8 | 呈现提供方同时注册/清除两条窄回调；不添加 API 凭据端口。 |
| `pet/app.py` | +19 / −1 | DLC 注册通知及固定 AI owner 导航；已有/启动中的设置进程异步转交请求。 |
| `pet/__main__.py` | +4 / −0 | 在独立设置持锁期间启停局部导航接收器，退出前关闭端点。 |
| `pet/settings_extension_navigation.py`（新增） | +168 / −0 | 有界 Qt 本地导航请求/接收、截止与重试、窗口状态及退出收口。 |
| `pet/modern_settings_dialog.py` | +2 / −0 | 两行 `extension:<owner>` 分派，复用现有独立设置进程参数。 |
| `pet/settings_mod_domain.py` | +34 / −2 | owner 深链接、草稿门、面板可见性、一次布局后的滚动；独立设置宿主使用现有全局配置视图。 |
| `tests/test_ai_window_callbacks.py`（新增） | +412 / −0 | 真打包、Qt、HTTP401、独立进程的 13 项回归；覆盖冷/已有窗口、草稿、保存通知开关及协议失败；只替换系统凭据边界。 |
| `tests/test_ai_package_host.py` | +15 / −1 | 通知查询不重置草稿、不绕过 CAS 冲突；补文件末尾换行。 |
| `tests/test_mod_center_end_to_end.py` | +2 / −0 | 原装配测试桩补上新增的真实回调方法。 |
| `tests/test_architecture.py` | +2 / −1 | 主设置文件仅新增两行 DLC 分派，按规范将实测行数预算 2413 校准到 2415。 |
| 本报告（新增） | +740 / −0 | 逐文件、性能、实机、测试与复现探针。 |
| `docs/INDEX.md` | +1 / −0 | 登记本报告及必读场景。 |
| `docs/modding/PORT-STATUS.md` | +15 / −1 | 保留第四片历史边界，在 §十记录接线、复审修复和验收状态。 |
| `docs/screenshots/ai-window-callbacks-2026-10-15/missing-key.png`（新增） | 二进制 `- / -`；109,008 B | 原始 Cocoa 聊天入口截图。 |
| `docs/screenshots/ai-window-callbacks-2026-10-15/settings.png`（新增） | 二进制 `- / -`；160,528 B | 原始 Cocoa owner 设置页截图。 |
| `docs/screenshots/ai-window-callbacks-2026-10-15/existing-settings.png`（新增） | 二进制 `- / -`；288,880 B | 复审 Cocoa 已有最大化设置窗口成功跳转。 |
| `docs/screenshots/ai-window-callbacks-2026-10-15/saved-notification.png`（新增） | 二进制 `- / -`；22,479 B | 复审 Cocoa 保存开启后实际显示的通知。 |

没有删除文件。未修改 requirements、构建、内置聊天或已知生命周期 flake。

## 三、实现要点与边界

回调在每次开窗/操作时惰性解析；未注册时维持无通知的独立包宿主形态。
`register_ai_pet_view(None)` 同时清掉回调引用，沿用既有退出收口。
通知回调检查 `AiPackageRuntime` 与 `AiRuntime.accepting`，不引入线程或常驻计时器。
设置页只增加 `extension:` 路由；正常侧栏标题选择保持原路径。
切换到其他 owner 前复用保存/放弃/取消草稿门，同一 owner 不重建面板。

独立设置进程的冷启动、已有窗口、启动尚未持锁三种路径均覆盖。已有窗口通过
`QLocalSocket` 接收固定的 AI owner 导航；复用既有单实例锁，不启动第二个设置进程。
客户端只在一次点击待确认时重试，5 秒截止；接收端每连接 2 秒截止、最多 8 个连接，
空闲时无轮询计时器或工作线程。失败显示重试提示，不把点击静默吞掉。
套接字名称按配置根摘要和持锁 PID 定位，消息不携带凭据或任意命令。
`FeatureHostContext.api` 仍为 `None`；包与内置聊天的配置、会话、凭据作用域独立。

## 四、性能分析

环境：macOS 27.0.1 arm64，10 个逻辑核，Python 3.13.7，PySide6 6.11.2。
以下表格复用首个实现提交 `476fb70` 的实测：在相同 Core 下分别装载基线包和该提交的包；
测量时未运行 CPU 负载。缺 Key 和进程内导航路径未再修改；复审新增路径另见 §八。
`perf_probe.py` 完整内容在附录。基线包由改动前 `build_package` 构建，源码 SHA 如页首。

```sh
QT_QPA_PLATFORM=offscreen PET_RENDER_TOPOLOGY=legacy .venv/bin/python .scratch/dlc-ai-runtime-callbacks/perf_probe.py base
QT_QPA_PLATFORM=offscreen PET_RENDER_TOPOLOGY=legacy .venv/bin/python .scratch/dlc-ai-runtime-callbacks/perf_probe.py current
```

| 路径 / 样本 | 基线 | 本次 |
|---|---:|---:|
| 首次聊天窗口，n=1，含模块/字体初始化 | 456.01 ms | 523.98 ms |
| 缺 Key 发送，n=300，中位 / P95 | 3.2793 / 3.7715 ms | 3.2861 / 4.2761 ms |
| 未开设置的静置采样：CPU 时间 / 墙钟 | 0.005977 / 5.0602 s | 0.004409 / 4.7503 s |
| 首开扩展设置，n=1 | 无此跳转 | 731.25 ms |
| 重复跳转，n=100，中位 / P95 | 无此跳转 | 2.7225 / 3.9654 ms |
| 已热身后再跳转 500 次，开启 tracemalloc | — | Python 保留量 +14,416 B；RSS +98,304 B |
| 600 次跳转后面板身份 | — | 同一对象 |
| OS 线程数：开设置前 / 重复跳转后 | 7 / — | 7 / 6 |

稳态静置 CPU 折合单核约 0.118% / 0.093%，是一次短采样，不能据此声称提速。
缺 Key 路径中位增加 0.0068 ms；P95 有波动。冷启动各只有一次样本，也不能推断
稳定的启动差异。首次设置导航是用户点击触发，复用既有设置窗口构造和配置读取；
它仍有约 731 ms 的首开成本，不应描述成零开销。

代码路径审计：回调注册/查询只有进程内引用操作。首次设置导航会触发已有配置
读取和窗口系统调用；默认隔离开关下还会启动一个既有类型的设置子进程。保存 Key
使用既有钥匙串操作，通知使用已有窗口绘制；无额外常驻轮询或网络请求，缺 Key
发送也未启动请求。新增滚动只排一次 Qt 零延时回调，线程实测没有增长。
首次打开设置后的 RSS 为 231,374,848 B，未打开
设置的基线为 162,856,960 B，包含既有设置模块、字体和控件缓存，不能归因于两条
回调本身；500 次重复跳转的增量已单列，未声称长期零增长。

## 五、实机运行记录

2026-10-15，在本机 Cocoa 平台运行真实包安装/启用/窗口/设置/停用路径，临时配置
与用户配置隔离。使用真实 AppShell 装配包窗口，未启动动画/托盘子系统。
该探针没有 mock；未填写或发送真实服务商 Key。完整探针见附录。

```sh
QT_QPA_PLATFORM=cocoa PET_RENDER_TOPOLOGY=legacy .venv/bin/python .scratch/dlc-ai-runtime-callbacks/native_probe.py base
QT_QPA_PLATFORM=cocoa PET_RENDER_TOPOLOGY=legacy .venv/bin/python .scratch/dlc-ai-runtime-callbacks/native_probe.py current
```

基线真实输出：`platform=cocoa`、`window_visible=true`、
`hint=尚未保存 API Key，请打开 API 设置。`、`request_started=false`，没有链接。
本次真实输出节选：

```json
{
  "platform": "cocoa",
  "hint": "<a href=\"api-settings\">打开 API 设置</a>",
  "input_retained": "没有保存 Key，这条消息应保留。",
  "request_started": false,
  "owner": "official.ai-chat",
  "key_visible": true,
  "key_inside_viewport": true,
  "credentials_scope_matches": true,
  "draft_retained": true,
  "notification_visible": true,
  "late_click_stayed_closed": true
}
```

Agent 实际检查了 [聊天入口截图](screenshots/ai-window-callbacks-2026-10-15/missing-key.png)
与 [扩展设置截图](screenshots/ai-window-callbacks-2026-10-15/settings.png)：链接完整可读、
原消息保留、Key 输入框落在当前视口。通知使用包的公开授权提示入口；HTTP 401 到
通知的整条网络链另由真实 loopback HTTP 服务回归测试覆盖，凭据后端在该测试中为内存替身。
失败边界实机验证为停用后点击旧通知，包窗口保持关闭。

Qt 日志仍出现原有 `_WrappingActionButton` 的负最小尺寸警告和 macOS IMK mach
port 日志；窗口及所有探针断言通过。Windows/Linux 的原生窗口行为本机不能实测
（`sys.platform=darwin`，Qt 平台为 `cocoa`）；没有声明已验证跨平台截图或真实模型回复。
没有新增设置键、默认值、迁移、重置语义或搜索行；本次相关设置门为导航、草稿、
凭据隔离与可见性。UI 整体对齐仍属于后续决策。

## 六、测试与验证

| 门 | 命令 / 选择 | 结果 |
|---|---|---|
| 初始全量 | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:randomly` | 8480 passed / 26 failed / 73 skipped，1238.88 s |
| 基线隔离复跑 | 同命令指定 26 个失败 node，进程内设置规范化 `TMPDIR` | 9 passed / 17 failed，4.64 s |
| test-first | 符号选择 `test_missing_key_opens_its_own_settings\|test_authentication_notification_routes\|test_settings_process_cold_start_selects` | 原产品 6 failed，6.69 s；后续聚焦中全部通过 |
| 相关族 | `rg -l 'AiRuntime\|AiPackageRuntime\|ai_bindings\|settings_mod_domain\|OwnerSettingsPanel\|select_page' tests -g 'test_*.py'`，排序后运行 | 360 passed / 2 failed，121.85 s；旧 Shell 桩补齐后在最终全量中通过，另一条为基线 screen menu 失败 |
| ruff | `.venv/bin/python -m ruff check pet tests scripts` 加本次 4 个包内 Python 文件 | 通过 |
| 受影响时序族满载 3 遍 | `rg -l 'AiRuntime\|AiPackageRuntime\|ai_bindings' tests -g 'test_*.py'`，10 个 CPU 负载进程 | 每轮 74 passed，17.15 / 17.14 / 18.03 s；107 个 CPU 样本平均 94.89%，峰值 100% |
| 首个实现提交全量 | 规范化 `TMPDIR` 后完整 pytest，不跳过既有失败 | 8494 passed / 20 failed / 73 skipped，1236.58 s；失败集合是原基线的子集，没有新增失败；复审后结果见 §八 |

基线额外失败的定位证据：默认 macOS 临时目录 `/var/folders/...` 被 `safe_path`
拒绝；解析为 `/private/var/folders/...` 则通过，6 条相关用例恢复。已知 3 条
workers lifecycle flake 隔离复跑通过，未修改。剩余 17 条包括：

- `test_frozen_runtime_paths.py` 5 条：把 `sys.platform` 设成 Windows 后仍传 POSIX
  临时路径，被 Windows 本机盘符校验以 `frozen_runtime_layout` 拒绝。
- `test_proactive_worker_adapter.py` 9 条：macOS 实际没有 `msvcrt` 模块。
- `test_workers_lifecycle.py::test_destroying_a_running_supervisor_kills_the_child_without_stderr_tracebacks`：子进程调用不存在的 `tasklist`。
- `test_island_bevel_fade.py::test_sample_value_change_never_fades`：取样 36，断言至少 60。
- `test_screen_package_e2e.py::test_enable_mounts_the_screen_menus_and_manual_look_runs`：预期的主动识屏子菜单为 None。

这些失败已在修改产品代码前观察并隔离复现。本任务没有修它们，也没有删测试、
添加 skip 或伪称全量通过。首个实现提交全量出现上述 17 条及原有 3 条生命周期 flake；
原定“全量必过”的发布门尚未满足，推送和 PR 需要用户明确接受本次基线例外。

## 七、风险与回滚

变化集中在 DLC 呈现回调和扩展设置装配；没有新数据格式。回滚本任务两个提交
恢复无跳转入口的旧行为，已由扩展设置保存的数据仍使用既有格式。独立设置进程
仍只有一个，新增局部导航端点在进程退出时关闭。已有错误槽位作用域的凭据引用不会自动迁移；若遇到此类引用，
需在扩展设置重新保存 Key，旧钥匙串条目不会被擅自删除。
既有全量失败的发布处理须由用户/维护者明确决定。

## 八、复审修复（R1 / R2）

首次自审发现两项 P2，均在产品改动前写出失败回归：已有设置窗口只提示“已打开”、
没有跳转；请求过程中保存通知开关后，完成通知仍读取运行时旧值。此次修复还通过
回归定位了启动锁尚未建立、窗口退出已删除 Qt 对象、导航改变最大化状态的边界。

### 复审测试与验证

`fix-red.log`：已有窗口及请求中保存关/开三例 **3 failed，40.97 s**；
`fix-startup-red.log`：未持锁的启动窗口 **1 failed，7.06 s**；
`fix-window-state-red.log`：最大化保持 **1 failed，2.90 s**。修正后全部通过。

相关族按符号选择：

```sh
rg -l 'AiRuntime|AiPackageRuntime|ai_bindings|settings_mod_domain|OwnerSettingsPanel|select_page|AiSettingsRequest|_exec_settings|open_settings_process|notifications_enabled' tests -g 'test_*.py'
```

排序后运行 27 个文件：**814 passed / 1 failed / 2 skipped，154.65 s**；唯一失败为
基线识屏菜单用例。包含真实独立设置进程两次跳转、未持锁启动、未知/超长消息、
不可达超时、正在运行的真实 HTTP401 请求中保存通知关/开，以及配置草稿/CAS 冲突保护。
Qt 测试使用事件循环；HTTP 用 Event 同步，没有用固定 sleep 猜测完成。

Ruff 已通过。时序族按 `AiRuntime|AiPackageRuntime|ai_bindings|AiSettingsRequest|_exec_settings|open_settings_process`
匹配并排序得到 14 个文件，使用相同 pytest 参数，在 10 个 CPU 负载进程下连续跑三遍：
**每轮 268 passed / 1 skipped**，86.86 / 86.46 / 91.05 s。
每个负载进程执行 `while True: sum(i*i for i in range(10000))`，531 个 CPU 样本平均
95.29%、峰值 100%；所有负载进程均已 terminate/wait 收口。

2026-10-16 最终全量：**8502 passed / 20 failed / 73 skipped，1321.78 s**。
20 个失败 node 与首个实现提交完全相同，且全部存在于原始基线；逐项集合比较
`new_vs_baseline=[]`、`new_vs_prior=[]`。测试前后本任务 Python 文件 SHA256 一致，
`changed_tested_sources=[]`。没有新增失败；已知生命周期 flake 未修改。
三条已知 flake 是 `test_teardown_leaves_no_process_timer_or_thread_residue`、
`test_bounded_drain_persists_the_stop_to_a_slow_worker` 和
`test_finish_app_shutdown_drains_inside_the_deadline`，其余 17 条见 §六。
全量仍未全绿，因此暂不推送或开 PR，必须先取得用户对基线例外的明确接受。

全量命令未排除既有失败：

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:randomly
```

在调用进程中将 `TMPDIR` 设为 `str(Path(tempfile.gettempdir()).resolve())`。

### 复审性能分析

同机、无 CPU 负载、Qt offscreen；真实 AppShell、真实包、真实独立 `_exec_settings`，
未替换配置或 IPC。探针完整源码在附录，运行：

```sh
QT_QPA_PLATFORM=offscreen PET_RENDER_TOPOLOGY=legacy .venv/bin/python .scratch/dlc-ai-runtime-callbacks/fix_probe.py perf
```

| 路径 / 样本 | 实测 |
|---|---:|
| 读取缓存通知开关，n=2000，中位 / P95 | 0.000291 / 0.000333 ms |
| 读取已保存通知开关，n=2000，中位 / P95 | 0.073084 / 0.087750 ms |
| 已有窗口首次打开 owner，n=1 | 113.5921 ms |
| 跨进程请求至收到确认，n=100，中位 / P95 | 1.5900 / 1.8762 ms |
| 再发 500 次，开启 tracemalloc，中位 / P95 | 2.1580 / 2.6528 ms |
| 500 次后的 Python 保留增量（主进程） | +30,178 B |
| 500 次后的 RSS 增量（主 / 设置进程） | +98,304 / +344,064 B |
| OS 线程数，采样前 → 后（主 / 设置进程） | 7 / 3 → 7 / 3 |
| 设置进程静置 CPU 时间 / 墙钟，n=1 | 0.077844 / 4.949136 s |

配置测量先实际保存 chat 和 ui 命名空间，读取的是存在的配置文件。每次符合后台
通知条件时新增一次有界文件读取（端口上限 1 MiB）、文件元数据检查和 JSON 解析；
无通知回调或聊天窗口为活动窗口时不读。不重置配置草稿，不更新编辑器 CAS 版本。
相比缓存读，中位增加 0.072793 ms；这不是每帧路径，频率由完成/失败/授权提示触发。

跨进程导航按用户点击触发，新增本地 socket 连接/读写及锁文件读取；无外部网络、
磁盘写入或工作线程。设置进程存活期间多一个监听端点；每次请求只有短期 socket 和
计时器，确认或失败后删除。客户端确认计时含 1 ms 探针检查，首次 owner 确认含
20 ms 子进程探针检查；确认表示请求已接收，不等同于后续模态草稿门已完成。
静置采样包含子进程探针自己的 20 ms 检查，不能归因于空闲接收器。
RSS 与 Python 保留量均有小幅增长，未声称长期零增长或做严格的分配归因。

### 复审实机运行记录

2026-10-15，本机 Cocoa、真实包与独立设置子进程，不使用 mock 或真实服务商 Key：

```sh
QT_QPA_PLATFORM=cocoa PET_RENDER_TOPOLOGY=legacy .venv/bin/python .scratch/dlc-ai-runtime-callbacks/fix_probe.py native
```

实际输出：`platform=cocoa`，已有窗口首次跳转 `497.982958 ms`（n=1），
`owner=official.ai-chat`，`key_inside_viewport=true`，`maximized=true`，
`pet_app_imported=false`，`draft_retained_after_navigation=true`，
`notification_after_saved_off=false`，`notification_after_saved_on=true`，
`draft_dirty=true`，`child_exit=0`。原输入仍为“已有设置窗口也应跳转，保留这条输入。”

已目视检查 [已有窗口跳转截图](screenshots/ai-window-callbacks-2026-10-15/existing-settings.png)
和 [重新保存开启后的通知](screenshots/ai-window-callbacks-2026-10-15/saved-notification.png)。
两个进程独立读取同一包配置；已保存值覆盖旧运行时缓存，未保存的相反值与 Key 草稿
仍保留。实机通知通过公开授权提示入口触发；请求中 HTTP401 链由回归测试覆盖。

### 复审结论与范围

实现者复审 R1/R2 后未发现新的可操作缺陷；这是实现者自审，未冒充独立审查。
检查了协议限长/截止、进程退出、锁竞争、草稿、窗口状态与通知保存语义。
Windows/Linux 原生 IPC 和新的冻结产物仍未实测。新增 QtNetwork 使用现有 PySide6
依赖，不修改包依赖或构建脚本。请求只接受固定 AI owner 导航，没有任意命令或凭据。
Qt 的 `UserAccessOption` 在 macOS 不提供 Unix socket 文件权限隔离，不能把本端点
当作授权边界；具体平台行为见 [QLocalServer 官方文档](https://doc.qt.io/qtforpython-6/PySide6/QtNetwork/QLocalServer.html)。

导航：[PORT-STATUS](modding/PORT-STATUS.md) · [全文档索引](INDEX.md)

## 附录：本次临时验收探针

将下列代码分别保存为报告命令所示的临时文件。探针未接入构建或 CI。

在新的临时目录重建基线包（当前包由探针直接构建）：

```sh
mkdir -p .scratch/dlc-ai-runtime-callbacks/base-source
git archive f824289e8facb725f552b1b2168bf3400b38e9c8 features/ai-chat | tar -x -C .scratch/dlc-ai-runtime-callbacks/base-source
.venv/bin/python - <<'PY'
from pathlib import Path
from scripts.build_ai_chat_package import build_package
root = Path('.scratch/dlc-ai-runtime-callbacks').resolve()
build_package(root / 'base-source/features/ai-chat', root / 'base-package')
PY
```

<details>
<summary>native_probe.py</summary>

```python
from pathlib import Path
import json
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from pet.app import AppShell
from pet.config import Config
from tests.ai_package_fakes import OWNER, build_package, dispose_qobject
from pet.settings_mod_domain import close_extension_settings

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
stage = sys.argv[1] if len(sys.argv) > 1 else "current"
out = ROOT / ".scratch/dlc-ai-runtime-callbacks"

def pump(check, timeout=30):
    deadline = time.monotonic() + timeout
    while not check() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    assert check()

with tempfile.TemporaryDirectory(prefix="native-", dir=out) as data:
    cfg = Config(base=Path(data).resolve())
    cfg.set("settings_process_isolation", False)
    shell = AppShell(app, cfg, enable_chat=False)
    manager = shell.feature_runtime.attach_official(OWNER)
    package = out / "base-package" if stage == "base" else build_package(Path(data) / "built")
    assert manager.submit("import_disabled", package, auto_apply=True)
    pump(lambda: not manager.busy)
    assert manager.submit("enable", True, expected_revision=manager.service.inspect().revision)
    pump(lambda: not manager.busy)
    mount = shell.feature_runtime.mounts.runtimes[OWNER]
    window = mount.chat()
    window.input.setPlainText("没有保存 Key，这条消息应保留。")
    window.send_message()
    window.activateWindow()
    pump(window.isActiveWindow)
    app.processEvents()
    window.grab().save(str(out / f"native-{stage}-missing-key.png"))
    result = {"platform": app.platformName(), "stage": stage,
              "window_visible": window.isVisible(), "hint": window.provider_label.text(),
              "input_retained": window.input.toPlainText(), "request_started": window.service.busy}
    if stage != "base":
        QTest.mouseClick(window.provider_label, Qt.MouseButton.LeftButton)
        pump(lambda: shell.instance.modern_settings_dialog is not None)
        dialog = shell.instance.modern_settings_dialog
        pump(dialog.isVisible)
        app.processEvents()
        panel = dialog.mod_panel
        key = panel.component.page.key
        scroll = dialog.pages.currentWidget().findChild(QScrollArea, "settingsScroll")
        from PySide6.QtCore import QPoint, QRect
        in_view = QRect(key.mapTo(scroll.viewport(), QPoint()), key.size())
        result.update(owner=panel.owner, key_visible=key.isVisibleTo(dialog),
                      key_inside_viewport=scroll.viewport().rect().contains(in_view),
                      credentials_scope_matches=panel.component.config.context.credentials.scope == mount.runtime.config.context.credentials.scope)
        dialog.grab().save(str(out / "native-current-settings.png"))
        key.setText("unsaved-native-draft")
        QTest.mouseClick(window.provider_label, Qt.MouseButton.LeftButton)
        result["draft_retained"] = dialog.mod_panel is panel and key.text() == "unsaved-native-draft"
        panel.discard_changes()
        close_extension_settings(dialog)
        dialog.mod_host.shutdown()
        dialog.hide()
        dialog.deleteLater()
        shell.instance.modern_settings_dialog = None
        background = QWidget()
        background.show()
        background.activateWindow()
        pump(background.isActiveWindow)
        window.hide()
        window.notify_authorization_required("本机 DLC 通知验收：点击返回包窗口。")
        pump(lambda: bool(shell._toast_windows))
        toast = shell._toast_windows[-1]
        toast.grab().save(str(out / "native-current-notification.png"))
        result["notification_visible"] = toast.isVisible()
        assert manager.submit("enable", False, expected_revision=manager.service.inspect().revision)
        pump(lambda: not manager.busy)
        QTest.mouseClick(toast, Qt.MouseButton.LeftButton)
        result["late_click_stayed_closed"] = not window.isVisible() and shell.instance.modern_settings_dialog is None
        background.close()
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    dispose_qobject(mount)
    shell.feature_runtime.close()
    AppShell._shutdown_live_for_tests()
    app.processEvents()

```

</details>

<details>
<summary>perf_probe.py</summary>

```python
from pathlib import Path
import gc
import json
import statistics
import sys
import tempfile
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import psutil
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pet.app import AppShell
from pet.config import Config
from tests.ai_package_fakes import OWNER, build_package, dispose_qobject
from pet.settings_mod_domain import close_extension_settings

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
stage = sys.argv[1]
out = ROOT / ".scratch/dlc-ai-runtime-callbacks"
process = psutil.Process()

def pump(check, timeout=30):
    deadline=time.monotonic()+timeout
    while not check() and time.monotonic()<deadline:
        loop=QEventLoop();QTimer.singleShot(10,loop.quit);loop.exec()
    assert check()

def measure(fn,n):
    values=[]
    for _ in range(n):
        start=time.perf_counter_ns();fn();values.append((time.perf_counter_ns()-start)/1e6)
    return {"n":n,"median_ms":round(statistics.median(values),4),"p95_ms":round(sorted(values)[int(n*.95)-1],4)}

with tempfile.TemporaryDirectory(prefix="perf-",dir=out) as data:
    config=Config(base=Path(data).resolve());config.set("settings_process_isolation",False)
    shell=AppShell(app,config,enable_chat=False)
    manager=shell.feature_runtime.attach_official(OWNER)
    package=out/"base-package" if stage=="base" else build_package(Path(data)/"built")
    assert manager.submit("import_disabled",package,auto_apply=True);pump(lambda:not manager.busy)
    assert manager.submit("enable",True,expected_revision=manager.service.inspect().revision);pump(lambda:not manager.busy)
    mount=shell.feature_runtime.mounts.runtimes[OWNER]
    result={"stage":stage,"platform":app.platformName()}
    start=time.perf_counter_ns();window=mount.chat();app.processEvents()
    result["first_window_ms"]=(time.perf_counter_ns()-start)/1e6
    window.input.setPlainText("missing key performance probe")
    window.send_message()
    result["missing_key"]=measure(window.send_message,300)
    result["threads_before_settings"]=process.num_threads()
    loop=QEventLoop();QTimer.singleShot(5000,loop.quit)
    start_wall=time.monotonic();start_cpu=time.process_time();loop.exec()
    result["idle_before_settings_wall_s"]=time.monotonic()-start_wall
    result["idle_before_settings_cpu_s"]=time.process_time()-start_cpu
    if stage!="base":
        def open_settings():
            QTest.mouseClick(window.provider_label,Qt.MouseButton.LeftButton);app.processEvents()
        start=time.perf_counter_ns();open_settings()
        result["first_settings_ms"]=(time.perf_counter_ns()-start)/1e6
        dialog=shell.instance.modern_settings_dialog
        assert dialog.mod_panel.owner==OWNER
        result["repeated_settings"]=measure(open_settings,100)
        panel=dialog.mod_panel
        tracemalloc.start();gc.collect()
        before_py=tracemalloc.get_traced_memory()[0];before_rss=process.memory_info().rss
        result["repeated_settings_memory_batch"]=measure(open_settings,500)
        gc.collect()
        result["python_retained_delta_bytes"]=tracemalloc.get_traced_memory()[0]-before_py
        result["rss_delta_bytes"]=process.memory_info().rss-before_rss
        result["same_panel_after_600_clicks"]=dialog.mod_panel is panel
        result["threads_after_settings"]=process.num_threads()
        tracemalloc.stop()
        close_extension_settings(dialog);dialog.mod_host.shutdown();dialog.hide();dialog.deleteLater()
        shell.instance.modern_settings_dialog=None
    loop=QEventLoop();QTimer.singleShot(5000,loop.quit)
    start_wall=time.monotonic();start_cpu=time.process_time();loop.exec()
    result["idle_wall_s"]=time.monotonic()-start_wall
    result["idle_cpu_s"]=time.process_time()-start_cpu
    result["rss_end_bytes"]=process.memory_info().rss
    print(json.dumps(result,indent=2),flush=True)
    dispose_qobject(mount);shell.feature_runtime.close();AppShell._shutdown_live_for_tests();app.processEvents()

```

</details>

<details>
<summary>fix_settings_host.py</summary>

```python
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from pet.__main__ import _exec_settings
from pet.config import Config

root, out, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
app = QApplication([])
phase = 0
original = None

def publish(name, value):
    temp = root / (name + '.tmp')
    temp.write_text(json.dumps(value), encoding='utf-8')
    temp.replace(root / name)

def inspect():
    global phase, original
    try:
        dialog = next(w for w in app.topLevelWidgets() if hasattr(w, 'mod_panel_owner'))
        if phase == 0:
            assert dialog.sidebar.currentItem().text() == '常规'
            dialog.showMaximized()
            publish('ready.json', {'page': '常规', 'platform': app.platformName()})
            phase = 1
        elif (phase == 1 and dialog.mod_panel_owner == 'official.ai-chat'
              and dialog.sidebar.currentItem().text() == '扩展管理'):
            panel = dialog.mod_panel
            key = panel.component.page.key
            scroll = dialog.pages.currentWidget().findChild(QScrollArea, 'settingsScroll')
            inside = scroll.viewport().rect().contains(QRect(key.mapTo(scroll.viewport(), QPoint()), key.size()))
            assert inside and key.isVisibleTo(dialog) and dialog.isMaximized()
            assert 'pet.app' not in sys.modules
            if mode == 'native':
                dialog.grab().save(str(out / 'fix-native-existing-settings.png'))
            original = panel
            if mode == 'native':
                key.setText('unsaved-native-draft')
                dialog.select_page('常规')
            publish('first.json', {'owner': panel.owner, 'key_inside_viewport': inside,
                    'maximized': dialog.isMaximized(), 'pet_app_imported': False})
            phase = 2
        elif (phase == 2 and mode == 'native' and dialog.sidebar.currentItem().text() == '扩展管理'):
            panel = dialog.mod_panel
            assert panel is original and panel.component.page.key.text() == 'unsaved-native-draft'
            panel.discard_changes()
            panel.component.page.system_notify_check.setChecked(False)
            QTest.mouseClick(panel.save_button, Qt.MouseButton.LeftButton)
            assert not panel.dirty()
            panel.component.page.key.setText('unsaved-native-draft')
            panel.component.page.system_notify_check.setChecked(True)
            publish('off.json', {'draft_retained_after_navigation': True, 'saved': False, 'draft': True})
            phase = 3
        elif phase == 3 and (root / 'enable').exists():
            panel = dialog.mod_panel
            panel.discard_changes()
            panel.component.page.system_notify_check.setChecked(True)
            QTest.mouseClick(panel.save_button, Qt.MouseButton.LeftButton)
            assert not panel.dirty()
            panel.component.page.key.setText('unsaved-native-draft')
            panel.component.page.system_notify_check.setChecked(False)
            publish('on.json', {'saved': True, 'draft': False, 'draft_dirty': panel.dirty()})
            phase = 4
        if (root / 'quit').exists():
            app.quit()
    except Exception:
        import traceback
        traceback.print_exc()
        app.exit(1)

timer = QTimer()
timer.setInterval(20)
timer.timeout.connect(inspect)
timer.start()
raise SystemExit(_exec_settings(app, Config(base=root), include_ai=False))

```

</details>

<details>
<summary>fix_probe.py</summary>

```python
import gc
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import psutil
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pet.app import AppShell
from pet.config import Config
from tests.ai_package_fakes import OWNER, build_package, dispose_qobject
from pet.settings_extension_navigation import AiSettingsRequest

mode = sys.argv[1]
out = ROOT / '.scratch/dlc-ai-runtime-callbacks'
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
process = psutil.Process()

def pump(check, timeout=30):
    end = time.monotonic() + timeout
    while not check() and time.monotonic() < end:
        loop = QEventLoop()
        QTimer.singleShot(1, loop.quit)
        loop.exec()
    assert check(), 'probe deadline'

def measure(fn, n):
    values = []
    for _ in range(n):
        start = time.perf_counter_ns()
        fn()
        values.append((time.perf_counter_ns() - start) / 1e6)
    return {'n': n, 'median_ms': statistics.median(values), 'p95_ms': sorted(values)[int(n * .95) - 1]}

with tempfile.TemporaryDirectory(prefix='fix-probe-', dir=out) as temp:
    root = Path(temp).resolve()
    config = Config(base=root)
    config.set('settings_process_isolation', True)
    shell = AppShell(app, config, enable_chat=False)
    manager = shell.feature_runtime.attach_official(OWNER)
    package = build_package(root / 'built')
    assert manager.submit('import_disabled', package, auto_apply=True)
    pump(lambda: not manager.busy)
    assert manager.submit('enable', True, expected_revision=manager.service.inspect().revision)
    pump(lambda: not manager.busy)
    mount = shell.feature_runtime.mounts.runtimes[OWNER]
    window = mount.chat()
    window.input.setPlainText('已有设置窗口也应跳转，保留这条输入。')
    window.send_message()
    with (out / f'fix-{mode}-child.log').open('w') as log:
        child = subprocess.Popen([sys.executable, '-u', str(out / 'fix_settings_host.py'), str(root), str(out), mode], stdout=log, stderr=subprocess.STDOUT)
        try:
            pump(lambda: (root / 'ready.json').exists() or child.poll() is not None)
            assert child.poll() is None
            start = time.perf_counter_ns()
            QTest.mouseClick(window.provider_label, Qt.MouseButton.LeftButton)
            pump(lambda: (root / 'first.json').exists() or child.poll() is not None)
            first_ms = (time.perf_counter_ns() - start) / 1e6
            result = {'platform': app.platformName(), 'mode': mode, 'first_owner_route_ms': first_ms,
                      **json.loads((root / 'first.json').read_text())}
            assert shell.instance.modern_settings_dialog is None and not shell._toast_windows
            if mode == 'native':
                QTest.mouseClick(window.provider_label, Qt.MouseButton.LeftButton)
                pump(lambda: (root / 'off.json').exists())
                result['saved_off'] = json.loads((root / 'off.json').read_text())
                window.hide()
                app.processEvents()
                window.notify_authorization_required('保存关闭后，这条通知应被抑制。')
                assert not shell._toast_windows
                result['notification_after_saved_off'] = False
                (root / 'enable').touch()
                pump(lambda: (root / 'on.json').exists())
                result['saved_on'] = json.loads((root / 'on.json').read_text())
                window.notify_authorization_required('已读取最新保存值；未保存草稿仍然保留。')
                pump(lambda: bool(shell._toast_windows))
                toast = shell._toast_windows[-1]
                assert toast.isVisible()
                toast.grab().save(str(out / 'fix-native-notification.png'))
                result['notification_after_saved_on'] = True
                toast.close()
                result['input_retained'] = window.input.toPlainText()
            else:
                child_process = psutil.Process(child.pid)
                cfg = mount.runtime.config
                cfg.set('system_notifications_enabled', True)
                cfg.set_chat_settings(cfg.chat_settings())
                cfg.save()
                result['cached_preference_read'] = measure(lambda: cfg.get('system_notifications_enabled', True), 2000)
                result['committed_preference_read'] = measure(cfg.notifications_enabled, 2000)
                def navigate():
                    failures = []
                    request = AiSettingsRequest(config.dir, lambda: failures.append(True))
                    pump(lambda: request.finished)
                    assert not failures
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                result['ipc_ack'] = measure(navigate, 100)
                gc.collect()
                tracemalloc.start()
                py_before = tracemalloc.get_traced_memory()[0]
                parent_rss = process.memory_info().rss
                child_rss = child_process.memory_info().rss
                threads = (process.num_threads(), child_process.num_threads())
                result['ipc_memory_batch'] = measure(navigate, 500)
                gc.collect()
                result['retained_python_delta_bytes'] = tracemalloc.get_traced_memory()[0] - py_before
                tracemalloc.stop()
                result['rss_delta_bytes'] = {'parent': process.memory_info().rss - parent_rss,
                                             'child': child_process.memory_info().rss - child_rss}
                result['threads_before'] = threads
                result['threads_after'] = (process.num_threads(), child_process.num_threads())
                cpu_before = sum(child_process.cpu_times()[:2])
                wall = time.monotonic()
                loop = QEventLoop()
                QTimer.singleShot(5000, loop.quit)
                loop.exec()
                result['child_idle_wall_s'] = time.monotonic() - wall
                result['child_idle_cpu_s'] = sum(child_process.cpu_times()[:2]) - cpu_before
            (root / 'quit').touch()
            pump(lambda: child.poll() is not None)
            assert child.returncode == 0
            result['child_exit'] = child.returncode
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
    dispose_qobject(mount)
    shell.feature_runtime.close()
    AppShell._shutdown_live_for_tests()
    app.processEvents()

```

</details>
