# PR 报告：DLC AI 回调复审缺陷修复 + 移植账本校准

> **基线**：`e5788b0`（PR #282 合入 `dlc/mod-center-port`）
> **分支**：`dlc/mod-center-port`　**日期**：2026-10-17
> **范围**：11 个文件（实现 4、测试 2、文档 5）
> **关联**：[`PR-REPORT-AI-WINDOW-CALLBACKS-2026-10-15.md`](PR-REPORT-AI-WINDOW-CALLBACKS-2026-10-15.md)（PR #282 的原始交付报告）

## 一、核心特性

PR #282 把 AI 扩展包的「通知」与「跳自己的设置页」接上线之后，交接文件（`DLC-HANDOFF-2026-10-15.md`）
§6.2 第 1 件按验收口径过了一遍，剩下三条可复现缺陷；同时 `PORT-STATUS.md` 有 6 处判定与作者分支
实测不符、且整片「主干减法」不在文档坐标系里。本片处理这两件事。

| # | 缺陷 | 用户看到什么 | 根因 |
|---|---|---|---|
| 1 | 深链接冷启动后设置页搜索失灵 | 从包窗点「打开 API 设置」进入设置页 → 之后在搜索框一按键就抛 `libshiboken: Internal C++ object (SettingRow) already deleted`，搜索永远没结果 | `ModernSettingsDialog.__init__` 里 `initial_page` 深链接在 `_search_rows = findChildren(SettingRow)` **之前**执行，扩展面板的行被收进快照；面板后来被收走（`dispose()` → `setParent(None)` + `deleteLater()`），快照里留下已删的 C++ 对象 |
| 2 | 配好 Key 回来表头还挂着旧提示 | 缺 Key 发送 → 表头变成蓝色链接「打开 API 设置」→ 点它配好 Key → 回到同一个窗口发送成功 → 表头**仍是**那个链接，tooltip 仍是旧错误文案 | 链接只由 `_begin_generation` 的错误分支写入，唯一恢复点是 `refresh_settings()`，而它只由 `runtime._api_changed` 触发；AI 包的 `context.api` 恒为 `None`（`pet/feature_host_bindings.py:501`），所以 `_api_changed` 永不触发 |
| 3 | 导航失败时点击方零反馈 | 点「打开 API 设置」→ 设置窗被拉到前台、停在扩展管理页、面板一片空白；主进程既没有报错也没有重试入口 | `_navigate` 前就 `socket.write(_ACK)`，而 `dialog.select_page(...)` 的返回值被丢弃——草稿门取消切 owner、目标包挂不上设置面板这两种 `False` 都变成"成功" |

**红线 / 不变量**（本片一位没动）：内置 `pet/chat/` 一个字节不改；导航端点仍只认固定 AI owner
路由（不接受任意命令、不传凭据）；不新增常驻定时器、worker 线程或轮询；`AiSettingsReceiver`
仍是设置进程里唯一持有 `settings.lock` 期间才存在的对象。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/settings_extension_navigation.py` | +28 / −15 | 应答挪到导航之后：`receive` 收到完整请求只 `deadline.stop()`，把 socket 交给 `QTimer.singleShot(0, …)` 排的 `_navigate(socket)`；`_navigate` 拿 `select_page` 的布尔结果，成功回 `_ACK`、失败回 `b"no\n"`，再 `disconnectFromServer()`。并发点击（`_navigating` 为真）按同一目标回 `_ACK`；`_closed` 时直接 `abort()`。客户端不用改——它本来就有「收到非 ACK 前缀立即失败」的分支（`_received`），现在成了失败快路径 |
| `pet/modern_settings_dialog.py` | +4 / −1 | 把 `self._search_rows = self.findChildren(SettingRow)` 移到 `if self.initial_page:` **之前**。搜索索引只收 Core 自身的设置行，扩展面板的行不再进快照——这也让两条入口口径一致（事后深链接挂面板时快照早已取完，本来就不进索引） |
| `features/ai-chat/host/chat/widgets.py` | +4 / −0 | `_begin_generation` 在 `prepare_request` 成功、`self.settings` 拿到最新值之后还原表头（`active_config.model` + 同文案 tooltip）。放在这里而不是 `send_message`：`send_message` 与 `retry_last` 两条路径都汇聚到 `_begin_generation`，一处覆盖两条 |
| `features/ai-chat/host/chat/legacy_widgets.py` | +3 / −0 | 同上，但用 `active_config.name`——legacy 窗口的表头一直是 name，且它的 `refresh_settings` 连 tooltip 都不恢复（既有缺口），这里一并补上 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_ai_window_callbacks.py` | +76 / −0 | 三条新用例，各对应上面一条缺陷：`test_deep_linked_extension_rows_never_enter_the_core_search_index`（断言面板行与 `_search_rows` 无交集 + 收走后 `_search_settings("api")` 不抛）、`test_a_successful_send_restores_the_provider_header`（先撞缺 Key 拿到链接，配好 Key 发送后断言表头等于 `active_config.model`）、`test_navigation_failure_is_reported_instead_of_a_premature_ok`（遮住 `select_page` 让它返回 `False`，断言点击方拿到失败而不是静默成功） |
| `tests/test_architecture.py` | +3 / −1 | 设置页行数预算按该测试自己的约定校准 2415 → 2418：本片在 `modern_settings_dialog.py` 原地加了 3 行说明性注释（为什么快照必须先于深链接），没有新增控件或页面。带日期注释写在常量上方 |

### 文档

| 文件 | 增删 | 改动 |
|---|---|---|
| `docs/modding/PORT-STATUS.md` | +117 / −19 | 6 处判定修正（§一-4 打包链、Phase 1「不适用」过宽、Phase 2 往悲观方向过期、Phase 4A 识屏文件数 15→18 且 `services.py` 已存在、Phase 5A「五个脚本全不存在」、§七 把生成物 `build_variant.py` 当脚本 + 「D5 才拆」已拆）；§十 补复审三条；新增 **§十一 未移植账本** 与 **§十二 主干减法登记** |
| `docs/modding/README.md` | +6 / −2 | 移植状态指针补上 §十一/§十二；「仍未落地」从「host-worker 冻结 + LPAC」改全（内容硬门、Phase 2 内核、冻结/Setup/签名链；LPAC 是拍板不做） |
| `docs/DLC-HANDOFF-2026-10-15.md` | +2 / −1 | §6.2 第 1 件标为已交付；§5 已完成清单加一行（PR #282 合入 + 本片三条复审） |
| `docs/INDEX.md` | +1 / −0 | 「PR 报告存档」登记本报告（新文档入场规则第 1 条，机器校验 `test_report_is_registered_in_index`） |
| `docs/PR-REPORT-AI-CALLBACK-REVIEW-FIXES-2026-10-17.md` | 新增 155 行 | 本报告 |

### 未改动（看起来相关但故意没动）

- `pet/app.py::_open_ai_package_settings`：`_ai_settings_request` 没有失效路径（超时前关掉再重开设置页，会收到一条迟到的失败通知）。改它要动 App 层请求生命周期，属独立一片；本片只修"导航结果被丢弃"这一侧。
- `pet/settings_mod_domain.py::select_extension_settings`：切 owner 失败时会先销毁当前可见面板。它需要第二个扩展包才触发（固定路由只有 `official.ai-chat`），且草稿有门保住，留作独立一片。
- 内置 `pet/chat/`：不动（硬边界）。

## 三、实现要点

**缺陷 3 的取舍：为什么不回一个结构化错误码。** 协议是 12 字节明文、单向、无认证，加字段只会让对端多一个必须同步的契约。改成「成功 `ok\n` / 失败 `no\n`」后，客户端那条 `elif not _ACK.startswith(self._reply): self._finish(False)` 分支天然接住失败，`AiSettingsRequest` 一行不用改——失败从"5 秒后超时"变成"立刻"。

**缺陷 3 为什么不连 `_navigate` 的异常也回否。** `_navigate` 的 `finally` 只复位 `_navigating`；`select_page` 自己吞了草稿门取消（返回 `False`），真正会抛的是 Qt 层异常。当前 `_navigate` 在 `singleShot` 回调里，抛出去会被 PySide6 打到 stderr 且 socket 得不到应答 → 客户端超时失败，语义仍正确，所以没有加 try/except（不做防御性编程）。

**缺陷 1 为什么改时序而不是加 `isValid` 过滤。** 面板行本来就不该出现在 Core 设置搜索里——它们是包自己的设置项，作者包的搜索面归包。改时序一处即让两条入口口径一致；在消费侧撒 `isValid` 只是把症状按住，`_search_rows` 仍会随每次深链接增长。

**缺陷 2 为什么不在 `_focus_auth_settings` 里清表头。** 用户点了链接但可能在设置页点了取消——那时表头还该是提示（是真的没配好）。恢复点必须挂在"请求真的通过"上，也就是 `prepare_request` 之后。

## 四、性能分析

**方法**：`QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:randomly <files>`
环境：Windows / Python 3.13.7 / PySide6 6.11.2 / 本机单活动屏

| 指标 | 实测 | 归属 |
|---|---|---|
| 三条新用例整组耗时 | 修复前 10.88 s（3 failed）/ 修复后 10.29 s（3 passed），同一命令同一机 | 新增 |
| 宽聚焦族（9 文件） | 310 passed / 1 failed（行数预算红，已校准）/ 142.89 s | 既有 |
| `_search_settings` 每次按键遍历量 | 深链接入口下**少 15 行**（扩展面板的 `SettingRow` 不再进 `_search_rows`）→ 每键少 15 次 `row.property("searchMatch")` | 既有路径，本片减少 |
| 表头恢复 | 每次成功发送 +2 次 `QLabel.setText` / `setToolTip`（纯内存，无布局重算） | 新增 |
| 导航应答时机 | 从"收包即回"改为"`select_page` 返回后回"，代价 = 一次 `select_page` 调用（页切换 + 面板挂载，毫秒级）；用户点击频率 < 1 次/秒 | 新增 |

**结论**：① 稳态开销无变化——本片没有引入定时器、线程、系统调用、网络或磁盘 IO；
② 新增路径的绝对成本都是"每次用户点击一次"的量级（两次 QLabel 赋值、一次布尔判断），
触发频率受用户点击限制；③ 唯一的结构性变化是搜索索引的**行数变少**（少 15 行），
方向是更快而不是更慢；④ 内存没有增长：面板行不再被 `_search_rows` 长期持有，
反而少一份 Python wrapper 引用。

**没有基准脚本**——本片没有可优化的热点，写基准只会测到噪声。

## 五、实机运行记录

**本机真实环境**：Windows / Python 3.13.7 / PySide6 6.11.2，`QT_QPA_PLATFORM=offscreen`
（无真桌面交互）。全部证据来自真 Qt 控件、真打包 + 真验签、真子进程、真 loopback HTTP。

**① 缺陷 1 的现场复现（红/绿对照）**：把 4 个产品文件 `git stash` 掉、只留测试跑同一条命令，
三条全红；`git stash pop` 后三条全绿。修复前 `test_deep_linked_extension_rows_never_enter_the_core_search_index`
的失败点就是 `dialog._search_settings("api")` 抛 `RuntimeError`。

**② 缺陷 3 的现场输出**（修复前）：

```
>           assert failures == [True], "面板没挂上时点击方必须拿到失败"
E           AssertionError: 面板没挂上时点击方必须拿到失败
E           assert [] == [True]
```

**③ 用户可见行为的确认**：本片没有做真实桌面手点——`offscreen` 下没有真窗口，做不了
"看窗口被拉到前台"这类观察。要确认的是：包窗缺 Key 时表头是可点链接、点完落在扩展管理
页并能改 Key（由 `test_missing_key_opens_its_own_settings_and_preserves_input_and_drafts`
的鼠标路径与键盘路径两条覆盖，键盘路径是真的 Tab + Return 激活）。

**④ 边界与失败路径**：`test_navigation_receiver_refuses_unknown_or_oversized_commands`
（未知路由与超长命令必须让 socket 空着被拒）、`test_navigation_unavailable_reports_failure_once_and_finishes`
（根本没有设置进程时失败回调恰好一次）继续绿。

**⑤ 无法自动验证的能力**：真机 GUI 手点（无真窗口）、真双屏与混合 DPI（本机只有一块活动屏）、
三端 CI（本片只在 Windows 本机跑）。给出的是排查证据而不是沉默：本片改动不触及平台分支。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `python -m ruff check pet tests scripts` | All checks passed |
| 聚焦（新增三条） | `pytest -q tests/test_ai_window_callbacks.py -k "search_index or provider_header or premature_ok"` | 3 passed（修复前 3 failed） |
| 宽聚焦族（9 文件） | `pytest -q tests/test_ai_window_callbacks.py tests/test_ai_package_host.py tests/test_ai_package_e2e.py tests/test_mod_center_end_to_end.py tests/test_settings_mod_panel.py tests/test_settings_process_isolation.py tests/test_settings_page_guide.py tests/test_architecture.py tests/test_pr_report_discipline.py` | 校准前 310 passed / 1 failed（唯一失败是本片新加注释撞了设置页行数预算）；校准后 `tests/test_architecture.py` 单跑 15 passed，即那格转绿。宽族未在校准后整体重跑（同一批用例的其余 310 条不受一行常量改动影响） |
| 受影响时序族满载 3 遍 | `for i in 1 2 3; do pytest -q tests/test_ai_window_callbacks.py -k "search_index or provider_header or premature_ok"; done` | 3/3 全绿（11.33 / 10.70 / 10.41 s，每遍 3 passed） |
| 断言有效性 | 四条产品文件 stash 后重跑新增三条 | 3 failed（证明断言真的区分新旧实现） |
| 全量 | `QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:randomly tests/` | 见 §九 本轮补记 |
| 架构红线 | `tests/test_architecture.py` | 通过（行数预算已按约定校准并注明理由） |

## 七、已知限制与后续

- 交接 §6.2 的另外两件仍未做：**文件解读投喂**（Core 拖文件 → 包的 `FileInterpretController`）
  与 **MOD 中心「安装官方包」按钮**。
- 缺陷 2 的恢复只在"请求通过"时发生。若浏览器/网络在 `prepare_request` 之后失败（401），
  表头不会再变回链接——用户要从错误气泡里读原因。这是有意保留：表头不做状态机。
- PORT-STATUS 的校准是 **2026-10-17 的作者分支快照**（分支名属仓库内工作档案，见
  `.scratch/dlc-fusion/PLAN.md`；快照 HEAD 是 `11646be`）。
  作者分支继续前进时要重跑 §十一 的核对命令，不要照抄结论。
- 未移植清单（内容硬门、Phase 2 内核收口、冻结/Setup/签名链）与它们的卡路顺序写在
  `PORT-STATUS.md` §十一；主干减法（Agent 检测器那组 2669 行零替代）写在 §十二。

## 八、风险与回滚

**影响面**：设置页构造顺序、AI 包窗表头的两条路径、设置导航 IPC 的应答语义。没有新增配置键，
没有落盘格式变化，没有数据库/缓存迁移。

**回滚**：`git revert` 本提交即可，无残留状态——`_search_rows` 是进程内快照，IPC 端点带 pid
每次启动重算，表头是纯 UI。唯一需要一起回滚的是 `tests/test_architecture.py` 的预算校准
（否则回滚后 `modern_settings_dialog.py` 少 3 行、预算仍宽松，不会红，但注释会撒谎）。

**风险点**：IPC 应答改为导航后回，若 `select_page` 将来出现长时间阻塞（例如同步网络），
点击方会多等那段时间。当前 `select_page` 只做页切换 + 面板挂载 + `singleShot(0)` 滚动，
没有 IO；一旦出现阻塞型操作，应把它移出应答路径而不是加超时。

## 九、本轮补记

### 全量套件（2026-10-17，本机）

`QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:randomly tests/`
→ **4 failed / 8575 passed / 19 skipped，4664.71 s（1:17:44）**，共 8598 个用例。

| 失败 | 定性 | 证据 |
|---|---|---|
| `test_workers_lifecycle.py::test_teardown_leaves_no_process_timer_or_thread_residue`<br>`::test_bounded_drain_persists_the_stop_to_a_slow_worker`<br>`::test_finish_app_shutdown_drains_inside_the_deadline` | **负载 flake，非本片引入** | 三条都只在满载时红；隔离单跑 `pytest tests/test_workers_lifecycle.py` → **22 passed / 1 skipped**。DLC 交接文档 §5 与 §7.5 本就把这一族登记为"基线上也红的负载 flake，单跑全绿，别再『修』它们" |
| `test_desktop_pet_features.py::test_product_copy_has_no_external_brand_reference` | **本片引入，已修** | 账本初稿把作者实现分支名写进了 `PORT-STATUS.md` §十一 与本报告，而该守卫禁止 `pet/` `tests/` `docs/` 出现那个品牌词。**没有放宽守卫**，改的是措辞：按仓库既有口径把分支名留在 `.scratch/dlc-fusion/PLAN.md`（gitignored 工作档案），正文只写 `<作者实现分支>` + 快照 HEAD |

修后复核：`pytest -q tests/test_desktop_pet_features.py -k product_copy` → **1 passed**；
`pytest -q tests/test_pr_report_discipline.py tests/test_architecture.py` → **168 passed**；
`ruff check pet tests scripts` → All checks passed。

**这条抓得好**：它证明这轮的价值不在"跑绿了"，而在于隔离复跑把两条性质完全不同的红分开——
一条是已登记的负载 flake（全量红/单跑绿），一条是我自己刚造出来的真红（全量红/单跑也红）。
只看全量汇总的话，这四条会被一起当成"既有失败"糊过去。
