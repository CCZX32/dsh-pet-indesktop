# 桌宠本版集成交付证据报告（release/2026-10-08-candidate）

> **状态：待完成草稿（不是最终交付完成）**。本报告按「已验 / 未验」分栏写实，未验项在
> §七「未完发布条件」逐条列出。任何一节都**不**声称全产品已过或三端全过。
>
> **基线**：`ee699c7b693297cb324a01c72989902302dfd768`（Merge pull request #233
> `feature/agent-link-subtraction`，2026-10-06 21:54:38 +0800，即本分支起点上的主线末端）
> **分支**：`release/2026-10-08-candidate`　**HEAD**：`7b3fe8209ca622822d8b6807c647602ca7376d03`（2026-10-09 17:59:24 +0800）
> **统计对象**：**基线 → 当前工作树**（含未提交改动与未跟踪文件），不是 `HEAD` only
> **统计时点**：2026-10-11 04:40 (+08:00)（见 §0.2，文档自身变动不再回填）
> **范围**：298 个产品文件（实现 91、测试 153、文档 36、构建与打包 18），
> `+85859 / −4310`；其中 37 个文件仍是**未跟踪/未提交**状态（§2.6 显式枚举）
> **关联**：`docs/INDEX.md`「PR 报告存档」中本版各专项报告（逐批证据），以及本版
> 内存档的产品规范 `docs/PRODUCT-NEXT-STEPS-SPEC-2026-10-09.md`

## 0. 统计口径、可复现性与时点

### 0.1 数量是机器可验的

本报告里的每一处计数都由下面两个脚本产出，脚本与原始导出留在本机
`.scratch/product-delivery-report-20261011/`（该目录被 `.gitignore` 忽略，**不随 PR 交付**）。
命令与产物：

```
python .scratch/product-delivery-report-20261011/collect_file_inventory.py
python .scratch/product-delivery-report-20261011/collect_change_details.py
```

- `inventory.json` / `inventory.tsv` / `stats.json`：逐文件增删行、状态、域归属、
  触及该文件的提交主题、测试文件按 AST 读出的**真实用例名**、`inventory_digest`。
- `change-details.tsv`：每个文件从 `git diff -U0 <base>` 的 `+`/`−` 行里抽出的
  **真实符号名**（`def` / `class` / `Signal` / 测试函数），本报告「改动意图」一栏即据此写。
- 采集口径：`tracked = git diff --numstat <base>`（基线 → 工作树），
  `untracked = git ls-files --others --exclude-standard`；`.scratch/` 被 gitignore 天然排除，
  素材派生前缀（`assets/` `dist/` `build/` `frameseq/` `node_modules/`）单独识别——
  本次实际命中 **0** 个派生文件（本版没有把转换/打包产物写进工作树）。

数量基线（脚本实际输出，非人工汇总）：

| 项 | 值 |
|---|---|
| 基线 / 分支 / HEAD | `ee699c7b…` / `release/2026-10-08-candidate` / `7b3fe820…`（与交接记录一致） |
| 基线之间提交数 | 160（其中 first-parent 108） |
| 工作树 dirty 条目 | 140 |
| 基线→工作树有改动的已跟踪文件 | 261 |
| 未跟踪文件（显式枚举） | 37 |
| **产品文件合计**（不含派生） | **298**，`+85859 / −4310` |
| 测试文件 | 153（其中**新增文件 78**，新增文件内含用例 1492 条） |
| 全部测试文件里 AST 可见用例 | 3622 条 |

### 0.2 本报告自身的时点

本版在报告写作期间仍在收口（每个批次都会改字节）。因此：

- §0.1 的数量对应上面写明的采集时点，**不随后续改动自更新**；复核者按同一条命令重跑即可
  得到当时真值，`stats.json` 里的 `head_sha` / `collected_at` / `inventory_digest` 是它的指纹。
- 采集发生在**本报告写作之前**：本报告文件本身与 `docs/INDEX.md` 的那一行登记**不在**
  上面这 298 个文件里。重跑脚本会看到 `docs/` 由 36 → 37（本报告为未跟踪新文件）、
  `docs/INDEX.md` 的增删行数略增——这是预期差异，不是统计错误。
- 生产字节在采集时点之后仍被改动过（§7 列出仍然敞开的工作），因此
  **「机器门全绿」的结论只属于它当时那一份 source digest**，不能顺延到今天的树。

## 一、核心特性

本版是 `release/2026-10-08-candidate` 这条集成分支相对主线的一次整体收口：把
「灵动岛段化 + 岛扩展接口」、一批社区 issue 的功能补全、设置页信息架构重整、
子宠档案与配置写入的并发安全、DSH 联动的回合完成语义、以及三端构建/CI 的最小闭环
合到一条可验收的树上，并按「每项交付必须带修改文件说明 / 性能分析 / 实机运行记录」
的纪律逐批留证。

| # | 能力 | 说明 |
|---|---|---|
| 1 | **灵动岛段化重设计** | 信息槽从「一个槽位」改为**段序列**：主信息段恒在 + `island_metrics` 里任意数量的指标段（CPU/内存/网络/GPU），列表序 = 用户优先级；收缩流水线按「省略名字 → 隐藏名字 → 尾部折 +N chip → 主信息省略 → 保底」逐级退让；宽度白名单是**结构保证**（采样值进不了计划输入键）。见 `PR-REPORT-ISLAND-P1-SEGMENT-REDESIGN-2026-10-07.md`、`PR-REPORT-ISLAND-P2P3-VISUAL-EXTENSION-2026-10-07.md`。 |
| 2 | **岛视觉与状态体系（P2）** | 状态点五态双通道（含错误感叹矢量、完成 4s 瞬态、声纳环只在运行期）、告警色 warn/crit 两级 + 逐指标滞回、单位弱化双盒、软陶笔内缘高光、结构变化 130ms 单侧淡化、展开卡片四分区、停靠细条停采样。 |
| 3 | **第三方岛段公开注册接口（P3）** | 零 Qt 的声明式注册面 + 四道恶意段护栏（非法 id / 重复 id / 缺字段 / 格式化函数抛异常降级）；配套 `ISLAND-SEGMENTS-EXTENSION.md` 公开契约文档。 |
| 4 | **设置页信息架构重整** | 页内分区跳转条 + 组描述（"按区直找"）、域页内标签、搜索增强（折叠组标题入索引 + 口语别名）、已修改标记 + 默认值小字 + 单项重置、页尾留白顶对齐、文案"黑话"lint 机制化。 |
| 5 | **子宠档案与配置写入并发安全** | 新档案存储 `pet/pet_profiles.py`（语义单测本批不接消费者，接线由 G1b 契约测试守护）、目录级跨进程短时写锁 `pet/config_write_lock.py`、`SlotRoutedConfig` 路由（子宠页读写不再落主配置）、`save_geometry` 带代次令牌（旧代次写入被拒）。 |
| 6 | **设置窗"关得掉"契约** | 档案代次被外部推进后，保存必须被**正确分类拒绝**并给出两个明确出口（继续编辑 / 放弃未保存的改动并关闭）；Esc 等同继续编辑；放弃不写盘、不丢已写入的全局部分。 |
| 7 | **DSH 联动：回合完成语义按 live 身份收口** | 判据从「呈现管线里上一个状态」换成**桥接真实写出的记录身份** `(session_id, step, epoch)`，收口四条来向（中途挂载 / idle 基线先到 / 收敛器已停在 SUCCESS / 关开联动残留终态）；历史回填不重播，同一回合只提醒一次。对应社区 issue #234 的主诉。 |
| 8 | **免打扰（#208）+ 语音静音闸** | 四档时长（15/30/60/120）+ 暂存队列 + 全屏联动；只压普通提醒（审批/提问/状态类一律穿透）；免打扰期间报时/节日语音静音。 |
| 9 | **社区 issue 的功能补全** | #209 查看天气 + 多城市（国内源直连、国外源跟随系统代理）、#210 回收内存、#172 灵动岛网络槽 +「网络信息」弹窗、#219 静止放手下落开关、#220 恢复默认设置、#221 动画菜单点完收起 + 随机动作前缀分组、#228 B 站标题清洗 + foobar2000 窗口标题源、#216 余额副标题参与气泡高度预算、#191 现代对话窗末条消息下方空白、#211 测试基建修复（产品代码 0 改动）。 |
| 10 | **旧版右键菜单全量退役** | 删除 `context_menus/legacy.py`、`menu_styles/legacy.py`、`menu_templates/{legacy,modern}.json` 与整条模板分发机制；配置键 `context_menu_template` 静默迁移后丢弃；三层防复活守卫进 `test_architecture.py`。 |
| 11 | **执行环境（harness）目标语义** | 自启目标 `auto` 改为只拉起 dsh 服务，新增 `service` 目标；`--slot N` 只选择既有身份、不新建第二实例。 |
| 12 | **GPU 读数接入** | `pet/gpu_monitor.py`（Windows PDH）→ 共享采样线程 → 胶囊读数 → 展开卡片详情；非 Windows 走诚实降级而不是零占位。 |
| 13 | **三端构建/CI 最小闭环** | 四条工作流加 `workflow_dispatch` + `source_ref` + resolved SHA/toolchain 记录、素材供给统一入口 `scripts/prepare_frameseq_bundle.py`（先验证 → 缺才转 → 转完再验）+ 缓存 key、Mac/Linux 构建脚本补素材硬门、Windows 两个安装包 AppId 分开。 |
| 14 | **单宠也能"关闭这只"** | overlay 托盘逐只菜单从「≥2 只才挂」改为「≥1 只就挂」，关最后一只不退应用；配合逐只关闭加确认框。 |

**红线 / 不变量**（本版明令不允许被破坏的既有语义）：

1. **关闭宠物 ≠ 退出应用**：关掉任意一只（含最后一只）后进程、托盘、壳级服务仍在；
   顶层「退出」才等于 `app.quit`。应用退出时活跃成员关系保留。
2. **档案与身份**：档案只在 `config-slot-N.json`，全局在 `config.json`，活跃成员在
   `overlay-active-pets.json`；profile 写入/重置共用目录锁与代次；坏档案**不覆盖、不清源**。
3. **岛宽度是结构保证**：采样读数不得进入计划输入键，读数变化不得引起 `setFixedSize`。
4. **提醒只由唯一呈现者负责**：承载者交接时不重发、不重复出声，有界队列满时本地丢弃并有日志。
5. **免打扰只压普通提醒**：审批/提问/交互/状态类事件穿透（不得塞进 `bubble_blocked`）。
6. **历史回填不播**：接上桥接之后真的发生了一回合收尾才提醒。
7. **不猜**：网页标题清洗只删片段不改写、结果为空即整体退回原参；foobar 格式串匹配不上就退回不猜。
8. **执行层进程边界**：不越出本产品自己的 pid 做进程操作；卸载清理只删带本产品 owner 标记的目录。

**不计入本版新增的既有成果**（避免误读）：帧序列 Q70 编码档切换、Qt 侧的系统性根治、
单宠内存瘦身等已在基线之前完成并另有报告（`PR-REPORT-FRAMESEQ-V3-PIPELINE-2026-09-29.md`、
`PR-REPORT-MEMORY-DIET-SINGLE-PET-2026-09-24.md` 等）。这些文件在**基线之后没有任何改动**，
因此不出现在 §2 的表里，也不作为本版新增能力计功。

## 二、修改文件说明

逐文件写「改了什么 + 为什么」；增删行数取自
`git diff --numstat ee699c7b693297cb324a01c72989902302dfd768`（基线 → 工作树）。
**状态列**：`已提交` = 该文件相对基线是分支上的提交产物；`未提交` = 采集时点仍在工作树
（含未跟踪新文件）。测试文件的用例名由脚本按 AST 从文件里读出，不用「增加测试」这类概述
代替。

约定：表里 `+N/−M` 是**基线→工作树**的累计 diff，不是某一个批次的增量；每行末尾的括号给出
采集时点是否仍未提交。**完整逐文件清单**（含未入库的 37 个文件）见 §2.6 与
`inventory.tsv`；本节按域分表，不遗漏任何文件。

### 2.0 域小计（脚本输出）

| 域 | 文件数 | 其中新增 | 采集时点仍 dirty | 增 / 删 |
|---|---|---|---|---|
| `pet/` 实现 | 91 | 5 | — | +25313 / −2620 |
| `tests/` | 153 | 78 | — | +51217 / −1605 |
| `docs/` | 36 | 25 | — | +8166 / −31 |
| `scripts/` | 7 | 1 | — | +675 / −14 |
| `.github/workflows/` | 4 | 0 | 4 | +300 / −5 |
| `packaging/` | 3 | 0 | 3 | +81 / −3 |
| `integrations/` | 1 | 0 | — | +18 / −12 |
| 仓库根（`AGENTS.md` `CONTEXT.md` `README.md`） | 3 | 0 | 1 | +89 / −20 |
| **合计** | **298** | **109** | — | **+85859 / −4310** |

### 2.1 `pet/` 实现（91 个文件）

#### A. 应用与窗口生命周期

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `pet/app.py` | +911/−110 | 新增 `_EmptyPetHost`（无可见宠时提醒仍有承载面，不再静默丢）；`_mark_slot0_profile_unusable` 按当前拓扑分流恢复指引（overlay 免重启 / legacy 需重启），旧文案两边共用一句是错的（实机发现）；活跃集合写入失败由 `_notify_active_set_write_failed` 可见上报；`_spawn_settings_process` 独立设置进程；`apply_settings_reset` 前先 `reload_runtime_config`（否则旧 Config 整表覆盖回旧值）；天气/网络信息入口与弹窗单例收口；设置窗可释放闸门 `_settings_window_releasable`/`_release_settings_windows`/`request_app_quit`（退出流程不得被"继续编辑"卡死）；单宠托盘 `_build_empty_pet_tray`；岛身份真值 `_island_interactive`/`_chat_identity_config`。（已提交） |
| `pet/overlay_shell.py` | +1438/−498 | 逐 sprite 呈现器 `_SpriteServicePresenter`：气泡与提醒按**槽**路由（此前只有主窗一个呈现面）；提醒交接完整链（`_present_alert_on` / `_retire_alert` / `_note_alert_presented` / `_alert_remaining_ms` / `_settle_alert_bubble` / `_resume_alert_copy`），承载者迁移不重发不重出声；托盘逐只菜单闸门从 `if self._spawned:`（≥2 只）改为 `if entries:`（≥1 只）并加 tooltip（单宠此前没有任何"关闭这只"入口）；坏 slot0 恢复入口 `_ensure_recovery_entry` 与其"托盘可用时不建恢复窗"的既有门；`_persist_active_slots` 只在显式用户操作时写；子宠几何/档案 `_save_child_geometry`/`_apply_child_profile`；`presentation_valid`/`presentation_available` 供上层判断呈现面是否可用。（已提交） |
| `pet/window.py` | +37/−12 | 旧版菜单退役后清理死槽；新增 `stable_body_local_rect` / `profile_character` / `set_profile_identity`（窗口侧供给角色身体框与当前档案身份）。（已提交） |
| `pet/window_placement.py` | +12/−6 | `save_position` 统一走 `cfg.save_geometry(geometry, token)`：位置写入带上**档案代次令牌**，代次过期即拒写（此前裸 `cfg.set(...).save()` 会把旧代次几何写回新档案）；无该方法的宿主保持旧路径。（未提交） |
| `pet/window_alerts.py` | +305/−58 | 提醒承载与队列：`alert_bubble` 承接面判定、`_show_item_on`/`_show_on_target`/`_remember_sticky`/`_reshow_on_carrier`（隐藏/迁移后按原 ID 与剩余 TTL 交接）、`_admit_to_queue`/`_enforce_queue_bound`/`_note_overflow`（有界队列，满时本地丢弃并记日志）、`quiet_blocked`/`defer_quiet`/`report_quiet_summary`（免打扰分流），`_worst_priority` 保高优先级。（已提交） |
| `pet/multi_window_shared.py` | +90/−7 | 交付确认制：新增 `has_presentation_target`（有承载面才交付）与 `_on_quiet_ended`（免打扰结束时排空暂存），补隐藏宿主与全屏往返缺口。（已提交） |
| `pet/runtime_cleanup.py` | +222/−13 | 运行时目录清理加**所有权标记**：`mark_owned_runtime_dir`/`mark_frozen_runtime_dir` 写 owner marker，`_read_owner_marker`/`_owned_identity`/`_marker_pid_alive`/`_tree_has_link_like`/`_is_link_like`/`_lstat` 在删除前判定「确属本产品实例」——通用 `_MEI` 清理越界是审查 A01。（未提交） |
| `pet/uninstall_cleanup.py` | +91/−1 | 统一入口 `main()`：`_describe_step`/`_format_results`/`_write_result_record` 逐步诊断输出 + 配置目录留痕 + 退出码语义，三个冻结入口（`pet/__main__.py`、`packaging/pet_entry*.py`）共用一处实现，不再各自复刻（审查 A12）。（未提交） |
| `pet/__main__.py` | +6/−7 | `--uninstall-cleanup` 改调 `uninstall_cleanup.main()`（不再在入口侧复刻退出码算术）；设置进程的 `instance_id` 不再 `or None` 兜底，`slot-0` 身份如实下发。（未提交） |
| `pet/overlay_window.py` | +28/−9 | 非 Windows 穿透补齐显示契约：首次显示同步收敛 + 显示后强制对账；macOS 关闭窗口系统阴影。（已提交） |
| `pet/overlay_instance_gate.py` | +25/−31 | 实例门与拓扑解耦：`acquire_overlay_instance_gate` 在 legacy 拓扑下同样持门（此前"legacy 可多开"是捕获模式死开关的残留）；删掉 `is_required` 这条会随拓扑漂移的判据。（已提交） |

#### B. 联动 / DSH

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `pet/agent_link.py` | +1061/−198 | ① 摄入账本 `EventIdentityLedger`（`note`/`clear`/`_purge`/`_retire_on_signal_loss`/`_is_duplicate_delivery`）按**信号发出身份**去重，替代按内容猜；`read_new_lines_with_cursors` 让摄入带上读取游标；② `TurnCompletionTracker` 接入：`DshMonitor.dsh_turn_completed` 新信号 + `_on_parsed_record(data, cursor)` 基类钩子 + manager 侧 `_dsh_turn_ids` 有界记忆（`_DSH_TURN_ID_MEMORY = 64`）与 `_on_dsh_turn_completed`，与既有 `busy→success` 边沿分工（边沿先排定，身份通道收口边沿看不到的四条来向）；③ 阻塞型交互按**身份**收口：`_interaction_key`/`_session_matches`/`_resolve_matching_interaction`/`_log_ambiguous_resolution` 多候选拒歧义，删除第三套 `_close_interaction_by_id`；④ pending 有上限 `_admit_pending_interaction`/`_prune_pending_interactions`/`_note_pending_overflow` 与补投 `redeliver_pending_interactions`；⑤ 六条路径按 Agent 路由专属文案。（已提交） |
| `pet/dsh_state.py` | +61/−2 | 新增纯逻辑 `TurnCompletionTracker`（无 Qt/线程/时钟）：`observe(record, cursor) -> identity | None` 用 live 记录算 `(session_id, step, epoch)` 身份，`reset()` 在监视器启停时清空——「已停在 SUCCESS 的收尾」不能由状态转换判定，必须由身份判定。（已提交） |
| `pet/agent_event_normalizer.py` | +26/−15 | 删除零生产者零消费者的 `ControlResultEvent`；收尾帧归一化不再被前缀分支吃掉；`_resolved_ids` 让 resolved 事件按 ID 集合收敛。（已提交） |
| `pet/agent_event_protocol.py` | +9/−7 | 清理减法后与实现矛盾的陈旧注释，并把 `callId` 读取回退到信封字段（无行为改动 + 兼容别名）。（已提交） |

#### C. 配置、档案与设置进程路由

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `pet/config.py` | +753/−168 | 新增 16 个键与对应归一化：`island_metrics`（有序列表，未知 id 丢弃、去重保序）、`island_network_enabled` 降级为**单向迁移源**（判真 → 追加 network 成员再自置 False）、`network_probe_interval_seconds`（夹到 [0.5, 60]）、`network_info_menu_enabled`、`weather_enabled`/`weather_city`/`weather_city_list`/`weather_city_codes`（城市名归一化是加载/重载下的不动点，见 `test_config_schema.py`）、`quiet_minutes_default`/`quiet_also_on_fullscreen`、`mem_skip_foreground`/`mem_min_size_mb`、`anim_menu_stay_open`、`drop_gravity`、`foobar_lyrics_enabled`/`foobar_title_format`、`harness_autostart` 目标扩展；删除 `context_menu_template`（`_migrate_menu_template_config` 读旧值 → 记一次 info → 丢弃）；新增 `chat_secret_carryover`（重置保留自定义服务商密钥）、`normalize_pet_profile_snapshot`/`_migrate_pet_profile_values`（per-pet 键搬迁）、`has_local_changes`/`discard_unsaved_drafts`（草稿与"脏"判定）、`_merge_config_changes`/`_keep_config_deletions`（`save` 递归合并）、`_clean_island_coordinate`（脏坐标不再打断构造，修 `OverflowError`/`ValueError`）、`_write_save_payload`/目录锁接入。（已提交） |
| `pet/config_domains.py` | +0/−121 | **整文件删除**：`_DomainFacade` 与 `ChatConfig`/`AgentLinkConfig`/`ProactiveConfig`/`CollisionConfig`/`MenuConfig` 这套域门面在减法后已无消费者，被 `Config` 的统一键表取代（`test_architecture.py` 守卫它不再回来）。（已提交） |
| `pet/config_write_lock.py` | +367/−0 | **新文件**：目录级跨进程短时写锁（`config.json` / `config-slot-N.json` 同目录）。存在的理由：设置进程与主进程写同一目录，此前靠"先读后写"必然丢更新；写锁把"读—改—写"整段圈住，且是**短时**的（不占用用户可见操作时长）。（未提交） |
| `pet/pet_profiles.py` | +1318/−0 | **新文件**：子宠档案存储（语义单测 68 条；`PER_PET_KEYS` 是 per-pet 键的唯一清单来源，`_SLOT_PROFILE_RE` 供 `agent_link` 判定槽档案路径）。本批**不接消费者**——接线由 G1b 契约测试（`test_settings_profile_integration.py`）守护，避免一次改动同时改存储与全部调用点。（未提交） |
| `pet/settings_slot_config.py` | +727/−0 | **新文件**（本轮功能主体）：`SlotRoutedConfig` —— 子宠设置页读写的**路由中枢**。每张表单持独立 `Config`（同 disk、同锁、同 reset 侧车），避免共享 `_main` 全局草稿互相污染；`new_form_view` 起**新基线**、`_pin_edit_generation` 在"新表单开始编辑"这一拍重取代次（sticky-pin 会让重开表单继续拿旧代次）、`absorb_persisted_globals` 只在 clean 时 reload（否则吸收会重引 nested 异叶丢更新）、`discard_unsaved_drafts` 真作废、`save_failure_of` 把失败按类别分类（`SaveFailure`）。（未提交） |
| `pet/settings_close_flow.py` | +379/−0 | **新文件**：设置窗关闭流程与"保存失败"两个出口的实现——`继续编辑`（保留草稿、不写盘）与`放弃未保存的改动并关闭`（弃稿、不覆盖档案），以及退出前关窗闸门（被"继续编辑"拒绝后不得清引用/销毁父窗）。此前同一现场表现为"保存失败 + X 也关不掉 + 只能杀进程"。（未提交） |
| `pet/overlay_spawn_state.py` | +70/−326 | 大幅瘦身并收紧：`normalize_slots`/`active_pets_path`/`scan_slot_configs`/`allocate_slot` 改为**不改档、不隐式提升**（`allocate_slot` 在历史满时复用最小退休身份，全满才报错）；`read_slot_config`/`write_slot_setting`/`read_slot_collision_enabled`/`write_slot_geometry`/`read_slot_geometry` 只做读/受限写；删除 `SpawnStateError` 与内部 `_finite` 等旧判据。（已提交） |
| `pet/overlay_settings_command.py` | +382/−41 | 拓扑判定快照化：`_topology_env_verdict`/`_explicit_env_verdict`/`_parent_env_verdict`/`env_forces_legacy`/`runtime_topology_env_value` 明确优先级（显式 env > 父进程 env > 盘上 `stream_capture_mode`），`topology_config_path` 复用主配置位置；命令租约 `claim_command`/`finish_command` 增加回滚与坏编码容错（坏一行不阻断下一条写入）；`reset_topology_snapshot` 供重置后重读。（已提交） |

Let me continue with D (island), E (menus), F (settings), G (features).

I'll append.

#### D. 灵动岛与采样

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `pet/dynamic_island.py` | +3039/−139 | 岛的能力主入口：段计划接入（`_info_text` 之外新增 `_seg_status_dot`/计划重算）、状态点五态与 `_arm_dot_done`/`_stop_dot_done_timer`、错误感叹矢量 `_status_error_glyph_path`、声纳环 `_sync_sonar_ring`/`_on_sonar_tick`/`_sonar_eligible`（只画不重建内容缓存、不碰宽度）、设备槽 `_make_sys_monitor`/`_sync_sys_slot`/`_unsubscribe_sys`/`_pause_sys_slot`/`_tick_sys`/`_tick_device_slot`、网络槽 `_make_net_monitor`/`_sync_network_slot`/`_tick_network`、GPU 槽 `_gpu_metric_enabled`/`_tick_gpu_slot`/`_update_gpu_alert`、第三方段 `_make_extension_sampler`/`_refresh_extension_declarations`/`_sync_extension_slot`、告警色 `_update_alert_severity`、卡片四分区 `_CardMetricRow`/`_CardSeparator`/`_CardStatusDot`、停靠细条 `_strip_hidden`、脏坐标容错。核心不变量：**采样读数不进计划输入键**，读数变化不得改写窗口几何。（已提交） |
| `pet/island_layout.py` | +547/−0 | **新文件**：行的几何与收缩计划。`_InfoSeg`/`_SegPlacement`（值盒右对齐 + 单位盒贴值盒）、`elide_to_width`（按前缀二分，不是逐字符试）、`_unit_box_width`（跟随本行最宽单位）、`ShrinkPlan`/`plan_info_row`/`apply_shrink`（"省略名字 → 隐藏名字 → 尾部折 +N chip → 主信息省略 → 保底"逐级退让，主信息永不折）、`chip_segment`/`_folded_alert`（chip 携带最高告警级）、`anchored_x`（分组伸长锚点只作用于自由胶囊）。（已提交） |
| `pet/island_segments.py` | +730/−0 | **新文件**：段契约与注册表。`SegmentSnapshot`（冻结、单行字段）、`SegmentRegistry`（保注册序、拒重复 id 且首次胜出）、`measure_segment_width` + `font_metrics_key` 宽度缓存、`format_field_box`/`split_value_unit`/`render_compact`（值/单位分离但仍发合并串）、`alert_thresholds`/`seed_thresholds`/`drop_thresholds`/`alert_severity`/`highest_severity`（逐指标滞回）、第三方面 `register_segment`/`unregister_segment`/`segment_declarations`/`judge_oversize`/`is_oversize`、恶意声明护栏 `_clean_segment_id`/`_clean_thresholds`/`_clean_value_text`/`_clean_note`（坏值降级到 error 态而不是抛）。（已提交） |
| `pet/island_extension_host.py` | +1050/−0 | **新文件**：第三方岛组件的**声明源 + 有界后台采样**。声明清单解析与去重、每组件独立子进程/线程边界、订阅即采样、退订即停、stop→start 不重叠（`_new_generation`/`_retire_generation`）、坏组件隔离（一个组件抛异常不影响其他段）。对应审查 A07/A08/O1 的修复面。（未提交） |
| `pet/sys_monitor.py` | +627/−0 | **新文件**：设备槽共享采样器。`read_cpu_percent`/`read_mem_percent` + `CpuMeter`（首次差分采样不作数，避免"第一拍假 0"）、`SysMonitor` 单例式共享（`subscribe`/`unsubscribe`/`subscriber_count`）、**0 订阅即停**、隐藏即休眠、`clamp_interval`、GPU 侧 `subscribe_gpu`/`unsubscribe_gpu`/`gpu_subscriber_count`/`_open_gpu_reader`/`_read_gpu`/`_bounded_release_error`（释放失败不得冒泡成崩溃）。（已提交） |
| `pet/gpu_monitor.py` | +1041/−0 | **新文件**：GPU 占用的真实读数源（Windows PDH 计数器 + 逐项容错）。非 Windows / 无计数器时走诚实降级（返回错误样本 → 胶囊显示 `--` + 卡片原因行），不伪装成"零占用"。（未提交） |
| `pet/net_monitor.py` | +514/−0 | **新文件**：网络槽采样核心。`NetRateMeter`（首样本只作基线不算速率、计数器回绕/重置按 0 处理而不是尖峰、EMA 平滑、缺计数器不抛）、`encode_dns_name`/`build_dns_query`/`probe_udp_latency`/`UdpLatencyProbe`（延迟探测打**境内 IP 字面量**的合法 DNS A 查询，复用 socket 且每条路都关）、`format_rate`/`format_latency`/`format_network_slot`（**定宽文案**，不定宽会每秒左右抖）、`NetMonitor` 代次隔离（`_new_generation`/`_retire_generation`，旧代次样本不得落屏）。（已提交） |
| `pet/network_info.py` | +387/−0 | **新文件**：「网络信息」数据层。`decode_json_body`（国内源是 GBK，解码顺序 UTF-8 → gb18030）、`parse_pconline`/`parse_ip_api`（两源字段映射与失败状态）、`is_china_geo`（认不出的省名/英文地名判"判定不了"，港澳台判否——**不硬猜**）、可达性用 HEAD 且 HTTP 错误码算可达、`collect` 国内源优先且不触碰兜底、有界读取响应体。（已提交） |
| `pet/network_info_dialog.py` | +267/−0 | **新文件**：「网络信息」弹窗，`showEvent` 时取一次（不轮询）、取数期间禁用刷新、失败显示原因而不是空白、弹窗在结果到达前被关掉不炸（`_apply_snapshot` 对已析构 dialog 是 no-op）。（已提交） |

#### E. 菜单

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `pet/context_menu.py` | +7/−81 | 旧版菜单全量退役后，只剩 `populate_context_menu` 一条现代建造路径；删除 `normalize_template_id`/`load_menu_template`（整条模板分发机制）。（已提交） |
| `pet/context_menus/legacy.py` | +0/−95 | **整文件删除**：旧版菜单建造器退役，`test_architecture.py` 守卫文件不存在。（已提交） |
| `pet/context_menus/menu_styles/legacy.py` | +0/−13 | **整文件删除**：旧版样式退役。（已提交） |
| `pet/menu_templates/legacy.json` | +0/−15 | **删除**：旧版模板资源退役。 |
| `pet/menu_templates/modern.json` | +0/−15 | **删除**：作为分发源的现代模板退役（只剩内置注册表）。 |
| `pet/menu_templates/modern-default-v1.json` | +5/−0 | 内置默认编排补两条新入口（网络信息 / 天气城市的落位）。（已提交） |
| `pet/context_menus/menu_styles/__init__.py` | +1/−2 | 导出面随 legacy 退役收窄。（已提交） |
| `pet/context_menus/menu_styles/common.py` | +15/−15 | `inherit_menu_style` 默认值原指向已删的旧版样式（父菜单属性没设上就**静默掉样式**），改为恒落现代分支；这是退役最容易漏的一处。（已提交） |
| `pet/context_menus/__init__.py` | +2/−3 | 导出面收窄（legacy 建造器不再导出）。（已提交） |
| `pet/context_menus/modern.py` | +1/−2 | `build_modern_menu` 去掉模板分发参数，只按注册表建树。（已提交） |
| `pet/context_menus/registry.py` | +81/−11 | 注册表补新条目与门：`_memory_trim_available`（回收内存的平台门）、`_network_info_enabled`（网络信息的 **enabled 门**——保留位置 + 置灰 + 原因，对齐 `CONTEXT.md` 的 Runtime Disabled，而不是让入口消失）；legacy 音乐子菜单补上引导文案所指的「歌词对齐」入口（B8）。（已提交） |
| `pet/context_menus/shared.py` | +649/−32 | 共享建造器：`run_after_menu_closed`/`add_tray_action`（**菜单先关、回调延到菜单跟踪会话结束**——macOS 托盘菜单是原生 NSMenu，Qt 侧 `isVisible()` 恒 False，裸 `addAction` 会表现为"第一次点了没反应"）；动画缩略图缓存 `animation_icon_cache_key`/`_entry`/`_hit`/`_drop_library` + `_AnimationIconFailure`（worker 失败可见收口）；`group_animation_entries`/`_dash_family_key`/`_prefix_family_key`（#221 随机动作前缀分组，纯数据驱动、家族子菜单**构建期**建好否则递归样式装不上）；`animation_menu_stay_open` + `closeOnTrigger` 接入既有收口链路；免打扰菜单 `add_quiet_mode_menu`/`end_quiet_mode`；`confirm_destructive_action`（退出这只加确认）；`add_memory_trim`/`_MemoryTrimBridge`；`add_network_info`。（已提交） |
| `pet/context_menus/icons.py` | +10/−0 | 补天气与网络信息的语义矢量图标。（已提交） |
| `pet/sprite_menu_facade.py` | +176/−141 | 菜单门面向逐 sprite 呈现面迁移：`_persist_sprite_setting`/`show_bubble`/`_service_host`（气泡与设置按槽落到正确宿主）、`on_show_weather`/`on_network_info` 新入口、`_icon_key` 缓存键带槽身份；`hide()` 的注释随闸门改动同步（纯注释）。（已提交） |
| `pet/weather_menu.py` | +517/−0 | **新文件**：天气菜单与城市子菜单。`weather_menu_enabled`/`_mark_disabled`（Runtime Disabled 门）、`add_show_weather`/`add_weather_cities`、增删/切换城市流程 `apply_added_city`/`switch_city`/`remove_city_from_config`、带显式代次的搜索（`_SearchBridge`/`_run_in_thread`/`set_search_results`，迟到的旧搜索结果不得覆盖新一次输入）、`WeatherCityDialog`。（已提交） |

#### F. 设置页

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `pet/modern_settings_dialog.py` | +258/−163 | 接入关闭流程：`reject`/`closeEvent` 改为走 `settings_close_flow`（保存失败时给两个出口，不再出现"窗口关不掉"）；`_save_before_close`/`_close_after_external_write`（保存成功后按外部写入结果决定是否关窗）；`_hidden_prerequisite_note`（被前置条件藏起来的行要有说明，不能静静消失）。（已提交） |
| `pet/settings_page_guide.py` | +495/−0 | **新文件**：设置页"按区直找"。`section_title`/`blocks_in_layout_order`/`sections_in_layout_order`/`rows_in_layout_order` 按布局顺序遍历（不是按构造顺序），`_FlowLayout`/`_SettingsAnchorBar` 页内跳转条，`jump_to`/`_settle`/`_reveal`/`_activate_layouts`（跳转一次到位），`_PastEndPadding` 让**最后一组也能一次点击顶对齐**。（已提交） |
| `pet/settings_search.py` | +188/−0 | **新文件**：搜索增强。`row_key`/`_row_text`/`find_matches` 之外，`fold_group_titles`/`_own_fold_title` 把折叠组标题也纳入索引（搜到的组要展开才看得到），`_alias_targets` 是口语别名表（"网速"能找到网络信息）。（已提交） |
| `pet/settings_default_marks.py` | +260/−0 | **新文件**：已修改标记 + 默认值小字 + 单项重置。`_row_default_value`/`_default_value_text`/`_values_equal`（默认值比较不走 `==` 的字符串化歧义）、`install`/`refresh`/`_reset_row`（单项重置回到出厂值而不是"清空"）。（已提交） |
| `pet/settings_reset_defaults.py` | +355/−0 | **新文件**：恢复默认（#220）。`reset_scope_is_slot`/`resolve_reset_scope`（这只 / 全局两种作用域显式区分）、`reset_config_for`、`build_reset_confirm_box`/`confirm_reset`/`on_reset_clicked`、`sync_system_autostart`、`reload_runtime_config`/`_request_runtime_alignment`（重置后把运行态对齐到默认值，B1 的根因是旧 Config 整表覆盖回旧值）。（已提交） |
| `pet/settings_slot_config.py` | 见 §2.1-C | （上表已列，避免重复） |
| `pet/settings_network.py` | +362/−0 | **新文件**：设置页「网络信息 / 灵动岛指标」控件与保存。`create_network_controls`/`metric_rows`/`metric_order`/`_checked_metrics`（列表序 = 优先级，勾选顺序即写入顺序）、`_extension_rows`（第三方段也进同一张表）、`_metric_attr` 把 id 映射到控件、`_traffic_hint`/`_interval_hint`/`_sync_interval_hint`（有流量的能力必须写明代价）、`build_island_network_rows`/`build_menu_rows`、`_install_visibility`（行显隐集中一处）、`_fit_spin_to_content`。（已提交） |
| `pet/settings_quiet.py` | +97/−0 | **新文件**：免打扰设置控件（`create_quiet_controls`/`build_quiet_rows`/`save_quiet_settings`），档位文案取自 `QUIET_MINUTE_CHOICES` 这唯一来源。（已提交） |
| `pet/settings_weather.py` | +125/−0 | **新文件**：天气设置标签（行归属、默认值口径、城市列表归一化与保存回写）。（已提交） |
| `pet/settings_pet_controls.py` | +122/−33 | 子宠页的**进程级设置死开关收口**：免打扰/天气/网络/foobar/下落这类"影响所有宠"的键不再在子宠页做成可点但无效的开关（改为全局域陈述口径）；新增 `harness_target_hint`（自启目标 auto/service 的影响面提示，纯选择移到这里以免抬行数预算）。（已提交） |
| `pet/settings_widgets.py` | +87/−2 | 供给页内分区跳转条与组描述所需的控件：`_section_description_label`/`set_description`、`set_default_state`（默认值小字）、`suggestedWidth`、`currentKeyChanged`（跳转条需要知道当前锚点）。（已提交） |
| `pet/settings_music.py` | +93/−2 | foobar2000 源的行（Windows-only，非 Windows 或控件缺失时整组不出现）、`advanced_group_title`、`save_source_settings`（两个开关 + 格式串一次写）。（已提交） |
| `pet/settings_interaction.py` | +7/−2 | 天气设置行的域归属落到「互动」，与菜单入口一致。（已提交） |
| `pet/settings_theme_qss.py` | +35/−5 | 视觉层级 QSS（组标题/描述/默认值小字的层级差）+ 14 行标题措辞重写。（已提交） |
| `pet/festival_settings.py` | +2/−1 | 免打扰期间节日语音静音的设置项接线。（已提交） |
| `pet/voice_chime_settings.py` | +1/−1 | 同上，报时语音设置项接线。（已提交） |

#### G. 功能模块（能力补全与收口）

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `pet/weather.py` | +724/−0 | **新文件**：天气取数纯逻辑。城市名归一化链 `normalize_city_name`/`strip_city_suffix`/`city_name_variants`/`base_city_name`/`same_city`（`鹿城区` 原名搜不到要能归一化重搜，且归一化必须幂等）、`parse_search_payload`/`pick_candidate`/`parse_cn_reading`/`parse_open_meteo_reading`、`read_bounded`（响应体有界读取）、`_default_http(use_proxy=...)`（**逐源出口策略**：国内源显式直连、国外源跟随系统代理）、失败文案点名两个源各自原因。（已提交） |
| `pet/weather_service.py` | +189/−0 | **新文件**：后台取数 + 冒泡落地（`WeatherService`/`_run_in_thread`/`_WeatherBridge`/`_settle`），失败口径与忙门、宿主销毁后迟到的结果不落屏。（已提交） |
| `pet/music_title.py` | +606/−0 | **新文件**：标题 → 取词查询词。`clean_web_title` 只删片段不改写（单测断言输出是输入的子序列），`A - B` 顺序判不出来就把整条同时当歌名与歌手（**押错的代价是贴错歌词**），结果为空/不足 2 字整体退回原参；`parse_foobar_title` 用**分段扫描**解析用户可配置的 titleformat 串（`_tokenize_format`/`_literal_pattern`/`_find_literal`/`_assign_fields`），正则回溯爆炸已被 `test_pathological_format_strings_fail_fast` 钉住。（已提交） |
| `pet/foobar_playing.py` | +166/−0 | **新文件**：foobar2000 窗口标题源（`foobar_pids` 带 TTL 缓存与 pid 短路、`_window_titles_for_pids`/`read_track` 取最长窗口标题、`reset_pid_cache`）。（已提交） |
| `pet/now_playing.py` | +76/−4 | 接入 foobar 源：`is_foobar_source` 是**唯一判据**（别处不准复制字符串比较），SMTC 在播时一次都不问 foobar，且 foobar 源不覆盖 SMTC 跟踪位。（已提交） |
| `pet/music_lyric_controller.py` | +258/−27 | 取词链改动：`_lyric_query`（浏览器会话才清洗）、`_foobar_lyrics_enabled`/`_foobar_title_format`、暂停计时 `_note_paused`/`_close_pause_segment`/`_paused_seconds`（暂停不推进歌词时钟）、`_request_lyrics` 绑定对齐上下文（迟到的旧请求不得改新歌的上屏）。（已提交） |
| `pet/music_lyric.py` | +11/−1 | 网易云源 `ar` 字段复活 + 失败改为冷却重试（不是永久拉黑）。（已提交） |
| `pet/memory_trim.py` | +561/−0 | **新文件**：回收内存（#210），**零 Qt 纯逻辑**。过滤真值表 `decide_target`（自己 / pid 0·4 / 自己的后代 / 前台 / 系统关键名单 / 工作集阈值 → skip 或 trim）、`_is_critical_name`、`Win32ProcessApi` 只用 `PROCESS_QUERY_LIMITED_INFORMATION|PROCESS_SET_QUOTA` 且句柄 `restype=c_void_p`、`CloseHandle` 只在唯一 `finally`、`own_child_pids`（跳过自己的子进程——本仓库解码 ffmpeg 读者就是子进程，抖它会当场掉帧）、`trim_working_sets` 后台 worker + `TrimReport.text` 汇报口径。（已提交） |
| `pet/quiet_mode.py` | +339/−0 | **新文件**：免打扰状态机（注入时钟，可无 sleep 测试）+ `QUIET_MINUTE_CHOICES` 档位唯一来源 + 全屏等效（复用既有全屏探针，不另起第二套检测）。（已提交） |
| `pet/proactive.py` | +8/−0 | 免打扰期间主动提醒走暂存而不是直发。（已提交） |
| `pet/speech_bubble.py` | +152/−5 | #216：副标题参与高度预算。`_subtitle_width_floor`/`_sync_subtitle_max_width`（上限从写死 248px 改为 `max(正文宽, 248×缩放)`，定高与绘制两端同口径）、呼吸泡 `_breath_subtitle_inset`/`_breath_subtitle_reserve`/`_breath_size_for_subtitle`/`_breath_label_height`（正文盒让出副标题预留，放不下时等比放大画布并给左右安全内边距）。（已提交） |
| `pet/pet_sprite.py` | +36/−1 | #219 静止放手下落开关：低速松手零初速受重力落地（`drop_gravity`）。（已提交） |
| `pet/golden_spin.py` | +10/−1 | 黄金回旋换目标：控制器全壳共享、目标独占（R06）。（已提交） |
| `pet/sprite_feeding.py` | +28/−22 | 喂食链：`eat_paths`/`_play_eating_animation`/`_show_feedback` 统一反馈出口。（已提交） |
| `pet/file_eater.py` | +153/−37 | 拖入扫描加**预算**：`_ScanBudget`（文件数 / 墙钟双预算，每项都查时钟）、`_measure_path`/`_measure_paths`/`account_dir`/`account` 逐层记账、`feeding_bubble_text` 如实说明被截断，而不是长目录把 UI 顶住。（已提交） |
| `pet/file_interpret.py` | +36/−7 | 同上，`collect_interpretable` 带文件数/时间双预算，超预算改为提示而不是"读不出来"。（已提交） |
| `pet/todo_panel.py` | +33/−7 | 待办落盘失败不再被当成保存成功：`_persist_or_warn`/`_save_items` 落盘成功才提交内存态，失败不关编辑器并给出含路径的提示。（已提交） |
| `pet/todo_reminder.py` | +56/−13 | daily 跨午夜的提前提醒不再迟发：`set_items`/`store_path` 与"下一条"计算按真实时刻判，出了当天窗口不再静默盖戳。（已提交） |
| `pet/festival_service.py` | +6/−0 | 免打扰期间的节日提醒走交付确认制（有承载面才交付）。（已提交） |
| `pet/voice_chime_service.py` | +951/−54 | 语音通道家族收口：占用判据收敛为 `_channel_idle()`（无合成在飞 ∧ `_player_engaged`）**一条不变量**（删掉只看 `playbackState` 的旧 `_player_busy`——`setSource` 后立刻 `play()` 有约 300ms 是 `StoppedState` + `LoadingMedia`，会把刚接管的通道误判成空闲）；出队口按**完成路径**收口 `_drain_pending_speech`（免打扰丢弃/合成失败/已停止/预合成都不产生 EndOfMedia）；合成代次 `_next_synthesis_generation`（迟到旧回调会取走新任务的口径）；播放时刻重判接管 `_release_stale_play_pending`/`_mark_play_pending`；回队不盖新；watchdog 前移 `_reararm_watchdog`/`_arm_unlock_timer`/`_disarm_unlock_timer`；免打扰三处闸 `_attach_quiet_listener`/`_on_quiet_state_changed`/`_quiet_muted`；临时文件清扫 `_register_live_temp`/`_sweep_orphan_temp_files`。（已提交） |
| `pet/harness_launcher.py` | +52/−24 | 自启目标语义：`auto` 改为只拉起 dsh 服务（不再探测桌面端），新增 `service` 目标；`service` 即使 `open_browser=true` 也不开浏览器、复用实例时同样不开。（已提交） |
| `pet/frameseq_provision.py` | +8/−2 | 转换子进程补 `CREATE_NO_WINDOW`，ffmpeg 不再闪终端窗口（实机 `tasklist` 过滤 `WindowsTerminal` 零匹配）。（已提交） |
| `pet/platform_passthrough.py` | +289/−0 | **新文件**：非 Windows 逐像素输入穿透。纯判定 `_should_click_through_truth_table`（短路在逐像素命中测试之前）、`apply_through` 同时写 Qt 属性与原生标志、外部改写会被**收敛回**、原生窗重建后重放穿透态、显示/隐藏的 start/stop、隐藏时不轮询。（已提交） |
| `pet/platform_mac.py` | +22/−0 | macOS 关闭窗口系统阴影（overlay 主窗与 legacy/捕获模式窗）。（已提交） |
| `pet/quick_chat.py` | +61/−4 | 快速对话面：请求在途时的让位判定、锚定发起槽（子宠自己的气泡点开归于该槽）。（已提交） |
| `pet/chat/widgets.py` | +6/−1 | #191：助手气泡纵向 `QSizePolicy.Minimum` → `Preferred`（`wordWrap` 的 `sizeHint` 偏大被当行最小高，差额每条助手回复堆 17px；只改记账不改绘制）。（已提交） |
| `pet/chat/session_store.py` | +2/−1 | 会话目录后缀：`slot-0` 身份不再算隔离后缀（否则主宠历史会话在升级后"消失"）。（未提交） |
| `pet/update_settings.py` | +0/−3 | 死代码清理（菜单模板分发退役的连带）。（已提交） |
| `pet/persona_template.py` | +3/−3 | 清理与实现矛盾的陈旧注释（无行为改动）。（已提交） |

### 2.2 `tests/` 新增文件（78 个，首次出现在基线之后）

「覆盖」一栏 = 该文件**自己的模块自述**（`ast.get_docstring` 首行）+
**实际用例名**（脚本按 AST 从文件读出，非转述）。用例数 = 该文件里 AST 可见的
`test_*` 数量。行数为基线→工作树的 `+N/−0`。

#### 2.2.1 灵动岛、采样与网络信息（29 个）

| 文件 | 增 / 用例 | 覆盖（文件自述 + 实际用例名） |
|---|---|---|
| `tests/test_island_segments.py` | +351 / 36 | 段契约单测：`test_builtin_segment_ids_are_stable`、`test_state_vocabulary_is_the_four_state_contract`、`test_registry_rejects_duplicate_id_and_keeps_the_first`、`test_measured_width_is_cached_per_segment_id` |
| `tests/test_island_segment_render.py` | +688 / 25 | 分段渲染（段管线 + 行内几何 + 宽度白名单）：`test_primary_is_the_only_segment_without_metrics`、`test_layout_elides_an_overlong_metric_value_without_widening_the_box`、`test_info_slot_off_composes_no_segments` |
| `tests/test_island_shrink_pipeline.py` | +641 / 31 | 收缩流水线：`test_plan_elides_the_name_before_dropping_anything`、`test_plan_folds_from_the_tail_and_adds_a_chip`、`test_plan_never_folds_the_primary`、`test_apply_shrink_with_fewer_segments_than_the_plan_folds_never_slices_backwards` |
| `tests/test_island_layout_audit.py` | +444 / 11 | 排版账目总审计：`test_right_margin_matches_left_19px`、`test_status_dot_stays_inside_capsule_outline`、`test_all_text_layers_share_one_baseline` |
| `tests/test_island_unit_box.py` | +536 / 18 | 单位弱化双盒：`test_split_value_unit_separates_the_percent_and_keeps_the_merged_formatter`、`test_unit_box_width_follows_the_widest_unit_in_the_row`、`test_value_box_right_edge_never_moves_from_9_to_100` |
| `tests/test_island_status_dot.py` | +875 / 24 | 状态点五态：`test_five_state_truth_table_all_combinations`、`test_error_glyph_is_two_strokes`、`test_sonar_ring_runs_only_while_working`、`test_done_flash_interval_is_4s_and_single_shot` |
| `tests/test_island_alert_colors.py` | +750 / 26 | 告警色 + chip 告警点：`test_thresholds_are_the_spec_values`、`test_hysteresis_counts_only_sample_ticks_not_paints`、`test_chip_alert_still_lights_for_a_folded_error_segment` |
| `tests/test_island_bevel_fade.py` | +859 / 20 | 软陶笔 + 结构变化淡化：`test_top_highlight_and_bottom_shadow_pixels_on_dark`、`test_sample_value_change_never_fades`、`test_fade_end_destroys_timer_and_final_frame_is_new_content` |
| `tests/test_island_card_sections.py` | +610 / 22 | 卡片四分区：`test_card_has_four_sections_with_their_data_sources`、`test_card_falls_back_to_text_dialect_before_the_first_sample`、`test_unavailable_segment_takes_no_capsule_slot` |
| `tests/test_island_dock_sampling.py` | +440 / 10 | 停靠细条停采样：`test_starting_docked_never_creates_a_monitor`、`test_docking_closes_both_slots_and_stops_their_timers` |
| `tests/test_island_device_slot.py` | +374 / 15 | 设备槽接线：`test_device_slot_off_by_default_creates_nothing`、`test_both_device_segments_share_one_monitor`、`test_removing_a_segment_unsubscribes_it` |
| `tests/test_island_network_slot.py` | +336 / 12 | 网络段接线：`test_network_slot_off_by_default_uses_info_mode_and_starts_nothing`、`test_network_slot_tick_keeps_text_width_stable`、`test_network_slot_lost_probe_shows_dashes` |
| `tests/test_island_network_envelope.py` | +187 / 2 | 包络外读数不得引起计划/订阅/几何振荡：`test_beyond_envelope_readings_never_change_the_plan`、`test_plan_and_geometry_stay_consistent_across_ticks` |
| `tests/test_island_metrics_config.py` | +186 / 15 | `island_metrics` 配置契约：`test_default_is_an_empty_list`、`test_legacy_true_key_migrates_into_the_list`、`test_legacy_true_does_not_duplicate_an_existing_network_member` |
| `tests/test_island_review_fixes.py` | +582 / 14 | 评审修复批契约：`test_work_edge_bounce_respects_event_effects_and_quiet_mode`、`test_close_event_closes_both_monitors`、`test_unsubscribing_a_metric_clears_its_hysteresis_memory` |
| `tests/test_island_segment_extension.py` | +347 / 28 | 第三方段注册接口：`test_builtin_ids_are_reserved`、`test_oversize_verdict_warns_once_per_font`、`test_formatter_exception_degrades_to_error_state` |
| `tests/test_island_extension_host.py` | +513 / 29 | 稳定声明源 + 有界后台采样：`test_declaration_is_read_from_an_explicit_trusted_directory`、`test_allowed_ids_are_builtins_plus_declared_components` |
| `tests/test_island_extension_chain.py` | +1162 / 29 | 第三方组件完整宿主链：`test_island_metrics_admits_declared_components_only`、`test_declared_component_survives_a_restart` |
| `tests/test_island_extension_recovery.py` | +318 / 8 | 装回/删掉/换内容/退订重订/stop→start：`test_installing_the_provider_file_alone_is_seen_without_resetting_the_cache`、`test_removing_the_provider_file_stops_executing_the_cached_callable` |
| `tests/test_island_gpu_integration.py` | +570 / 20 | GPU 端到端接线：`test_gpu_only_subscribes_the_gpu_slot_and_nothing_else`、`test_cpu_only_never_touches_the_gpu_slot` |
| `tests/test_island_gpu_placeholder.py` | +148 / 8 | GPU 接线合同：`test_gpu_is_a_known_metric_id_that_survives_a_restart`、`test_gpu_is_not_a_static_unavailable_segment_any_more` |
| `tests/test_island_chat_identity.py` | +239 / 7 | 岛对话身份真值 = **slot0 档案**：`test_island_chat_uses_the_slot0_profile_role_not_the_global_default`、`test_island_chat_ignores_child_pet_roles` |
| `tests/test_sys_monitor.py` | +527 / 30 | 设备槽共享采样器：`test_clamp_interval_keeps_the_one_hz_floor`、`test_clamp_interval_falls_back_on_bad_values` |
| `tests/test_sys_monitor_gpu.py` | +872 / 27 | GPU 读数器接进共享采样线程：`test_gpu_subscriptions_are_counted_separately_and_are_idempotent`、`test_repeated_subscribe_of_the_same_key_does_not_rebuild_the_reader` |
| `tests/test_gpu_monitor.py` | +1200 / 58 | GPU 占用数据源（Windows PDH）：`test_parse_engine_instance_uses_recorded_grammar`、`test_parse_engine_instance_rejects_junk_without_guessing` |
| `tests/test_net_monitor.py` | +518 / 27 | 网络槽采样核心：`test_clamp_interval_bounds_and_bad_values`、`test_rate_meter_treats_counter_reset_as_zero_not_spike`、`test_default_probe_target_is_domestic_and_never_a_name` |
| `tests/test_network_info.py` | +289 / 19 | 「网络信息」数据层：`test_decode_json_body_handles_gbk_from_domestic_source`、`test_is_china_geo`、`test_collect_prefers_domestic_source_and_never_touches_fallback` |
| `tests/test_network_info_dialog.py` | +201 / 7 | 「网络信息」弹窗：`test_dialog_fetches_once_on_show_and_renders_snapshot`、`test_dialog_survives_close_before_result_arrives` |
| `tests/test_network_info_menu.py` | +321 / 14 | 菜单入口接线：`test_gate_default_on_and_missing_callback_counts_as_unavailable`、`test_add_network_info_keeps_disabled_entry_when_switch_off` |

#### 2.2.2 设置页、配置与档案并发（19 个）

| 文件 | 增 / 用例 | 覆盖（文件自述 + 实际用例名） |
|---|---|---|
| `tests/test_settings_stale_form_exit.py` | +1769 / 39 | 档案代次被外部推进后设置窗必须**关得掉**：`test_rebuilt_pet_keeps_the_draft_by_default_and_can_still_be_closed`、`test_discard_closes_once_without_another_save` |
| `tests/test_pet_profiles.py` | +1212 / 68 | 子宠档案存储语义单测（本批不接消费者）：`test_profile_paths_are_stable_and_include_slot_zero`、`test_identity_space_is_zero_to_128` |
| `tests/test_settings_reset_defaults.py` | +1077 / 33 | 恢复默认：`test_reset_restores_every_non_secret_key_to_defaults`、`test_reset_keeps_custom_provider_credentials_when_keyring_unavailable` |
| `tests/test_settings_slot_config_route.py` | +696 / 23 | 子宠页配置读写路由：`test_child_save_routes_global_keys_to_main_config`、`test_child_save_keeps_per_slot_keys_in_the_slot_file` |
| `tests/test_settings_profile_integration.py` | +571 / 19 | 子宠设置路由 → 新档案存储：`test_missing_per_pet_key_reads_the_same_source_default_not_the_main_pet`、`test_profile_value_wins_over_the_same_source_default` |
| `tests/test_settings_page_guide.py` | +831 / 25 | 按区直找：`test_layout_order_helper_follows_the_layout_not_the_creation_order`、`test_rows_in_layout_order_keeps_rows_outside_any_section` |
| `tests/test_settings_ia_first_cut.py` | +552 / 17 | 信息架构第一刀：`test_v1_forbidden_jargon_is_gone_from_the_production_files`、`test_v1_required_wording_is_present_where_it_belongs` |
| `tests/test_settings_default_marks.py` | +474 / 15 | 已修改标记 + 默认值小字 + 单项重置：`test_default_config_shows_no_mark_anywhere`、`test_mark_and_reset_fit_inside_the_row_without_overlapping_control` |
| `tests/test_settings_network.py` | +537 / 22 | 网络/岛指标行契约：`test_network_rows_exist_with_documented_copy`、`test_network_rows_defaults_match_config` |
| `tests/test_settings_search_aliases.py` | +435 / 14 | 搜索增强：`test_group_title_query_returns_every_row_of_the_group`、`test_collision_group_title_query_switches_to_the_owning_tab` |
| `tests/test_settings_pet_tabs.py` | +313 / 8 | 域页内标签：`test_pet_domain_uses_in_page_tabs_without_changing_sidebar`、`test_group_order_inside_each_tab_puts_the_advanced_group_last` |
| `tests/test_settings_copy_lint.py` | +197 / 3 | 设置页文案「黑话」lint：`test_no_jargon_outside_advanced_groups`、`test_whitelist_has_no_stale_entries` |
| `tests/test_config_concurrent_save.py` | +404 / 21 | 并发保存：`test_subprocess_disjoint_and_same_key_commit_order`、`test_subprocess_nested_chat_and_deletion` |
| `tests/test_config_write_lock.py` | +508 / 20 | 目录级跨进程短时写锁：`test_write_lock_path_is_dir_scoped_and_never_unlinked`、`test_lock_module_does_not_reintroduce_retired_slot_locks` |
| `tests/test_profile_snapshot_normalization.py` | +155 / 11 | 旧档快照归一化在两个消费点一致：`test_legacy_scale_uses_same_default_at_both_consumers`、`test_legacy_custom_sound_survives_at_both_consumers` |
| `tests/test_overlay_profile_reset.py` | +267 / 11 | 重置命令与几何：`test_route_reset_consumes_preferences_and_preserves_anchor_then_restart`、`test_reset_blocks_old_geometry_before_consume` |
| `tests/test_overlay_command_concurrency.py` | +134 / 7 | 设置命令并发：`test_unconsumed_a_and_later_b_both_execute`、`test_process_writer_b_during_consumer_read_is_not_deleted` |
| `tests/test_slot0_lifecycle.py` | +645 / 22 | 单宠关闭闭环与 0 只合法态：`test_close_zero_preserves_children_and_restores_identity`、`test_tray_close_of_the_only_pet_keeps_process_tray_and_services` |
| `tests/test_slot0_ownership.py` | +84 / 7 | slot0 归属：`test_migration_cleans_source_and_normalizes`、`test_explicit_global_ignores_instance_environment` |

#### 2.2.3 联动、交互、菜单、媒体、平台与构建（30 个）

| 文件 | 增 / 用例 | 覆盖（文件自述 + 实际用例名） |
|---|---|---|
| `tests/test_dsh_mid_attach_done.py` | +859 / 21 | 中途挂载回合的完成提醒（真 tailer 回填 + 真 worker + 真收敛器 + 真 800ms 确认窗）：`test_mid_attach_premise_pipeline_has_never_seen_the_agent`、`test_skipped_history_then_live_turn_end_notifies_exactly_once` |
| `tests/test_interaction_identity_ambiguity.py` | +741 / 21 | 交互身份不碰撞：`test_three_sources_two_sessions_same_rpc_id_stay_distinct`、`test_resolved_reaches_only_its_own_source_and_session` |
| `tests/test_final_interaction_regressions.py` | +593 / 16 | 唯一 resolved 摄入 + 有界 pending：`test_one_resolved_record_closes_only_its_own_session`、`test_question_resolved_is_isolated_across_sessions` |
| `tests/test_g2_alert_lifecycle.py` | +667 / 14 | 提醒生命周期：`test_carrier_exit_moves_alert_to_child_same_id_no_replay`、`test_carrier_hide_moves_copy_and_slot0_return_does_not_steal` |
| `tests/test_g2_event_delivery.py` | +557 / 15 | 事件单次声响/不重放：`test_duplicate_tool_call_across_throttle_window_shows_body_once`、`test_duplicate_question_request_keeps_one_pending_and_closes` |
| `tests/test_g2_handoff_and_repeat.py` | +322 / 10 | 交接不重放：`test_r6_slot0_return_does_not_replay_alert_or_sound`、`test_r6_alert_resolvable_after_slot0_return` |
| `tests/test_child_bubble_quick_chat.py` | +92 / 2 | 子宠自己的气泡可点且归于发起槽：`test_child_own_bubble_is_clickable_and_anchors_quick_chat`、`test_child_bubble_opens_quick_chat_on_real_mouse_click` |
| `tests/test_animation_menu_close_and_group.py` | +448 / 12 | #221 两条：`test_clicking_random_action_closes_whole_menu_chain`、`test_grouping_splits_prefix_families_without_losing_actions` |
| `tests/test_animation_icon_worker_lifecycle.py` | +434 / 8 | 缩略图 worker 生命周期（真 QThreadPool）：`test_loader_failure_does_not_stall_the_thumbnail_queue`、`test_success_still_decodes_every_icon` |
| `tests/test_quiet_mode.py` | +1079 / 45 | 免打扰 #208：`test_suppression_truth_table`、`test_duration_choices_and_remaining_label` |
| `tests/test_memory_trim.py` | +1033 / 38 | 回收内存 #210：`test_decide_target_truth_table`、`test_win32_api_uses_minimal_access_rights_and_closes_every_handle` |
| `tests/test_weather.py` | +517 / 42 | 天气取数纯逻辑：`test_normalize_city_name_keeps_the_users_original_name`、`test_normalize_city_name_is_idempotent_on_every_sample` |
| `tests/test_weather_menu.py` | +550 / 31 | 天气菜单与城市子菜单：`test_show_weather_action_calls_through_to_the_window_callback`、`test_show_weather_action_absent_without_callback` |
| `tests/test_weather_service.py` | +311 / 14 | 天气服务：`test_no_city_bubbles_guidance_without_any_request`、`test_disabled_switch_bubbles_and_never_fetches` |
| `tests/test_weather_settings.py` | +226 / 11 | 天气设置：`test_weather_rows_live_in_their_own_interaction_tab`、`test_default_values_are_the_documented_ones` |
| `tests/test_lyric_sources.py` | +439 / 17 | 歌词来源接线：`test_foobar_supplies_track_when_no_smtc_session`、`test_playing_smtc_session_beats_foobar`、`test_browser_title_is_cleaned_into_the_fetch_query` |
| `tests/test_music_title.py` | +359 / 24 | 标题 → 取词查询词：`test_web_title_truth_table`、`test_cleaning_never_invents_characters`、`test_parse_auto_does_not_guess_the_order`、`test_pathological_format_strings_fail_fast` |
| `tests/test_drop_gravity_toggle.py` | +245 / 10 | #219 下落开关三重登记：`test_default_is_off_and_survives_round_trip`、`test_row_disabled_when_capture_mode_makes_topology_legacy` |
| `tests/test_bubble_subtitle_budget.py` | +199 / 4 | #216 副标题参与高度预算：`test_balance_subtitle_stays_inside_scaled_standard_bubble`、`test_balance_subtitle_stays_inside_breath_bubble` |
| `tests/test_golden_spin_retarget.py` | +209 / 7 | 黄金回旋换目标：`test_retarget_menu_trigger_settles_previous_pet_and_spins_new_one`、`test_exit_spinning_child_settles_target` |
| `tests/test_platform_passthrough.py` | +688 / 23 | 非 Windows 逐像素穿透：`test_pure_decision_truth_table`、`test_external_flag_write_is_converged_back`、`test_recreated_native_window_replays_through_state` |
| `tests/test_platform_mac_shadow.py` | +143 / 7 | macOS 关窗口阴影：`test_no_window_shadow_flag_dispatch`、`test_overlay_shadow_flag_survives_on_top_toggle` |
| `tests/test_final_cleanup_boundaries.py` | +486 / 17 | 清理所有权与冻结卸载：`test_foreign_temp_mei_dir_with_other_app_file_is_untouched`、`test_foreign_owner_marker_is_not_trusted` |
| `tests/test_cleanup_mei_cache_cli.py` | +87 / 3 | 清理脚本 CLI 契约：`test_help_states_the_ownership_gate`、`test_preview_lists_only_owned_candidates` |
| `tests/test_overlay_settings_unavailable_feedback.py` | +142 / 5 | 设置交不出去时的可见反馈：`test_open_settings_for_with_isolation_off_bubbles_and_returns_false`、`test_open_settings_for_with_launch_failure_bubbles_other_reason` |
| `tests/test_single_pet_close_entry.py` | +182 / 3 | 单宠关闭入口：`test_single_pet_tray_exposes_close_entry_and_keeps_quit_separate`、`test_single_pet_close_then_restore_then_quit` |
| `tests/test_tray_settings_deferred_dispatch.py` | +608 / 17 | 托盘入口延迟派发：`test_legacy_tray_settings_entry_waits_for_menu_close`、`test_legacy_tray_chat_entry_waits_for_menu_close` |
| `tests/test_frameseq_bundle_gate.py` | +766 / 55 | 帧序列完整性硬门 + 素材供给入口：`TestGateVerdicts::test_complete_tree_passes`、`TestGateVerdicts::test_stale_encoder_fails`、`TestSourceIdentity::test_source_sha_stamp_mismatch_fails`、`TestPrepareRealMaterial` 真素材用例 |
| `tests/test_ci_workflows.py` | +283 / 20 | CI 工作流结构门：`TestPrTestWorkflow::test_keeps_three_os_matrix_and_pr_integration_trigger`、`TestPrTestWorkflow::test_has_manual_dispatch_with_source_ref` |
| `tests/test_stream_capture_window_switch.py` | +134 / 3 | 窗口能力跟随主配置：`test_slot_window_follows_main_capture_switch`、`test_slot_window_keeps_own_switch_when_main_capture_off` |

### 2.3 `tests/` 既有文件的增量（75 个）

行数为基线→工作树累计 diff；「新增用例」一栏的**名字**由脚本从 `git diff -U0` 的 `+` 侧
抽出真实 `def test_*`，`= 0` 表示该文件本批**没有新增测试函数**（只改替身面 / 断言口径 /
夹具），改了什么写在说明里。

| 文件 | 增删 | 新增用例 | 真实新增用例名 / 改动说明 |
|---|---|---|---|
| `tests/conftest.py` | +96/−0 | 0 | 新增共享夹具：假屏尺寸、把 `window_placement.desktop_area` 钉成 `None`、QLocal 名字长度约束、有界等待辅助——治「只在我机器上红」的族（#211） |
| `tests/test_agent_link.py` | +1054/−10 | 17 | `test_working_to_success_plays_done_bubble_and_sound`、`test_returning_to_busy_inside_confirm_window_cancels_done`、`test_success_then_idle_does_not_repeat_done`、`test_converged_success_enters_presentation_pipeline`、`test_real_bridge_turn_records_reach_done_bubble`、`test_failed_turn_sends_error_not_success_to_the_island`、`test_failed_turn_with_idle_before_execution_failed_never_claims_success`、`test_next_turn_after_post_completion_error_plays_done_` 等 17 条 |
| `tests/test_agent_event_protocol.py` | +104/−0 | 4 | `test_legacy_resolution_event_names_normalize_to_interaction_resolved`、`test_interaction_resolved_reads_top_level_call_id`、`test_retired_control_result_events_no_longer_produce_semantic_events`、`test_control_result_event_class_stays_removed` |
| `tests/test_dsh_state.py` | +102/−1 | 6 | `test_success_edge_needs_a_real_transition`、`test_turn_completion_identity_from_turn_end`、`test_turn_completion_epoch_separates_successive_turns`、`test_turn_completion_ignores_non_completion_records`、`test_turn_completion_accepts_any_success_shaped_record`、`test_turn_completion_cursor_fallback_and_reset` |
| `tests/test_architecture.py` | +192/−1 | 5 | `test_retired_dead_facade_files_are_gone`、`test_pet_tree_has_zero_dead_facade_imports`、`test_retired_legacy_menu_files_are_gone`、`test_retired_menu_template_key_confined_to_migration`、`test_pet_tree_has_zero_retired_legacy_menu_references` |
| `tests/test_background_service_gates.py` | +127/−7 | 4 | `test_stream_capture_mode_boots_legacy_single_window`、`test_overlay_topology_would_restore_spawned_pets`、`test_capture_mode_refuses_manual_spawn`、`test_overlay_topology_still_spawns_on_menu_action` |
| `tests/test_config_schema.py` | +518/−3 | 19 | `test_anim_menu_stay_open_defaults_to_closing_after_action`、`test_memory_trim_keys_have_documented_defaults`、`test_dirty_weather_keys_are_normalized`、`test_network_keys_defaults_are_off_probe_and_on_menu`、`test_repeated_normalization_never_erodes_the_city_name`、`test_city_name_normalization_is_a_fixed_point_on_load_and_reload`、`test_harness_launch_target_accepts_service_and_falls_back_to_auto` 等 19 条 |
| `tests/test_config_reload_null.py` | +30/−2 | 1 | `test_reload_keeps_in_memory_position_when_keys_are_absent` |
| `tests/test_chat_subsystem.py` | +63/−5 | 1 | `test_modern_chat_trailing_blank_does_not_grow_with_message_count`（#191） |
| `tests/test_desktop_pet_features.py` | +179/−265 | 5 | `test_context_menu_has_no_template_switch_entry`、`test_context_menu_always_applies_the_modern_style`、`test_submenu_inherits_the_modern_style_from_its_parent`、`test_wired_petwindow_offers_settings_entry`、`test_modern_menu_exposes_no_template_switch_action` |
| `tests/test_dynamic_island_revamp.py` | +66/−0 | 3 | `test_config_cleans_dirty_island_coordinates`、`test_island_survives_dirty_stored_coordinates`、`test_island_restores_legal_stored_coordinates` |
| `tests/test_festival.py` | +26/−0 | 2 | `test_quiet_mode_defers_festival_bubble`、`test_speak_hint_mentions_quiet_mode` |
| `tests/test_file_eater.py` | +284/−0 | 9 | `test_eat_paths_offer_chain_enforces_scan_budget`、`test_small_drop_reports_no_truncation`、`test_eat_paths_stops_at_file_budget`、`test_eat_paths_stops_at_time_budget_in_one_slow_directory`、`test_eat_paths_stops_when_each_stat_is_slow` 等 9 条 |
| `tests/test_file_interpret.py` | +108/−0 | 4 | `test_collect_interpretable_stops_at_file_budget`、`test_collect_interpretable_stops_at_time_budget`、`test_offer_marks_truncated_scan_in_alert`、`test_offer_all_items_over_budget_hints_instead_of_unreadable` |
| `tests/test_frameseq_provision.py` | +16/−0 | 1 | `test_creation_flags_hide_ffmpeg_console_on_windows` |
| `tests/test_harness_launcher.py` | +102/−25 | 4 | `test_auto_resolves_to_service_without_probing_desktop`、`test_auto_launch_is_headless_service`、`test_service_target_stays_headless_even_with_open_browser_true`、`test_service_target_does_not_open_browser_on_reused_instance` |
| `tests/test_harness_ownership.py` | +31/−2 | 1 | `test_autostart_default_target_starts_service_without_gui_or_browser` |
| `tests/test_island_chat.py` | +418/−1 | 10 | `test_island_feedback_yields_to_inflight_request`、`test_island_switch_character_drops_inflight_answer`、`test_island_switch_character_drops_queued_late_delta_and_completion`、`test_running_island_disable_retires_chat_availability`、`test_disabled_island_hidden_chat_click_falls_back_to_non_island_route` 等 10 条 |
| `tests/test_island_shell_wiring.py` | +44/−0 | 1 | `test_aggregate_pet_visible_accounts_for_individually_hidden_sprites` |
| `tests/test_menu_layout.py` | +124/−18 | 2 | `test_network_info_entry_status_follows_its_setting`、`test_settings_menu_page_has_no_menu_version_selector` |
| `tests/test_music_lyric.py` | +726/−14 | 19 | `test_no_lyric_retry_after_cooldown_not_permanent_blacklist`、`test_first_song_lyrics_resolve_the_progress_estimate_hint`、`test_same_track_retries_lyric_fetch_after_cooldown`、`test_netease_matches_artist_via_ar_field`、`test_lrclib_instrumental_flag`、`test_stale_pending_playback_never_leaks_across_songs`、`test_pause_still_open_when_lyrics_arrive_freezes_clock` 等 19 条 |
| `tests/test_music_player_settings.py` | +210/−0 | 8 | `test_foobar_lyrics_rows_are_absent_on_non_windows`、`test_foobar_lyrics_widgets_are_windows_only`、`test_save_source_settings_writes_both_switches_and_format`、`test_music_player_pickers_are_editable_on_the_child_page` 等 8 条 |
| `tests/test_overlay_app_hosts.py` | +218/−0 | 7 | `test_overlay_switch_character_syncs_open_chat_window`、`test_overlay_switch_character_syncs_island_chat_bubble`、`test_capture_mode_switch_character_syncs_quick_and_island_bubbles`、`test_chime_construction_without_stop_leaves_quiet_listener`、`test_shared_quiet_table_is_clean_at_this_boundary` 等 7 条 |
| `tests/test_overlay_instance_gate.py` | +73/−31 | 4 | `test_gate_is_topology_independent`、`test_legacy_topology_also_holds_the_gate`、`test_main_legacy_topology_also_takes_gate_and_does_not_take_slot_lock`、`test_main_legacy_topology_refuses_second_instance` |
| `tests/test_overlay_per_slot_settings.py` | +17/−18 | 1 | `test_slot_missing_or_broken_uses_defaults_not_main` |
| `tests/test_overlay_settings_command.py` | +244/−4 | 17 | `test_topology_follows_stream_capture_mode_in_config`、`test_explicit_env_wins_over_stream_capture_config`、`test_parent_running_topology_env_wins_over_disk_capture_config`、`test_target_zero_is_a_valid_slot_identity`、`test_claim_lease_recovers_without_removing_other_pending`、`test_corrupt_encoding_or_command_type_does_not_block_next_write` 等 17 条 |
| `tests/test_overlay_shell.py` | +187/−2 | 6 | `test_topology_config_input_is_isolated_to_tmp`、`test_switch_character_syncs_chat_surfaces`、`test_closing_slot0_leaves_it_empty_without_promoting_a_child`、`test_closing_slot0_keeps_its_profile_and_can_be_restored` 等 6 条 |
| `tests/test_overlay_spawn.py` | +70/−28 | 2 | `test_spawn_reuses_retired_identity_when_history_is_full`、`test_spawn_exhausted_identities_reports_bubble` |
| `tests/test_overlay_spawn_state.py` | +36/−14 | 4 | `test_allocate_slot_restores_smallest_inactive_profile`、`test_allocate_slot_reuses_smallest_retired_when_history_is_full`、`test_allocate_slot_preserves_existing_profiles`、`test_allocate_slot_raises_only_when_all_slots_active` |
| `tests/test_overlay_tray_routing.py` | +170/−30 | 6 | `test_tray_single_pet_has_per_pet_close_entry`（原 `..._has_no_per_pet_submenu` 更名）、`test_tray_exit_this_on_main_pet_promotes_first_child`、`test_tray_exit_this_on_main_pet_cancel_keeps_everything`、`test_tray_exit_this_on_main_pet_without_children_says_app_quit`、`test_tray_and_context_menu_exit_confirm_copy_is_identical` |
| `tests/test_quick_chat.py` | +271/−2 | 6 | `test_switch_character_moves_session_and_prompt_to_new_character`、`test_switch_character_drops_inflight_answer`、`test_switch_character_drops_queued_late_delta_and_completion`、`test_switch_character_drops_queued_late_error` 等 6 条 |
| `tests/test_requested_regressions.py` | +298/−14 | 7 | `test_harness_target_offers_service_item_and_auto_says_headless`、`test_harness_target_hint_helper_keeps_both_platform_copies_verbatim`、`test_menu_autostart_persists_wanted_flag`、`test_modern_settings_escape_keeps_the_dialog_open_when_save_fails`、`test_modern_settings_escape_closes_when_save_succeeds` 等 7 条 |
| `tests/test_runtime_cleanup.py` | +82/−24 | 4 | `test_find_stale_runtime_dirs_only_returns_owned_old_mei_directories`、`test_cleanup_stale_runtime_dirs_removes_owned_and_keeps_unowned`、`test_garbage_owner_marker_is_not_trusted` 等 4 条（A01 清理越界） |
| `tests/test_session_end_ffmpeg_guard.py` | +70/−7 | 1 | `test_normal_quit_survives_a_missing_chat_module` |
| `tests/test_settings_and_resources.py` | +76/−6 | 3 | `test_clear_spawned_pets_targets_all_for_slot0_identity`、`test_clear_spawned_pets_stays_disabled_with_a_reachable_hint_on_a_child_page`、`test_clear_spawned_pets_row_copy_does_not_promise_data_deletion` |
| `tests/test_settings_overlay_copy.py` | +18/−13 | 2 | `test_stream_capture_enabled_with_restart_level_copy_under_overlay`、`test_stream_capture_toggle_clickable_in_both_topologies` |
| `tests/test_settings_process_isolation.py` | +117/−9 | 3 | `test_launch_settings_process_tells_child_the_running_topology`、`test_spawn_settings_process_hands_environment_to_the_detached_child`、`test_immediate_sound_toggles_do_not_roll_back_external_changes` |
| `tests/test_settings_subslot_autostart.py` | +53/−13 | 3 | `test_modern_settings_dialog_keeps_autostart_editable_for_every_pet`、`test_autostart_row_hint_states_the_global_scope_on_a_pet_page`、`test_child_page_autostart_save_lands_in_the_global_config` |
| `tests/test_single_process_spawn.py` | +63/−24 | 2 | `test_open_quick_chat_routes_to_overlay_shell_when_win_none`、`test_open_quick_chat_win_none_without_overlay_is_quiet_noop` |
| `tests/test_sprite_edge_probe.py` | +94/−0 | 1 | `test_overlay_return_corner_cancels_active_probe_session` |
| `tests/test_sprite_feeding.py` | +152/−2 | 5 | `test_drop_on_child_pet_eats_and_bubbles_on_child`、`test_overlay_drop_event_routes_to_hit_sprite`、`test_drop_truncated_dir_reports_budget_in_result_and_bubble`、`test_small_drop_is_not_marked_truncated` 等 5 条 |
| `tests/test_sprite_menu_facade.py` | +814/−14 | 18 | `test_character_switch_clears_menu_icon_cache`、`test_late_worker_write_is_keyed_to_the_old_library`、`test_cache_entry_does_not_keep_the_library_alive`、`test_exiting_spawned_pet_drops_its_menu_icon_cache`、`test_exit_main_pet_confirmed_promotes_first_child`、`test_exit_main_pet_confirm_box_defaults_to_cancel` 等 18 条 |
| `tests/test_sprite_menu_parity.py` | +315/−114 | 12 | `test_menu_tree_matches_reference_petwindow`、`test_ai_settings_stays_merged_into_pet_settings_entry`、`test_music_menu_lyric_align_availability_matches_the_registry`、`test_network_info_entry_greyed_out_when_switched_off`、`test_long_animation_menu_groups_and_closes` 等 |
| `tests/test_sprite_menu_target.py` | +53/−20 | 1 | `test_balance_targets_the_initiating_pet_and_update_still_uses_the_shell` |
| `tests/test_sprite_physics.py` | +161/−0 | 5 | `test_drop_gravity_slow_release_falls_to_ground`、`test_drop_gravity_off_slow_release_stays_in_the_air`、`test_drop_gravity_grounded_slow_release_rests_without_bounce` 等 5 条（#219） |
| `tests/test_stream_capture_copy.py` | +176/−21 | 7 | `test_stream_capture_copy_is_restart_level_under_overlay_topology`、`test_stream_capture_check_is_never_greyed_out`、`test_stream_capture_child_row_is_editable_in_legacy`、`test_capture_config_flips_topology_verdict` 等 7 条 |
| `tests/test_todo_reminder.py` | +162/−0 | 7 | `test_daily_lead_window_crosses_midnight`、`test_service_daily_cross_midnight_lead_fires_before_midnight`、`test_panel_save_failure_keeps_editor_and_draft`、`test_panel_save_retry_after_failure_writes_once` 等 7 条 |
| `tests/test_uninstall_cleanup.py` | +285/−9 | 12 | `test_slot_profiles_in_own_variant_are_not_other_instances`、`test_near_miss_slot_names_still_protect`、`test_main_entry_delegates_uninstall_cleanup_without_qt_or_desktop_main`、`test_main_returns_shared_entry_failure_code` 等 12 条（A12 + 入口统一） |
| `tests/test_voice_chime_edge_voice.py` | +71/−0 | 3 | `test_worker_publishes_cache_path_atomically`、`test_worker_exception_after_partial_write_cleans_temp`、`test_worker_empty_audio_leaves_no_temp_file` |
| `tests/test_voice_chime_service.py` | +2512/−317 | 17 | `test_quiet_mode_silences_chime_voice_and_still_defers_bubble`、`test_quiet_mode_skips_precache_synthesis`、`test_quiet_mode_drops_inflight_synthesis_result`、`test_festival_speech_is_silenced_under_quiet_mode`、`test_click_self_talk_speech_is_exempt_from_quiet_mode`、`test_pending_speech_carries_quiet_exemption_through_the_queue`、`test_discarded_synthesis_drains_pending_speech_with_exemption` 等 17 条 |
| `tests/test_config_domains.py` | +0/−341 | 0 | **整文件删除**：与 `pet/config_domains.py` 一同退役（`test_from_dict_to_dict_roundtrip_is_stable`、`test_normalize_equals_from_dict_data` 等 12 条随之删除）——域门面已无消费者，留着会假装那条路径还活着 |
| `tests/test_effects_integration.py` | +2/−19 | 0 | 删掉 `test_legacy_menu_has_golden_spin_and_edge_probe`（旧菜单退役后断言无对象） |
| `tests/test_drag_move_coalescing.py` | +25/−3 | 0 | 假屏 1920×1200 → 4096×3072：窗口初始位置在 `PetWindow` 构造时按**运行机真实屏幕**算，假屏之后才装上（#211 实测真机制，上游归因与实测不符） |
| `tests/test_pet_interaction_locks.py` | +48/−9 | 0 | 同上，假屏与多屏快照口径对齐 |
| `tests/test_bubble_text_scale.py`、`tests/test_click_self_talk_speech.py`、`tests/test_config_instance.py`、`tests/test_harness_lifecycle.py`、`tests/test_menu_tree_release.py`、`tests/test_overlay_bubble_wiring.py`、`tests/test_overlay_chat_proactive.py`、`tests/test_overlay_collision_toggle.py`、`tests/test_overlay_hidden_polling.py`、`tests/test_overlay_recycle_settings.py`、`tests/test_overlay_screen_migration.py`、`tests/test_overlay_self_talk.py`、`tests/test_overlay_sprite_settings.py`、`tests/test_overlay_window_capabilities.py`、`tests/test_self_talk_image_chance.py`、`tests/test_settings_interaction_tabs.py`、`tests/test_slot_and_memory.py`、`tests/test_sprite_visibility.py`、`tests/test_updater.py`、`tests/test_window_position.py`、`tests/test_agent_link_subtraction.py`（21 个） | 合计 +≈330 / −≈150 | 0 | **契约跟随式更新**：旧菜单退役后的替身面、捕获模式拓扑语义、逐 sprite 呈现面、0 只合法态、几何写入走代次令牌、会话库身份、各模块替身属性等；无新增测试函数，故不列名（逐文件增删见 `inventory.tsv`） |

### 2.4 `docs/`（36 个）

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `docs/PR-REPORT-*`（本版批次报告 **22 份新增** + `OVERLAY-MENU-PARITY` **1 份补章**） | 合计 +约 6900 | 本版逐批交付证据。新增 22 份的文件名**逐条列在此处（不是示例）**：`PR-REPORT-HARNESS-SERVICE-TARGET-2026-10-06.md`、`PR-REPORT-ISLAND-P1-SEGMENT-REDESIGN-2026-10-07.md`、`PR-REPORT-ISLAND-P2P3-VISUAL-EXTENSION-2026-10-07.md`、`PR-REPORT-ISSUE-172-NETWORK-INFO-2026-10-07.md`、`PR-REPORT-ISSUE-191-CHAT-BOTTOM-BLANK-2026-10-07.md`、`PR-REPORT-ISSUE-208-QUIET-MODE-2026-10-07.md`、`PR-REPORT-ISSUE-209-WEATHER-2026-10-07.md`、`PR-REPORT-ISSUE-210-MEMORY-TRIM-2026-10-07.md`、`PR-REPORT-ISSUE-211-TEST-FIXES-2026-10-07.md`、`PR-REPORT-ISSUE-216-BALANCE-SUBTITLE-2026-10-07.md`、`PR-REPORT-ISSUE-219-DROP-GRAVITY-2026-10-07.md`、`PR-REPORT-ISSUE-220-RESET-DEFAULTS-2026-10-07.md`、`PR-REPORT-ISSUE-221-MENU-CLOSE-GROUP-2026-10-07.md`、`PR-REPORT-ISSUE-228-BILI-LYRICS-2026-10-07.md`、`PR-REPORT-LEGACY-MENU-RETIREMENT-2026-10-08.md`、`PR-REPORT-RELEASE-CANDIDATE-DEPLOY-2026-10-08.md`、`PR-REPORT-REVIEW-FIXES-2-2026-10-08.md`、`PR-REPORT-REVIEW-FIXES-2026-10-08.md`、`PR-REPORT-STREAM-CAPTURE-PHASE-A-2026-10-07.md`、`PR-REPORT-THREE-PLATFORM-INPUT-2026-10-07.md`、`PR-REPORT-TRAY-DEFER-SETTINGS-FEEDBACK-2026-10-07.md`、`PR-REPORT-VOICE-QUIET-AND-CONSOLE-FIXES-2026-10-09.md`。每份都按三份证据纪律写，`test_pr_report_discipline.py` 强制校验标题含三个必备章节并在 `INDEX.md` 登记。补章 1 份：`PR-REPORT-OVERLAY-MENU-PARITY-2026-09-24.md`（+1/−1，登记后继变更）。 |
| `docs/ISLAND-SEGMENTS-EXTENSION.md` | +316/−0 | 第三方岛段的**公开契约**文档（注册面、字段盒、护栏、GPU 段现状与"勾了没反应"前提作废的就地更新） |
| `docs/INDEX.md` | +27/−2 | 全文档入口索引：登记本版新增的批次报告 + 本报告一行；既有条目就地补链接 |
| `docs/PRODUCT-NEXT-STEPS-SPEC-2026-10-09.md` | +265/−0 | **未跟踪**：本版主规范（发布门禁、无宠/退出/托盘口径、三端验收口径、DLC 另立的口径）。按品牌检查口径写，含品牌名的分支地址只在本地交接里（未进 `docs/`）。 |
| `docs/PRODUCT-STATUS-2026-10-09.md` | +142/−0 | **未跟踪**：产品成果台账（**2026-10-11 全量重写**为"当前状态快照"，旧中途数字已删除）。六节：授权边界 / 当前机器与真机证据（唯一可引用的"最新"）/ 能力现状快照（统一状态词）/ 真实未完成与阻断（11 项）/ GitHub 开放对象适用性 / 下一步。**它的覆盖边界与本报告 §6.1 一致**：唯一一次全量只到 close 增量（6342 passed），其后三批增量只有各自相关集证据 |
| `docs/ONEDIR_PACKAGING.md` | +70/−2 | 新增「六、CI 验证与三端手动构建」：手动输入的准确用法、素材缓存 key 构件、门在脚本里、以及本批**未**覆盖的口径 |
| `docs/ACCEPTANCE_TESTS.md` | +42/−7 | 验收清单随本版实现更新（删失效引用、补新能力的人工验收项） |
| `docs/DSH-REQUEST-EVENT-CATALOG.md` | +42/−1 | DSH 事件目录随减法与新信号（`dsh_turn_completed`）补齐 |
| `docs/DSH-BRIDGE-PET-EVENT-CONTRACT-2026-09-02.md` | +20/−6 | 桥接事件契约：删除零生产者零消费者的 `ControlResultEvent` 条目 |
| `docs/SETTINGS-CHANGE-GATES.md` | +236/−0 | 设置变更门禁随本版新增的键与页面结构扩充（改/加/移设置项前必读） |
| `docs/CONTEXT-MENU-RESEARCH-AND-REFACTOR-2026-08-25.md` | +12/−0 | 旧版菜单退役的用户可见说明与文档同步 |
| `docs/SETTINGS-REDESIGN-Q6-Q7-DOMAIN-LAYOUT-DECISION.md` | +4/−2 | 域布局裁决文档按退役结果就地更正 |
| `docs/DEV-HANDOVER.md` | +5/−9 | 交接规范校准（架构守卫的实测行数/用例数按真值写入） |
| `docs/WINDOW_PY_SPLIT_GUIDE.md` | +0/−1 | 删一条已失效的引用 |

### 2.5 `scripts/`、CI、打包、集成与仓库根（18 个）

| 文件 | 增删 | 改了什么 + 为什么（状态） |
|---|---|---|
| `scripts/prepare_frameseq_bundle.py` | +251/−0 | **新文件（未跟踪）**：素材供给唯一入口 = 先验证 → 缺才转 → 转完再验；`--print-cache-key` 输出 CI 缓存 key；转换器非零原样冒泡、不重试。干净检出没有 `frameseq/`（刻意不入库），三端必须同一口径补齐。 |
| `scripts/check_frameseq_bundle.py` | +348/−0 | **新增**：打包前帧序列完整性硬门（源身份戳、编码档、非规则帧集、缺 clip、坏 meta 逐类可判，问题列表上限 20 条）。 |
| `scripts/build_onedir.ps1` | +15/−0 | Windows 构建接入该硬门（非 GIF 变体） |
| `scripts/build_macos.sh` | +22/−0 | 非 GIF 变体在 PyInstaller 前跑门，非零 `exit 1`（此前只有 workflow 里有门，绕过 workflow 的本地构建仍会打缺帧序列的静默降级包） |
| `scripts/build_linux.sh` | +22/−0 | 同上 |
| `scripts/cleanup_mei_cache.py` | +17/−4 | 清理只针对**带本产品 owner 标记**的目录，help 写明归属门禁 |
| `scripts/capture_settings_pages.py` | +0/−10 | 同步随菜单版本行失效的残留引用 |
| `.github/workflows/pr-test.yml` | +67/−0 | 加 `workflow_dispatch` + `source_ref` 输入；checkout 显式 `ref: source_ref \|\| github.sha`；新增「记录 resolved source SHA」与「记录工具链版本」两步（`pip freeze` 落 `$GITHUB_STEP_SUMMARY`——requirements 全是 `>=` 无 lock，三端各装一套）；新增 `Setup Node 20`（桥门禁依赖 `node --test`，此前靠 runner 预装会漂移） |
| `.github/workflows/build-windows.yml` | +85/−3 | 同上两个输入（+`upload_artifacts` 默认 `false`）；素材 key/缓存/供给三步；`Upload artifact` 加条件；`Publish Release` 加 `event_name == 'push'`；**修 AppId**：webm 变体不再与 webm-chat 共用默认 AppId（共用会互装覆盖对方卸载登记）；ISCC 显式传 `/DMyAppVersion=$version`（`.iss` 里的默认值与 `pet/__init__.py` 会漂移） |
| `.github/workflows/build-macos.yml` | +74/−1 | 同 Windows（除安装器）；macOS 此前**没有**任何素材门 |
| `.github/workflows/build-linux.yml` | +74/−1 | 同上；Linux 此前**没有**任何素材门 |
| `packaging/dsh-pet.iss` | +56/−3 | 卸载清理回调、AppId/版本注入、两变体登记分开 |
| `packaging/pet_entry.py` | +14/−0 | 冻结入口改用统一 `uninstall_cleanup.main()`（逐步诊断 + 留痕 + 退出码只有一处实现） |
| `packaging/pet_entry_no_chat.py` | +11/−0 | 同上（无聊天变体） |
| `integrations/dsh-pet-bridge/index.js` | +18/−12 | 桥接侧注释与减法后的实现对齐（无行为改动） |
| `AGENTS.md` | +28/−2 | 工程指南随本版变化更新（拓扑/档案/设置门禁等条目） |
| `CONTEXT.md` | +36/−0 | 领域上下文补本版新增的运行态口径（Runtime Disabled 门、重置契约、逐 sprite 呈现面） |
| `README.md` | +25/−18 | 面向用户/贡献者的结构说明与退役结果对齐 |

### 2.6 采集时点仍未跟踪 / 未提交的产品文件（37 个，显式枚举）

`git ls-files --others --exclude-standard` 的实际输出，**一个不省**：

**未跟踪（37）**

```
docs/PRODUCT-NEXT-STEPS-SPEC-2026-10-09.md        docs/PRODUCT-STATUS-2026-10-09.md
pet/config_write_lock.py                          pet/gpu_monitor.py
pet/island_extension_host.py                      pet/pet_profiles.py
pet/settings_close_flow.py                        scripts/prepare_frameseq_bundle.py
tests/test_animation_icon_worker_lifecycle.py     tests/test_child_bubble_quick_chat.py
tests/test_ci_workflows.py                        tests/test_cleanup_mei_cache_cli.py
tests/test_config_concurrent_save.py              tests/test_config_write_lock.py
tests/test_dsh_mid_attach_done.py                 tests/test_final_cleanup_boundaries.py
tests/test_final_interaction_regressions.py       tests/test_g2_alert_lifecycle.py
tests/test_g2_event_delivery.py                   tests/test_g2_handoff_and_repeat.py
tests/test_gpu_monitor.py                         tests/test_interaction_identity_ambiguity.py
tests/test_island_chat_identity.py                tests/test_island_extension_chain.py
tests/test_island_extension_host.py               tests/test_island_extension_recovery.py
tests/test_island_gpu_integration.py              tests/test_overlay_command_concurrency.py
tests/test_overlay_profile_reset.py               tests/test_pet_profiles.py
tests/test_profile_snapshot_normalization.py      tests/test_settings_profile_integration.py
tests/test_settings_stale_form_exit.py            tests/test_single_pet_close_entry.py
tests/test_slot0_lifecycle.py                     tests/test_slot0_ownership.py
tests/test_sys_monitor_gpu.py
```

**另有 103 个已跟踪文件在采集时点仍有未提交改动**（完整名单见
`.scratch/product-delivery-report-20261011/inventory.tsv` 的 `still_dirty=Y` 列）。

与"是否本版新增"的关系（三个数不要混）：全 298 个产品文件里，**相对基线为新增的文件
共 109 个** = 未跟踪新文件 37 + 已跟踪但相对基线属新增（`added-vs-baseline`）72；
其余 189 个是基线里已存在、本版改动的文件。这 109 个新增文件**每一个**都已在上面的
§2.1–§2.5 各域表里逐条给出增删行数与改动意图（不是只列在清单里）。

### 2.7 看起来相关但故意没动

| 项 | 为什么不动 |
|---|---|
| `docs/FRAMESEQ*` 相关的既有编码档常量、`pet/frameseq_provision.py` 的档位定义 | 帧序列 Q70 编码档切换是**基线之前**的成果，本版只加了一个 `CREATE_NO_WINDOW`；动档位会连带重转 379 MiB 素材 |
| `pet/collision.py` / `pet/sprite_collision.py` | 碰撞数学是纯函数且本版未改语义；岛的 stadium 夹取走 `island_bridge` 既有入口 |
| `tests/` 里其余兄弟代理曾触碰的测试卫生文件 | 只做本版 scope 内的契约跟随；不顺手全改历史失效引用（§7 说明） |
| 上游未合并 PR 的提案代码（#235 / #236 / #237 / #232 / #229 / #211 / #172） | 逐条核真后的结论是「本版已有更强实现」或「采纳即崩」或「属新 feature」，见 §7.3 |

## 三、实现要点

**灵动岛 = 段序列 + 计划驱动**。信息槽不再是一个"写文本的地方"，而是**段列表**：
主信息段恒在，`island_metrics` 的成员各占一段（列表序 = 优先级）。每次刷新只重算
「行计划」这一个纯数据（`plan_info_row` → `ShrinkPlan`），几何与订阅都从计划派生：

- **宽度白名单是结构保证**——采样读数进不了计划输入键，所以读数变化在结构上不可能
  触发 `setFixedSize`（这也是 P1 报告里"120 轮 tick 0 次改宽"的机制来源）；
- **收缩是逐级退让而不是把字压扁**：省略名字 → 隐藏名字 → 尾部折 +N chip → 主信息
  省略 → 保底；被折掉的段**即时退订采样**（subscriber_count 实测 2→0）；
- **告警只染值不染框**，滞回按样本拍推进（不是按重绘拍），折叠后的 chip 仍携带最高级；
- 停靠细条、卡片、单击路由各自独立，停靠即停采样（0 采样器 / 0 定时器 / 0 线程）。

**第三方段是对外契约，不是内部钩子**。`register_segment` 是零 Qt 的声明式接口，
四道护栏把"坏声明"挡在进来之前或降级到 error 态（非法 id / 保留 id / 缺字段 /
非声明对象 / 格式串抛异常），宽度超界**不拒绝只降级为优先折叠并只警告一次**。
公开语义写在 `docs/ISLAND-SEGMENTS-EXTENSION.md`。

**DSH 回合完成：判据从"状态"换成"身份"**。`turn/end` 是桥接真实写出的收尾事实，
但它不带源 ID，且收敛器是 edge-trigger（已停在 SUCCESS 时再收一条收尾零产出）。
原来的唯一判据是 `busy→success` 边沿，四种真实来向（中途挂载 / `idle` 基线先到 /
收敛器已停在 SUCCESS / 关开联动残留终态）拿不到这个边沿。新判据是
`TurnCompletionTracker` 给每条 **live** 记录算的 `(session_id, step, epoch)`：

- live 由构造保证——回填之后才读到的字节才会进 `_on_parsed_record`，历史记录到不了
  这里，所以「拿到身份」等于「接上之后真的发生了一次收尾」，不重播历史；
- 同一回合只提醒一次：身份进有界记忆（每 Agent 64 条），重复帧/多文件各写一份直接返回；
- 连续回合不误判：新回合必有 live `turn/start`（epoch+1）；
- 分工：完整的 `busy→success` 仍由既有边沿先排定，身份通道只收口边沿看不到的来向，
  且**看到 pending 就不动它**——两个通道不抢同一个提醒。

**提醒承载与事件摄入（G2 批）：按身份收口，不要按早期台账读成"未决"**。采集时点的实现是：

- **事件去重按"信号发出身份"**（`EventIdentityLedger` 的 `note` / `_is_duplicate_delivery` /
  `_retire_on_signal_loss` + `read_new_lines_with_cursors` 带游标），**不是**只靠一个时间冷却窗；
  冷却窗仍在，但它做的是去抖，不是唯一判据；
- **交互身份键 = 来源 + kind + 会话 + 命名空间/值**（`_interaction_key` / `_session_matches` /
  `_resolve_matching_interaction`，多候选**拒歧义**而不是猜一个），因此"三来源两会话撞同一
  rpcId"不会互相关闭对方；
- **承载者迁移时提醒跟着走**：`_settle_alert_bubble` / `_sync_alert_copy` / `_resume_alert_copy` /
  `_alert_remaining_ms` / `_note_alert_presented` 这一族保证同 ID、剩余 TTL 继承、主位回来不抢回、
  不重发不重出声——所以"slot0 退出后提醒不跟随子宠"是**修复前**的表现；
- 证据：`tests/test_g2_alert_lifecycle.py`（14）、`tests/test_g2_event_delivery.py`（15）、
  `tests/test_g2_handoff_and_repeat.py`（10）、`tests/test_interaction_identity_ambiguity.py`（21），
  以及 **该轮已有的两票独立代码审查**（结论与修补都已落到专项报告里）。
  仍未决的是**发布层**证据（新包 / GUI / 三端），不是上述语义本身。

**档案写入三件事**：目录级短时写锁（跨进程）、代次令牌（旧代次写入被拒）、
每张表单独立全局内存（避免共享 `_main` 草稿互相污染）。`SlotRoutedConfig` 是路由中枢：
子宠页的 per-slot 键落槽档案、全局键落主配置，两边共用同一份锁与同一套 reset 侧车。
"保存失败"被分成**类别**而不是一句话——「这只桌宠已重新生成（上一代）」与
「磁盘写不进去」对用户是完全不同的处置，前者给"继续编辑 / 放弃并关闭"两个出口，
后者也必须有出口，否则窗口就永远关不掉。

**旧版菜单退役用三层守卫**：文件不存在 + 零退役符号 + 退役键只许出现在迁移函数里
（`test_architecture.py`）。配置键 `context_menu_template` 走静默迁移（读旧值 → 记一次
info → 丢弃，不报错、不回退、不写回），主配置与 slot 配置同一条路径。

**三端构建的同一口径**：PR 事件默认检出**合并提交**（`github.sha`），与分支 tip 不是
同一棵树；因此加 `workflow_dispatch` + `source_ref`，并把 resolved source SHA 与工具链
版本（`pip freeze` / Node 版本）写进 step summary，让"三端跑的是同一棵树"可证。
素材供给收敛到唯一入口 `prepare_frameseq_bundle.py`（先验证 → 缺才转 → 转完再验），
门同时装在 workflow 与本地构建脚本里——只装在 workflow 里的话，绕过 workflow 的构建
仍会打出缺帧序列的静默降级包。

## 四、性能分析

**方法（可复现）**：`python .scratch/product-perf-20261010/run_matrix.py`（矩阵编排）→
`perf_driver.py`（进程外整树采样 + 相位驱动）→ `perf_child.py`（被测子进程：探针启动器，
产品侧零 hook、零 env 判定分支，先起采样线程再 `from pet.app import main`）；真
`AppShell` / `OverlayShell`（`PET_RENDER_TOPOLOGY=overlay`）、**真窗口 on-screen**（明确从
环境剔除 `QT_QPA_PLATFORM`）、不打真实 API/chat/DSH。
环境：Windows / Python 3.13 / PySide6 / 本机 **16 逻辑核** / 素材 `shenshen` 106 段
（产品日志实证 `素材加载完成：shenshen 106 段动画`、首跑供给"新转 0 / 跳过 0"——测的是
预转素材热路径）。**12 次运行全部正常退出（exit=0），源码 hash 全程一致**：12 份
before/after manifest 只有一个唯一摘要 `e662111ac61156bb`；`pet/**/*.py` 合并 sha256
`40058b6fd8ceed1f3d643106752d9d4feb1fb50abb7a46bb49eb1b9cae0268f2`。
样本：宠数 1/3 × 岛指标 全关/CPU+MEM+GPU 开 × 相位 cold(0–20s)/steady(20–65s)/
hidden(65–110s)/restored(110–155s)，每格 3 轮。

| 指标 | 实测 | 归属（热路径 / 新增 / 既有） |
|---|---|---|
| 整树 CPU，单宠全关 → 三宠全关 | **32.4 → 70.7 core-%**（`cpu_core_pct`：100 = 占满 1 逻辑核，故整机占比 = 值 ÷ 16） | 既有热路径（解码 + 重绘）；**加宠边际 = +38.3 个百分点 = +0.383 核总增量 ÷ 2 只 = +0.19 核/只** |
| 整树 CPU 绝对值 | 三宠稳态 **≈0.71 核**（整机 4.4%）；单宠 **≈0.32 核**（整机 2.0%） | 既有；**实质性持续开销，不是"可忽略"** |
| tick 调度间隔 p50 | 全部 12 次 **6.00–6.04 ms** | 既有：这是 **tick 定时器的调度间隔**（产品日志 `标称=6ms`，随刷新率 ≈167 Hz），**不是素材解码帧率** |
| 有效 tick 率（按各相位原始时长折算 = 调用次数 ÷ 相位秒数） | `steady` **163.7–164.8 次/s**、`cold` **148.7–150.2 次/s**、`hidden` **典型 ≈3 次/s** | 既有；三宠全开 p95 **7.87 ms**、p99 **9.70 ms**（相对单宠全关 +0.69 / +1.19 ms） |
| 内存，单宠全关 → 三宠全关 | WS +11.2 MB（÷2 = **+5.6 MB/只**）、PrivateBytes +11.0 MB（÷2 = **+5.5 MB/只**）、主进程 USS +9.3 MB（÷2 = **+4.65 MB/只**） | 既有；**USS ≠ WS**，两者不得混用（本版已就地更正旧报告的算术错误） |
| 岛指标段（CPU+MEM+GPU 全开）的代价 | 主进程 **+1 线程、+23~25 句柄、+9.2 ~ +11.3 MB**（USS/WS） | **新增路径**；CPU 变化（+1.1 / −1.4 core-%）在轮间噪声内，**测不出**，不编造"零成本" |
| 隐藏桌宠 | 单宠 32.4 → **3.8 core-%**（−88%）；三宠 70.7 → **4.0 core-%**（−94%）；重绘帧 **→ 0**；有效 tick 率 → ≈3 次/s；恢复后回到 32.0 / 68.2 | 既有；**隐藏 ≠ 释放**：PrivateBytes 隐藏期不降（单宠 99.2 → 100.2 MB） |
| 稳态每帧渲染（岛） | 0.358 ms；软陶笔内缘高光 **+65 µs/帧**（唯一每帧新增） | 既有 + 新增各半（P2 报告） |
| 启动窗单发 GUI 停顿 | **95–133 ms，12/12 轮 cold 相位都有** | 既有；**如实登记为定量异常，未下"回归"结论**（无旧基线对照） |
| 一次 324 ms GUI 心跳间隔 | `pet3-metricsoff-r1` hidden 相位单发（该轮 p99 仅 11.9 ms） | 既有；如实登记 |
| `quiet_blocked` / `memory_trim` 判定等纯函数 | 0.384 µs / 0.42 µs / 单次 `_menu_open` 0.338 µs 量级 | 新增路径，事件级触发 |

**结论（逐条）**：

1. **稳态开销有没有变化**：本改动**没有绝对性能预算可判"通过"**——仓库从未锁定绝对
   预算（历史上只有 2026-09-24 自设的"单宠稳态 ≤200 MB"）。本版给出的是**当前源码态的
   自洽基线**，并明确 **三宠 ≈0.71 核属实质性持续开销**。
2. **新增路径的绝对成本与触发频率**：岛指标段整机代价 = +1 线程 +23~25 句柄
   +9.2~11.3 MB（**0 订阅即停**，隐藏期不采样）；告警/滞回/计划重算都是**样本拍与事件级**
   触发，不是每帧；软陶笔 +65 µs/帧是唯一的每帧新增。
3. **有没有引入新的系统调用 / 网络 / 磁盘 / 线程**：有，且都是**显式选择的**——
   网络延迟探测**只在用户打开网络段时**每 `network_probe_interval_seconds`（默认 1s，
   夹到 [0.5,60]）发一次合法 DNS 查询（单次往返网约 160 字节）；GPU 读数只在勾选后
   进共享采样线程；配置写锁是**短时**目录锁，不新增常驻线程；`memory_trim` 只在用户
   点菜单时启动后台 worker。**没有后台轮询式新增**。
4. **内存与缓存有没有增长**：加宠边际 WS +5.6 MB/只、USS +4.65 MB/只（当前树、受控
   配置、155 s）；岛指标段 +9.2~11.3 MB。历史 2026-09-24 报告的 +146.7 MB 均值是
   **打包态、修复前、用户真实 3 宠配置、200 s** 的口径（它自己写"≈80 MB/只"是约值，
   精确折算为 73.35 MB/只），**打包/版本/配置三重差异并存，不作因果断言**。
5. **没有前后可比证据**：本轮**未跑旧打包基线**（会破"正常 quit 收尾"纪律，且混着
   打包/版本/配置三重差异），所以本报告**不含任何"改进比例"，也不含"有无回归"的结论**。
6. **口径警告**：WS 会被 Windows 工作集修剪污染——`pet3-metricson-r3` 里隐藏→恢复把整树
   WS 从 181.7 MB 打到 66.2 MB，而同一时刻 PrivateBytes 纹丝不动（120.1 → 120.5 MB）。
   **结论口径以 PrivateBytes 为准，WS 只作参考。**
7. **不重测已过项**：同一棵树在同一 hash 下已经跑过完整性能矩阵；除非字节变化，
   不再重复（本报告采集时点后确有字节变化，见 §7）。

## 五、实机运行记录

本节只写**本机真实环境**跑过的东西（不是 CI、不是 mock）。每个结论都注明它对应
**哪个包/哪份源码**——包与源码都改过多次，混着说就是假证据。

### 5.1 新候选包的 GUI 增量实测（隔离环境，2026-10-11 03:22 → 03:34）

| 项 | 记录 |
|---|---|
| 被测包 | `dist-onedir/dsh-pet-standalone-webm-chat/`，exe sha256 **`0ddb5c0099545aca6487378cd5f960ac48335e919d79b1f88868d803e5a4f20e`**（与候选元数据一致；复制到临时目录后复验一致）；zip sha256 `169f1fed…3077c`（572825203 B / 546.3 MiB，未解压使用） |
| 隔离 | 新临时目录启动；`APPDATA`/`LOCALAPPDATA`/`TEMP`/`TEMp`/`USERPROFILE`/`HOMEDRIVE`/`HOMEPATH`/`DSH_HOME`/`XDG_CONFIG_HOME`/岛扩展目录全部指向本 scope 的 scratch；父进程等待式启动器。开工先查 **前台就是桌面端应用本身，无任何游戏进程**；用户真实桌宠 **PID 6812 全程未碰** |
| 上轮缺陷收口：三个出口 | 从主宠**真实右键菜单**开设置 →「桌宠」页把 `气泡文字大小` 100 → **140**（真草稿）→ 托盘把 slot0「退出这只」再「生成 / 恢复 slot0」（**代次 1→2**）→ 点「保存并退出」：<br>① 「继续编辑」= 框关、设置窗**保留**、控件仍 140、磁盘仍 100 ✅<br>② 在失败框上按 **Esc** = 与继续编辑同效 ✅<br>③ 「放弃未保存的改动并关闭」= 设置窗**真关闭**、设置进程退出、磁盘仍 100 ✅ |
| 重开新基线 | 重开设置读到 **100**（不是弃掉的 140）→ 改成 **130** →「保存并退出」**无失败框**、进程正常退出 → 磁盘 130 → 再重开读到 **130** ✅ |
| 子泡真实点击 | 设置页真实 UI 打开 `点击触发自言自语` 并保存（读回 True）→ 实移光标**逐点 hit-test**确认属本进程不透明像素才点（中心落在别处时脚本 abort 不点）→ 子身体出泡（hwnd 80481720，hit 校验 `pid=32572`）→ 实点该泡打开 **`QuickChatBubble`**（320×153，AX：`QLabel '快速对话'` + `×` + `发送`）✅ |
| 是否发网络请求 | **netstat 该 pid 无任何连接**；日志无 request/HTTP 行；动作期 IO `read +2.45 MB`，**低于空转 8s 基线 `read +5.47 MB`**（读的是素材），`write +805 B`（日志）⇒ **未发请求** ✅ |
| 同槽重建后重复 | 托盘重建 slot0（代次 2→3）→ 再执行一次：出泡 → 点泡 → 再次打开 `QuickChatBubble`（hwnd 8785772）✅ |
| 坏 slot0 fixture | 非法 JSON + `overlay-active-pets.json = {"version":2,"slots":[0]}`：启动日志 `slot0 档案不可信（target-corrupt），已跳过这只桌宠；原文件保留未改：<路径>`；**坏档案 sha256 前后一致**（`df88e283…673a`）⇒ 不覆盖、不清源 ✅；托盘出现诊断入口 **`生成 / 恢复 slot0（档案损坏，见日志）`** ✅ |
| 修好后免重启恢复 | 不重启，直接点该诊断入口 → 日志 `子肥鱼 slot 配置有变更` / `素材加载完成：shenshen 106 段动画` / **`已生成子肥鱼 (slot=0)`** ⇒ **原地恢复成功** ✅ |
| 正常退出与重启 | 托盘「退出」→ 日志 `会话结束闸门已置位` / `about_to_quit` / `进入静默退出` ✅；重启（新 pid）→ `素材加载完成：shenshen 106 段动画` ×2、`新转 0` ×3 行、`overlay-active-pets.json` 仍 `[0,1]` ✅；设置保留（`bubble_text_scale=130`、`click_self_talk=True`）✅ |
| 收尾 | 本轮我方实例（pid 32572 / 20988 / 30668 / 设置进程）**全部正常退出、无残留**；未用 taskkill、未强杀、未按名字杀进程；用户 6812 未受影响 |

### 5.2 本机**不可达 / 未能观测**的项（如实登记，不用沉默代替结论）

| 项 | 现场证据 | 为什么不自动 |
|---|---|---|
| 「打开配置目录」按钮 | **本轮没有出现「桌宠恢复」窗**。探针定位到设计上的托盘门：`overlay_shell._ensure_recovery_entry(force=False)` 里 `if not force and QSystemTrayIcon.isSystemTrayAvailable(): return`——**托盘可用时不建恢复窗**；`force=True` 只在"托盘构造失败"或"生成失败且提示上不了屏"时才走。本次启动路径只落了 `WARNING … 无法上屏（无可见桌宠/托盘）`（该句只写日志，不建窗） | 本机托盘可用 ⇒ 走不到该分支。**没有为了复现它去停/杀 explorer 或托盘**（越界）。要覆盖这条路径需要"无托盘"环境或产品提供非托盘入口 |
| 启动诊断文案口径（**已收口，非欠项**） | 上轮包 `0ddb5c00` 上实测到：启动诊断写「修好该文件后**重启**即可恢复」，而实测**免重启**即可原地恢复（同链路气泡文案写着"可用托盘/恢复窗的「生成 / 恢复 slot0」再试"） | 采集时点的工作树已**按拓扑分流**该文案（overlay → 「生成 / 恢复 slot0」即可恢复（重启同样有效）；legacy → 重启），见 §7.4；该分流与其属同一增量，**不在 `0ddb5c00` 里**，所以本行只描述那个包，不代表当前树 |
| 单宠状态没有"关闭这只"入口（已修，但不在被测包里） | 新装（active 只有 slot0）实测：宠物右键菜单 19 项无 `退出这只`；托盘菜单为 `显示/隐藏｜回到右下角｜生小肥鱼｜退出子肥鱼｜桌宠设置｜鼠标穿透｜开机自启｜退出`，也没有逐只关闭项；只有 ≥2 只时托盘才出现逐只子菜单 | 这是**上轮包的真实观测**，已由本轮最小修（托盘 `if entries:` ≥1 只即挂逐只菜单）收口；**该增量不在 `0ddb5c00` 包里**（见 §7） |
| 图像目视 | 本轮执行环境**无图像输入能力**：所有结论来自 UIA(AX) 树、Win32 hit-test、进程/IO/netstat、日志与 hash，**不是目视** | 需要目视的截图应由具备图像输入的会话按 `pid/hwnd` 直抓；本轮实例已全部正常退出，无遗留窗口 |
| 真实聊天 | **按指令不做网络交互**，只验证"打开输入面且不发请求" | 网络交互会打到真实服务 |

### 5.3 更早的包/源码实测（保留，但**不代表当前包**）

| 时点 | 包 / 源码 | 实测内容 |
|---|---|---|
| 2026-10-10 | 候选包 exe `a422be50…` | 真实启动、106 段新转 0；设置页 UIA 定位到「桌面组件」，GPU/CPU/MEM 数值随动；主代理对该窗口截图目视确认时间/读数/状态点在胶囊内（非仅 OCR）。**用户处于全屏游戏 + 隐藏光标，测试宠自动穿透、禁止点击落游戏**，故多宠菜单/主关闭/托盘正常退出当时未验 |
| 2026-10-10 | 候选包 exe `58161b57…` | 多宠：关 0 不升 → 补 0 → 生 3 → 正常托盘退出 → 重启 4 只恢复通过；双 reset / 全局捕获开关 / 106 新转 0 通过。**但打开设置再关、或重生 slot0 使旧表单代次过期时，保存被正确拒却无丢弃出口、窗口永久关不掉（2/2 真复现）**——该缺陷已在本轮 `0ddb5c00` 包里复验修复 |
| 2026-10-10 | 迁移夹具 | 4 类合成 fixture × 6 次包内迁移 97/97 通过（备份完整 / 不提升 / 幂等 / 坏态拒覆 / 新转 0）。**有效 fixture 在离屏环境没有正常 quit 入口，用自己的 PID 强停** ⇒ 不能算"正常退出"证据；另有一次坏配置弹出 PyInstaller 原生错误框约 19 s，属**正常错误反馈质量**待最终审查，不隐藏 |

### 5.4 性能实测的实机属性

§四 的 12 次运行是**本机真实 GUI 窗口**（真 `AppShell`/`OverlayShell`、on-screen、真实
素材），不是 CI、不是 offscreen。隔离见 §四「方法」。**12/12 exit=0，源码 hash 全程一致。**

## 六、测试与验证

### 6.1 已验（有机器可查的退出码/计数）

| 门 | 命令 | 结果（时点与归属） |
|---|---|---|
| **同树完整机器门** | 主套件 + decode fanout + node 桥 + verify_import + ruff + diffcheck（脚本 `run_main.sh` / `run_gates.sh`） | **6312 passed / 13 skipped / 0 failed（941.61 s）+ fanout 30 passed（4.68 s）= 6342 passed / 13 skipped / 0 failed**；8 个退出码全 0；558 文件 before/after **NO-DRIFT**；source digest `1ea59288c91afcc4f9ca1d57511a655f4956ed53bfea6dfd00d1d0ec91e224cf`；完成时间 **2026-10-11T02:55:49+08:00**。⚠️ **该结果早于本轮的 CI 接线 / 单宠关闭入口 / DSH 中途挂载三批新增，不得当作当前全量的通过结论** |
| 静态检查 | `python -m ruff check pet/ tests/` | All checks passed（rc=0） |
| 空白/冲突标记 | `git diff --check`（含 `--cached`） | rc=0 |
| 架构红线 | `tests/test_architecture.py` | 内含退役守卫（文件不存在 / 零退役符号 / 退役键只许出现在迁移函数），逐批复跑通过 |
| DSH 中途挂载批 | `pytest tests/test_dsh_mid_attach_done.py tests/test_dsh_state.py` + 相关集 | 相关 **407 passed / 1 skipped**；独立复核该两文件 **50 passed / exit 0 / 36.46 s** |
| 单宠关闭入口批 | 相关 277 + 202；单宠关闭 + 设置路由 + frameseq 门相关集 | **104 passed / exit 0 / 8.08 s** |
| 三端 CI 最小闭环 | `pytest tests/test_ci_workflows.py tests/test_frameseq_bundle_gate.py`（实现前红：31 failed / 11 passed + collection error） | 实现后 42 + 58 passed；相关集 215 passed；再加 requested_regressions / fix_bridge_bundle / voice_chime_service = **481 passed / 1 skipped**；`bash -n` 两个构建脚本 syntax OK；`prepare_frameseq_bundle.py --print-cache-key` 两次一致（0.57 s）；真素材 `check_frameseq_bundle.py` **106 个 clip PASS**；`convert_frameseq.py --character shenshen --include random,events` = **新转 0 / 跳过 106 / 失败 0**（没有重转 379 MiB） |
| 先前一轮完整机器门 | 同结构 | 6262 + 30 = **6292 passed / 13 skipped / 0 failed**（较早，已被上表取代） |
| GUI 实机 | 见 §5.1 | 失败出口三条路径、子泡点击、坏档案、正常退出/重启全部实测通过 |
| 本报告自身 | `pytest tests/test_pr_report_discipline.py`、设置文案 lint、`test_product_copy_has_no_external_brand_reference`、本报告链接自检、`git diff --check` | 见 §6.3 |

### 6.2 未验（本报告不把下列任何一项当已通过）

| 未验项 | 现状 |
|---|---|
| **macOS / Linux 真机** | **从未跑过本候选**。当前只在 Windows 上跑过；三端 CI 的接线已落盘并本地静态验证，但**没有 runner 就没有"三端通过"**，也不拿 Windows 模拟、WSL 或 offscreen 单机套件充三端 |
| **新版 Windows 安装包** | 未构建。当前的 `0ddb5c00` 包**不含**本轮新增的单宠关闭入口与最新 DSH 修复 |
| **安装器（Inno setup）** | **未构建**。本机缺 Inno 编译器（9 处 PATH / 常规安装 / registry 只读探测均无 compiler）；副本里把 `x64compatible` 降为 `x64` 编出的 setup 是**仅 x64 测试产物、非等价、不能作通用发布包** |
| OBS 相关 | 新版包下的 OBS 场景、**长时间掉源**、自动隐藏诊断仍欠 |
| foobar2000 端到端 | 本机**未安装** foobar2000（注册表 + 进程 + 深度 3 扫描三项探针全空）⇒ foobar 取词路径**无法端到端实机复现**，窗口标题源的解析只用录制的格式串样本验证 |
| 多屏真机 | 多屏弹射/落位只在假屏与快照层验证；真实多显示器人工验收未做 |
| 平台 skip 项 | 各平台分支的跳过项（symlink 权限等）如实保留，未逐个在目标 OS 复跑 |
| 在线更新 / 覆盖安装 | 未做（只做了配置迁移的合成夹具） |
| 独立审查第三票 | **双独立审查**已逐项收口（结论与修补都已落到本报告引用的批次报告里）；**第三票（只读交叉审查）尚未返回结论**，不预记、不当作已过 |
| 发布前同 SHA 门与部署 | 未做（见 §7） |

### 6.3 本报告自身的验证（已跑，结果如下）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python -m pytest -q tests/test_pr_report_discipline.py tests/test_settings_copy_lint.py "tests/test_desktop_pet_features.py::test_product_copy_has_no_external_brand_reference"` | **121 passed**（3.5–9 秒级）。覆盖：本报告标题逐字含「修改文件说明 / 性能分析 / 实机运行记录」三节、已在 `docs/INDEX.md` 登记、设置页文案「黑话」lint、产品文案无外部品牌引用 |
| 2 | `python .scratch/product-delivery-report-20261011/check_report_links.py` | **LINK CHECK OK**（本报告 + 它在 `docs/INDEX.md` 的那一行，全部相对链接均可解析；绝对链接不检查，离线不发网络请求） |
| 3 | `git diff --check`（含 `--cached`） | rc=**0**（无空白/冲突标记问题） |
| 4 | 逐文件覆盖自检（脚本断言） | 本报告正文**逐条提到了全部 298 个产品文件**（含 37 个未跟踪文件与 6 个被删除文件），无遗漏 |

**没有做、也刻意不做的**：不重跑全量测试套件（本轮是文档批次，§6.1 的机器门与各专项
聚焦结果已在本报告内；再跑一次同树的完整门收益为零且会与其它工作争资源）；不顺手修复
历史报告里的失效链接（避免把无关历史文档拖进本 PR 的 diff）。

## 七、未完发布条件

**本版仍不能宣布"可发布"。** 下列条件未满足之前，任何"全产品已过 / 三端全过"的说法
都是错的。

### 7.1 硬阻塞（不做完就不能发）

| # | 条件 | 现状与理由 |
|---|---|---|
| 1 | **三端各自真实跑一遍本候选** | 三端 runner 必须先把本候选 SHA 推到**隔离的验证分支**才能跑；远端授权尚未得到人工答复，因此**不能推、不能 dispatch**。本地 mac/Linux runner 也没有 |
| 2 | **构建包含本轮全部增量的新 Windows 包** | 现候选 `0ddb5c00` 早于单宠关闭入口与最新 DSH 中途挂载修复；包与源码必须同 SHA |
| 3 | **合格的安装器** | 缺 Inno 工具链（见 §6.2）。降级平台编出的 setup 不是合格发布包 |
| 4 | **发布前同 SHA 门 + 部署** | 未做。`#233` 之后的整棵树需要在同一 SHA 上重跑一次完整机器门（本报告 §6.1 那一轮不覆盖后三批新增），再走部署与回滚演练 |

### 7.2 实机欠项（可以并行推进，但不能算已验）

OBS 新版包场景 / 长时间掉源 / 自动隐藏诊断；foobar2000 真机；多屏真机；
平台 skip 项复跑；在线更新与覆盖安装；坏 slot0"打开配置目录"入口（需要无托盘环境）。

### 7.3 GitHub 核真：8 个开放 PR + 13 个开放 issue 的**分类**（只读，未外发）

本轮只做**只读**核真（`gh` 查询、本地探针、静态读 diff），**未评论、未 merge、未关闭、
未 push**。结论是**适用性分类**，**不等于"全部已修/已合/可关闭"**。

| 对象 | 判定 | 处置 |
|---|---|---|
| issue #234（回合成功结束不弹完成提醒） | **本版已解决**（独立等价实现且更强，另多 4 条来向通路，早于对应 PR 最终 head 约 10.5h） | 不为它合并上游 PR #235 |
| PR #235 | 只剩一条残留：中途挂载回合的 `turn/end` 静默；其余条目与本版契约相反或已等价存在 | 整段不采纳；残留那一条已由本版 §三 的身份判据收口 |
| PR #237（"合并主线 + 6 项兼容改动"） | **不要整合**。本地探针实测：其 `app.py` 传 `dsh_tracker` → `TypeError`；其 `dsh_state.py` emit 两个**不存在**的 Signal ⇒ 每条 `turn/end` / `assistant/message` 会被 `_poll` 的 per-line except 静默吞掉（采纳即真崩） | 不采纳。**注意其自述与实际 diff 不一致**（自述 6 项/5 个测试文件/8 个 GIF，实际另含两处接线、1 个测试文件、9 个 GIF）——按"说明与 diff 不符"记录，不对作者作任何定性 |
| PR #236（自定义联动示例） | 协议面可用（读方实测 8 项 7 PASS）；示例自身 3 处缺陷：`%APPDATA%` 环境变量不展开（与 `Path.expanduser` 不是同一个文件）、轮转责任写反（属写方）、相对链接少一层 | **改完再收**；不为了迎合示例去改产品 |
| issue #214（启动桌面端） | **本版已解决**：显式 `desktop` 源码已实现（真实探测 + 未装提示 + 非 Windows 诚实 unsupported + 菜单/托盘/自启入口齐）；`auto` 按用户决定 = 仅服务 | 回帖须讲清"须同时开联动"的口径；不改代码 |
| PR #229（macOS 窗口阴影） | 本版已有更宽的 mac 无阴影实现；**真实 mac 阴影验收仍缺** | 不直接合旧测试 |
| PR #211（测试基建 + 协作文档） | 测试修复已等价覆盖；文档约定、旧预算与复盘脚本与本版冲突 | 不整合 |
| PR #172（网络信息面板） | 网络面板能力本版已实现（岛指标走不同接口）；旧 PR 存在父窗与销毁收口风险 | 不整合 |
| PR #232（独立可选产品变体） | 属**独立产品变体**，不是本版一部分；签名兼容门与默认 overlay 判断与本版不兼容 | **不进本版** |
| issue #213（多屏弹射限制偏好） | 尚未实现的新偏好 | 不擅自加入本版 |
| issue #231（OBS 黑屏） | 本机 WGC 可用，与报告者场景不同 | 不能据本机结论直接关 |
| issue #228（foobar2000 歌词） | 已有接线但**未真实播放器验证**（本机未装） | 保留未验 |
| issue #216（余额副标题裁切） | 裁切已修；词语断行建议未处置 | 部分完成，如实标注 |
| issue #116（直播采集消失） | 缺复现信息；唯一"已解决"评论是**另一件事**（音效） | 不据此关整条 |
| issue #4（macOS 右键菜单） | 只有源码/模拟回归 | 待 mac 真机 |
| issue #220 / #219 / #221 / #191 | 已有实现（#221 的点位诉求与多列方案差异保留；#191 捕获相关未定） | 已实现部分不再重复 |
| issue #225（新执行器支持） | **新增 feature 请求，不算 bug**；另一侧证据不足 | 不承诺支持、不安装该工具 |

### 7.4 本报告写作时核对的口径项

- **坏 slot0 的恢复指引不再欠**：采集时点的工作树里，`pet/app.py::_mark_slot0_profile_unusable`
  已**按当前拓扑分流**（实测两串：overlay 拓扑 → `修好后点托盘 / 恢复窗的「生成 / 恢复 slot0」即可恢复（重启同样有效）。`；legacy 拓扑 → `修好该文件后重启即可恢复。`），
  两拓扑共用一句"重启"的旧口径已不存在。该分流属「单宠关闭入口」同一增量，
  **不在被测包 `0ddb5c00` 里**——§5.2 那条是对**那个包**的观察，不代表当前树。
- 仍然欠的只有「打开配置目录」按钮的**可达性**（托盘可用时不建恢复窗，需要无托盘环境才能实测），见 §7.2。
- 历史失效链接不顺手全改（避免把无关历史报告拖进本 PR 的 diff）。

## 八、迁移与回滚

### 8.1 配置键

**新增（16 个，都有归一化与默认值）**：
`island_metrics`（有序列表，未知 id 丢弃）、`network_probe_interval_seconds`（夹 [0.5,60]）、
`network_info_menu_enabled`、`weather_enabled`、`weather_city`、`weather_city_list`、
`weather_city_codes`、`quiet_minutes_default`、`quiet_also_on_fullscreen`、
`mem_skip_foreground`、`mem_min_size_mb`、`anim_menu_stay_open`、`drop_gravity`、
`foobar_lyrics_enabled`、`foobar_title_format`、`harness_autostart`（取值域扩展为
`auto` / `service`）。

**语义变更（1 个）**：`island_network_enabled` 从"真值来源"降级为**单向迁移源**——
归一化阶段判真则把 `network` 追加进 `island_metrics` 并把自己置回 `False`；键名保留只为
降级读取不炸档。加载与 `set()` 两条路径都会跑归一化。

**退役（1 个）**：`context_menu_template` 整键退役，`_migrate_menu_template_config` 读旧值 →
记一次 info → 丢弃（不报错、不回退、不写回）；主配置与 slot 配置同一路径；守卫测试断言
该键字面量只许出现在迁移函数里。

**默认值口径**：`island_metrics` 默认空 = 升级用户不会突然多出指标段；
网络探测默认关（要花流量必须用户显式开启）；`weather_enabled` 默认开、
`weather_city` 默认空（**不猜城市**）；foobar 两键默认关。

### 8.2 落盘状态

- **活跃成员** `overlay-active-pets.json`（`{"version":2,"slots":[...]}`）：只在**显式用户
  生成/关闭**时写；启动与退出都不改写。坏文件在替换前先备份
  （`on_broken="backup-overwrite"`），写入失败会**可见上报**（不静默）。
- **槽档案** `config-slot-N.json` 与全局 `config.json`：写入共用目录级短时锁与档案代次；
  坏 slot0 只降级该槽（**不覆盖、不清源**，诊断里带完整路径），其它非 ok 状态仍中止启动。
- **设置会话目录** `sessions-<identity>/`：`slot-0` 身份不再算隔离后缀，升级后主宠历史
  会话名字不变。
- **写入通道收敛**：窗口位置/角色的落盘改走 `cfg.save_geometry(geometry, token)`——
  代次过期的写入被拒绝（无该方法的宿主仍走旧路径）。

### 8.3 回滚

- **代码回滚**：本版改动全部在 `git` 可撤销范围内——`git revert` 或直接丢弃未提交改动
  （采集时点有 37 个未跟踪文件 + 103 个已跟踪文件带未提交改动，回滚粒度可按域收）。
  被删除的 6 个文件（`pet/config_domains.py`、`pet/context_menus/legacy.py`、
  `pet/context_menus/menu_styles/legacy.py`、`pet/menu_templates/{legacy,modern}.json`、
  `tests/test_config_domains.py`）在 `revert` 后由 git 还原，无需手工补。
- **落盘残留（回滚后会出现、需人工确认的部分）**：
  1. `config.json` 里会留下本版写入的新键与已迁移的 `island_metrics`；`context_menu_template`
     已被丢弃，**不会**自动回到旧值（旧版会按自己的默认值处理菜单，不需要该键）。
  2. `island_network_enabled` 可能已被置回 `False` 且 `network` 成员已进 `island_metrics`——
     旧版不认该列表键。
  3. `overlay-active-pets.json` 与 `config-slot-N.json` 可能已按新的身份/几何写入方式落盘。
  这些残留是**数据**而不是开关：清掉它们等于回到出厂状态，**不要在没有备份的情况下手工清理**。
  **本报告不把"旧版读新数据一定无损"列为已验结论**——需要时按 §8.2 的备份路径先备份再验证。
- **回滚验证**：回滚后必须复跑 `tests/test_architecture.py`（退役守卫）与配置族
  （`test_config_schema.py` / `test_config_reload_null.py`），确认旧实现下这两个族仍绿。

## 九、下一版范围（**不在本报告内**）

用户已明确：作者的另一条 DLC 分支作为**下一版独立工作区**处理，另建分支评估，**不混入本版
PR**。该分支的远端地址与 SHA 只记录在本地交接文件里（`docs/` 属对外文案扫描面，
品牌与远端地址不得写进 `docs/`）。本报告、本 PR、本版验收**都不包含 DLC 任何内容**；
本版收口完成后再另立。

## 十、证据索引（**本地原始证据位置，不随 PR 交付**）

下面全部在 `.scratch/`（被 `.gitignore` 忽略），**不会进入仓库、PR 读者看不到**，
列在这里只为"这些数字当时到底存在哪里"可追溯；读者要复核请按 §0.1 的命令在本机重跑。

```
.scratch/product-delivery-report-20261011/     本报告的数量与符号采集脚本 + 导出
                                                （collect_file_inventory.py / collect_change_details.py /
                                                  inventory.json / inventory.tsv / stats.json /
                                                  change-details.tsv / raw-*.tsv|txt）
.scratch/product-close-approved-machine-gate-20261011/   §6.1 的完整机器门（GATES_DONE.json + logs/）
.scratch/product-close-approved-gui-20261011/            §5.1 的 GUI 实测（REPORT.md + logs/ + json/ + 工具脚本）
.scratch/product-perf-20261010/                          §4 的性能矩阵（REPORT + runs/ 原始 csv）
.scratch/product-dsh-midattach-fix-20261011/             DSH 中途挂载两轮证据
.scratch/product-three-platform-gates-20261011/          三端 CI 接线与真素材命令输出
.scratch/product-single-close-entry-20261011/            单宠关闭入口批证据
.scratch/product-gh-triage-20261011/                     §7.3 的 GitHub 核真台账与独立抽验
.scratch/product-close-approved-candidate-20261011/      §5.1 被测包的候选元数据
.scratch/product-release-continuation-20261009/HANDOFF.md 本线的断点与授权边界
```

> 本报告**不得**被当作"发布批准"。它是：一份按三份证据纪律写成的、明确区分
> 已验 / 未验 / 未完条件的**待完成草稿**。

## 十一、追加轮次（**统计后增量**）：外部配置变更热应用实证

**本节定位**：只补两轮实证的摘要，**不回填** §0.1 的 298 文件统计（采集时点在前，口径见 §0.2），
本轮增量单列在 §11.2；两轮都**没有**跑全量 pytest、**没有**重新打包、**没有** GUI 目视、
**没有** git 提交，也没有读用户真实配置目录。

两轮的关系是**包态先发现、源码后收口**：

1. **包态合成输入验证**（被测包 exe sha256 `01f4b99f…`，取候选路径的 onedir 产物；喂的是按桥接
   writer 真实字段集构造的**合成 JSONL，不是真实 DSH 会话**）：六个场景按设计反应（§11.3），
   同时留下一处范围外观察——overlay 拓扑下外部改 `config.json` 的 `agent_link.dsh` **不重应用**
   （磁盘已是 false、监视器照旧运行；legacy 生效）。当时**未定性**。
2. **源码侧根因 + 最小接线 + 新回归**：把上面那条观察定性为**真缺陷**，修在应用级接线一处，
   补 5 条回归（修前 4 failed / 1 passed，修后 5 passed）。根因与修复见 §11.4。

### 11.2 修改文件说明（统计后增量）

本表增删是**本批次自述**，与 §0.1 / §2 的「基线 → 采集时点」累计 diff **不是同一口径，不可相加**；
298 文件统计与 §2.6 的未跟踪清单都**不回填**（未跟踪由采集时点 37 → 现 39：本报告自身 + 下面这个测试文件）。

| 文件 | 本批增删 | 新增 | 改了什么 + 为什么（状态） |
|---|---|---|---|
| `pet/app.py` | +25 / −1（其中 1 行为改写） | 否 | `_apply_external_config_change` 的 overlay 分支补一行 `_sync_shared_optional_services()`（含 6 行说明注释）：overlay 下 `instances[].win` 恒为 None，逐窗 `refresh_pet_settings()` 链一次都不执行，而 `OverlayShell.refresh_settings()` 不含 agent_link / proactive，进程级共享子系统必须在**应用级**补一次；同函数的 agent_link 注释改写 2 行；新增私有方法 `_sync_shared_optional_services()`（与 legacy 的 `sync_optional_services` **同序**：proactive → agent_link）。写在 `if overlay_shell is not None` 内是刻意的：`_overlay_shell` 只在 overlay 分支被赋值，legacy 恒为 None ⇒ legacy 逐位不变、不可能二次应用。（未提交） |
| `tests/test_agent_settings_hot_reload.py` | +388（5 个用例） | **+new** | 新增回归：真 AppShell + 真 Config + 真 config watcher + 真共享子系统（真 `SharedSubsystems` / 真 `DshMonitor` 线程 / 真完成确认定时器），只把「起桌宠那一层」置空（合成窗 / 托盘 / 会话结束探测器 / 灵动岛 / 可选服务），口径与 `tests/test_background_service_gates.py` 一致。五个用例：① 外部写盘 → 共享读方停，且 agent_link / proactive **各恰好应用一次**、壳的 `refresh_settings` 仍被扇出；② 关闭立即退役在飞的完成确认，越过确认窗无气泡；③ 关→开不重启应用、复用同一监视器对象且代次前进、新代次真实收尾照常提醒；④ 自启策略不扩权（全程零 `launch_harness` 调用）；⑤ legacy 窗链照旧**恰好一次**（应用级不补第二次）。出机边界全部替身：探活整函数替换（**不建任何 socket**）、包管理器调用只记录、profile 目录指向临时空目录。（未提交，未跟踪） |

### 11.3 实机运行记录（两轮：包态 exe + 源码态探针）

**第一轮：包态合成输入六场景**（本机真实环境，独立隔离目录启动，未用 CI、未用 mock）。

| # | 场景 | 拓扑 | 结论 | 关键证据 |
|---|---|---|---|---|
| S1 | 完成成功 | overlay | 按设计 | 气泡窗口 OCR「DSH 已完成本轮任务。」+ `[DSH STATE] idle→thinking→working→success` + done 音效 ×1（成功收尾后约 800 ms，与确认窗一致） |
| S2 | 重复同 ID 帧 | overlay | 只算一次 | 重复帧与真新回合**同一次写入**；done 音效计数 1→2（仅 +1；若重复帧被处理会是 +2），气泡只有一条 |
| S3 | 中途挂载（开始回填） | overlay + legacy | 历史不重播 | 启动前预置的整段历史**零气泡 / 零音效 / 零状态日志**；第二次启动时文件里已有旧内容，同样成立 |
| S4 | `execution/failed` 后 `turn/end` | overlay + legacy | 不报成功 | 失败气泡 OCR「当前会话中，DSH 的工具执行失败。」；收敛器照旧 `working→success` 但 **done 音效计数不变**、无成功气泡 |
| S5 | 关监测期间在飞的完成确认 | legacy | 不冒泡 | 帧被读到（`idle→thinking`）→ 确认已排定（`thinking→success`）→ 停表时刻**早于**确认到期时刻 → 本应到期的确认无气泡、无音效 |
| S6 | 停 → 开换代 | legacy | 旧失败不污染新代 | 关闭退役本代簿记、重开为新一代基线；新代 live 收尾出「已完成本轮任务」气泡 + done ×1；同代新硬失败仍被抑制 |

两处需要写明的口径：

- **S5 / S6 为什么在 legacy 跑**：这两条都要靠「外部改动落到运行期」，而 overlay 下那条通道当时
  不生效（就是 §11.4 的缺陷）。legacy 用产品自身文档化的开发环境开关切换，**同一 exe、同一份代码、
  同一套监视器类**，只有呈现宿主不同，不是改代码。
- **这一轮的边界**：没有真实 DSH 会话（无真实上游事件，也没有启动或接触真实 DSH 进程）；
  把联动「开启」的 UI 路径必然要走桥接安装（会执行包管理器），属禁用动作，全程**未触发**，
  关停通道用的是配置重应用；**图像目视未做**（该执行侧无图像输入，结论来自窗口 OCR、窗口列表、
  进程与 IO 计数、日志与哈希），需要目视的截图应由具备图像输入的会话另行抓取。两个实例都走
  **正常退出路径**（未强杀）；用户真实桌宠全程未碰、未按名杀进程。

**隔离偏差（如实登记，且不升级为真实联动证据）**：假端口监听器有一次按默认时长上限被杀，
留下约 20 s 空档。这段里探活回退到用户真实本机 DSH web 服务的端口，产生约 5 次「回环连接后
立即关闭、**零字节**」的探测；当时**没有**任何合成帧输入、**没有** `offline` 状态迁移、未发送
任何数据、未建会话、未冒名、未接受任何外部连接，也未影响任何测试数据。它只说明本轮的实验隔离
有一处缺口（一次后台任务未续期），**不得**被读成「真实 DSH 链路可用」，也不能用来给「有没有连过
那个真实端口」下结论（毫秒级回环连接不在采样窗口内）。

**第二轮：源码态探针**（真 `AppShell` 实跑，只替掉出机边界）：

```
前置：监视器 running = True / 代次 1；overlay 壳 = Stub，instances[].win = None
应用链触发次数 = 1          <- 去抖回调确实跑了
磁盘配置 dsh = False         <- 磁盘确实变了
应用后：监视器 running = True  <- 读方没停（缺陷）
越过确认窗后仍出现「已完成本轮任务」气泡  <- 关掉后仍弹
```

同类误判已排除：**不是** watcher 没触发，**不是**去抖窗口太长，**不是**磁盘没变。

### 11.4 缺陷与最小修复（源码，未进包）

| 项 | 内容 |
|---|---|
| 现象 | overlay 拓扑下外部（独立设置进程保存 / 手改 `config.json`）把 `agent_link.dsh` 改成 false：磁盘已变，监视器照旧运行、无停止日志；同一操作在 legacy 下生效 |
| 根因 | 外部配置变更的唯一应用入口 `_apply_external_config_change`：legacy 逐窗 `refresh_pet_settings()` 走到链尾 `sync_optional_services → manager.apply_config()`；overlay 下 `instances[].win` **恒为 None**，循环体一次都不执行，而 `OverlayShell.refresh_settings()` 只做窗口能力 / self_talk / 气泡样式 / 音乐。overlay 下能落到 `apply_config()` 的路径只剩进程启动与菜单开关，后者必然走桥接安装（禁用动作）⇒ 外部写盘在 overlay 下**完全落空** |
| 修复 | overlay 分支按**同序**补一次共享子系统 apply（proactive → agent_link）；legacy 仍由窗链负责，不补第二次。改一处、删零处 |
| 修复前后 | 探针：修前读方不停、关掉后仍弹完成提醒；新回归修前 **4 failed / 1 passed**（全部卡在「外部写盘后读方停表」），修后 **5 passed** |

### 11.5 性能分析（本批次**未重新计时**）

- **路径归属**：新增的是一次同步函数调用，只在 overlay 拓扑的**外部配置变更**路径上（设置保存 /
  watcher 去抖回调），**不在每帧、每 tick 路径**上；触发频率与人保存设置的频率同频。
- **新增系统调用 / 网络 / 磁盘 / 线程**：**无**。不建线程、不开 socket、不落盘；`apply_config`
  只在功能门发生翻转时才启停监视器——那本来就是该发生的那个启停。
- **本批次没有做任何计时**，因此本节**不写耗时数字**，也不写「可忽略 / 更快 / 省性能」这类
  形容词。专项报告里出现的「约 0.4 s」是测试等待时长（含去抖窗口），**不是性能测量**，
  不得当数字引用。要数字就必须单独跑一次计时，属待补项（§11.7）。

### 11.6 测试与验证（本轮，**非全量**）

| 门 | 命令 | 结果 |
|---|---|---|
| 新回归（先红后绿） | `pytest -q tests/test_agent_settings_hot_reload.py` | 修前 **4 failed / 1 passed**（日志 `red-before-fix.txt`）→ 修后 **5 passed** |
| 相关族（两族） | settings / single_process / background / harness / feature_gating 族 与 agent_link / dsh / overlay_shell / 回归族 | **153 passed**；**444 passed / 2 skipped** |
| 邻域族一次跑（95 个文件，非全量） | `pytest -q` 于 settings / overlay / app / agent / background / harness / config / dsh / proactive / single_process / feature_gating 族 | **1497 passed / 1 skipped**（413.93 s，exit 0） |
| 静态与空白 | `ruff check pet/app.py tests/test_agent_settings_hot_reload.py`；`git diff --check` | All checks passed；仅 CRLF 提示，无空白错误 |
| 本报告自身 | `pytest -q tests/test_pr_report_discipline.py tests/test_settings_copy_lint.py tests/test_desktop_pet_features.py::test_product_copy_has_no_external_brand_reference`；`python .scratch/product-delivery-report-20261011/check_report_links.py`；`git diff --check` | 本节写入**前后各一次**：两次均 **121 passed**（5.74 s / 5.05 s）；`LINK CHECK OK`（本报告 + 它在 `INDEX.md` 的登记行，相对链接全部可解析）；`git diff --check` rc=0（仅 CRLF 提示）。⚠️ 本报告与状态台账都仍是**未跟踪文件**，`git diff --check` 看不到它们 —— 因此另用脚本查过本节与状态台账新增行的行尾空白，**0 处**。日志：`.scratch/product-doc-hotreload-20261011/` |

另有一组 **18 条**用例在本轮之外单独跑过并全通过；该数字来自协作会话记录、**未留日志**，
因此本节**不把它算作独立证据**。

### 11.7 不能声称 / 待补

1. **两份独立代码审查（针对本轮增量）此时并行进行、尚未返回结论** ⇒ 本节**不写 PASS**。
   此前 close 增量那两份只读审查的覆盖范围也**不含**本轮增量，不能代签。
2. **修复未进包**：被测包 `01f4b99f…` 不含本轮接线（§5.1 的 GUI 包 `0ddb5c00…` 同样不含），
   因此热更新修复**没有包态证据**；需要重新打包后复测（包与源码必须同 SHA，见 §7.1）。
3. **未跑全量**：本节所有测试数字都是聚焦 / 相关集；§6.1 那次完整机器门早于本轮增量 ⇒
   「当前树全量全绿」**不成立**。
4. **发布层未动**：三端 runner 的预推仍需人工许可，**未推、未 dispatch**；
   不写「已部署」「三端 PASS」。
5. **待完整 PR 收口时补齐**：本版 actual source hash、覆盖本轮增量的全量机器门、
   新包与合格安装器（同 §7.1）。
6. 本轮**没有**做性能计时（§11.5），**没有**做图像目视（§11.3），**没有**真实 DSH 会话；
   这些边界不隐藏。

新增证据位置（同样在 `.scratch/`，不随 PR 交付）：
`.scratch/product-release-dsh-input-20261011/`（包态六场景）、
`.scratch/product-agent-hot-reload-20261011/`（源码根因 + 探针 + 红前日志）、
`.scratch/product-doc-hotreload-20261011/`（本节文档纪律与品牌扫描的运行日志）。

> 本节不改变本报告的整体结论：仍是**待完成草稿**，不得当作发布批准（§十末条同样适用于本轮）。

## 十二、追加轮次（2026-10-12）：DSH 用户中止回合不再误报完成

- **问题**：DSH 减法后，用户中止的回合同样落 `turn/end`，桥接不区分原因，收敛器一律判 `success` →
  桌宠弹「已完成本轮任务」+ done 音效。
- **修复**：桥接 `integrations/dsh-pet-bridge/index.js` 在 `turn/end` 记录里透传短枚举 `reasonKind`
  （取自 DSH 的 `reason.kind`）；`pet/dsh_state.py` 把 `reasonKind == "aborted"` 收敛为 `IDLE`，
  且不产生回合完成身份；`pet/agent_link.py` `_on_dsh_converged_state` 新增 `idle`（来源 `turn/end`）分支：
  注入呈现管线回待机并撤掉本轮完成确认——否则 `_last_raw` 会停在 `thinking`，桌宠一直播忙碌动画、
  识屏一直把 DSH 当忙（ops5.5 审查发现）。
- **旧桥兼容**：无 `reasonKind` 的旧记录保持原 `SUCCESS` 行为；`decideTurnEndFailure` 未改。
- **已验**：`tests/test_dsh_state.py`（中止 → IDLE、无完成身份、旧桥 → SUCCESS）、
  `tests/test_bridge_hardfailure.js`、`tests/test_agent_link.py::...test_aborted_turn_returns_to_idle_without_done`
  （消融：删掉新分支即红）。**未验**：真实 DSH 桌面端中止一次回合的端到端。
- **astra 第三轮复审修正**：原分支不可达——收敛器 `_transition` 未带 `source`，且 AgentStatus idle 基线
  先到时同态去重吞掉中止。现 `handle_record` 对中止 `turn/end` 带 source 产出；已是 IDLE 时补产
  `idle→idle` 标记以撤掉基线排下的确认；呈现侧上一拍为 `success`（另一会话真实完成）时不撤确认。
  新增收敛器单测 2 条 + 经真 `DshMonitor._poll` 的端到端用例（两种到达顺序）；消融（删收敛器修复）
  3 条中止用例红，恢复后绿。另：`account_in_group` 命中后仍排空 234 续枚举再返回（防枚举句柄泄漏）。
- **astra 第四轮复审修正**：中止分支前移到锁存闸之前，并解除审批/问题锁存（锁存期间中止不再被吞）；
  `_done_cause` 记录待定完成确认的来源（`success` / `edge`），中止只撤 `edge` 来源的确认，
  重复中止也不会撤掉另一会话真实完成排下的确认。新增锁存中止单测与重复中止用例；
  `tests/test_dsh_state.py` + `tests/test_agent_link.py` 251 passed / 1 skipped。
- **astra 第五轮复审修正**：中止注入 idle 时跳过 `_on_agent_state` 的「该 agent 全部交互」兜底清理
  （`_idle_clear_scoped`），由 `_on_interaction_lifecycle` 按会话定向清理——会话 A 中止不再误撤会话 B
  仍在等待的审批/问题气泡；shutdown 补清 `_done_cause`。新增跨会话交互用例（消融即红）；
  两文件 252 passed / 1 skipped。
- **astra 第六轮复审**：中止分支本身判定已修复（同步注入、真 `_poll` 转发、按会话定向清理均核实）。
  残留一条**既有限制（非本版回归）**：多 DSH 实例并存时，桥接 `AgentStatus` 聚合记录不带实例/会话作用域
  （`integrations/dsh-pet-bridge/index.js` `aggregateWrite`），A 实例回 idle 会经 `_on_agent_state` 的
  全量兜底撤掉 B 实例仍在等待的交互气泡。该全量清理在 HEAD（`8dbae55`）中即已存在；修复需改桥接契约
  （聚合记录携带实例 id）并补双实例真 `_poll` 测试，登记为下一版事项，本版不改。
- **全量门（当前源码，含第三~六轮修正）**：`python -m pytest -q -p no:cacheprovider tests` →
  **6808 passed, 13 skipped**（17:28，日志 `.scratch/full-gate-20261012g.log`）。门 d/e/f 因启动后源码又改，作废不计。
- **ops5.5 产品审查**：裁决通过，无 blocker/major。已修 minor：桥接 `turnEndReasonKind` 挪出
  `decideTurnEndFailure` 注释与函数体之间；三处「一切 turn/end 收敛为 success」改为「非中止」；
  `_on_dsh_converged_state` docstring 补 idle 分支；unsupported 文案改「无法判定权限，点此尝试授权…」
  （按钮可点为有意设计：判不出时允许尝试）。未改：节流窗口内中止可能短暂停留忙碌动画（既有行为，未核实补发）。
  定向回归 `test_dsh_state/test_agent_link/test_fps_permission/settings` 327 passed / 1 skipped，
  `node tests/test_bridge_hardfailure.js` 12/12。门 g 之后这批改动以注释和一处文案为主，PR 前仍需在最终源码上再跑一遍全量门。

## 十三、最终候选（2026-10-12）：同源码全量门、包与本地部署

- **全量门 h**（ops5.5 minor 修正之后的最终源码，工作树 diff 指纹 `32a97a12`）：
  `python -m pytest -q -p no:cacheprovider tests` → **6808 passed, 13 skipped**。
- **Windows onedir 包**：`build_onedir` webm-chat 变体 EXIT=0；包内 DLL 链（Shiboken/QtCore/QtGui/QtWidgets）、
  exe 启动与 `--settings` 冒烟均通过；portable zip 546.8 MB。包与上述源码同一工作树构建，
  §7.1 #2「包早于增量」已解除。
- **本地部署**：旧 `_internal` / exe 已备份（`*.bak-localdeploy-20261012h`，可回滚）；部署后 exe 哈希与构建产物一致，
  `_internal` 逐文件无差异；实机启动后灵动岛正常渲染时钟、网速、延迟与占用指标。
- **仍未验（如实保留）**：§7.1 #1 三端 runner、#3 合格 Inno 安装器；§7.2 各实机欠项；真实 DSH 桌面端中止回合端到端；
  多 DSH 实例聚合作用域（下一版）。fable5-1 保底审查：本环境未提供该模型，未调用。

## 十四、CI 收口轮（2026-10-11）：跨平台判据收口与原生崩溃取证位

**本节定位**：PR243 三端 CI 首次跑红之后的一批**最小修复**，按三份证据纪律记账。
只追加本节；上文各节结论一律不变（尤其 §6.1 / §十三 的全量门仍只属于它们各自那份源码），
本节**不回填** §0.1 的 298 文件统计（口径见 §0.2）。

**状态：待完成。** §14.6 列出的收口门在本节写作时**仍在跑**（写作期间复查进度：21:51 → 75%、21:52 → 79%、21:53 → 86%），
因此本节**不写**全量通过数字，也不声称三端全绿、真实 FPS 已验或 GUI 已验。

三端首次跑红的形态（只读日志，不作修复结论）：

| runner | 退出 | 形态 | 证据 |
|---|---|---|---|
| windows-latest | 1 | 主套件原生崩溃（access violation），无 Python 断言栈 | `.scratch/ci243/114459265643.log` |
| ubuntu-latest | 134 | SIGABRT（core dumped），日志里**一行原生栈都没有** | `.scratch/ci243/114459265812.log`、`linux_full.log` |
| macos-latest | 1 | pytest `INTERNALERROR: cannot instantiate 'WindowsPath' on your system`（`nodes.py` → `Path(os.getcwd())`） | `.scratch/ci243/114459265845.log` |

崩溃取证与已排除项详见 `.scratch/ci243/WIN-LINUX-NATIVE-CRASH-FINDINGS-2026-10-11.md`
（该文件的结论是**根因未确证**，本轮交付的是诊断位，不是修复）。

### 14.1 修改文件说明（本节增量）

`git diff --numstat`（工作树 vs `HEAD = 2ae2c273930bc7e122a2283d4203745473525c55`）：
**11 个文件，`+263 / −10`**，其中产品实现只有 **1 个**文件（`pet/fps_monitor.py`）。

产品与 CI：

| 文件 | 增/删 | 改了什么 + 为什么 |
|---|---|---|
| `pet/fps_monitor.py` | +10 / −2 | `_blocked()` 的平台判据**只问注入的那一次**。改前 `platform_supported()`（默认取 `game_fps.platform_support`）之后又调 `game_fps.backend_state()`，后者**再查一次真实 `sys.platform`**，把"注入的能力可用"在非 Windows 宿主上静默压掉（本机是 Windows，这条分支天然通过 ⇒ 本机绿、CI 红）。现改成只查后端文件（`game_fps.backend_problem`，不碰平台），状态码与原因串逐字不变（§14.3 五组接线实测）。这是本批**唯一**产品运行态改动 |
| `tests/conftest.py` | +49 / −0 | 新增两处**崩溃取证位**，不改任何红绿判定：① 面包屑 `pytest-breadcrumb.txt` 逐阶段（`[start]`/`[setup]`/`[call]`/`[teardown]`）写盘、`buffering=1` 逐行 flush，进程被原生杀死也留得下"死在哪个用例的哪个阶段"；② `pytest_runtest_logreport` 里失败当刻把 `longrepr` 直写 `sys.__stderr__` —— `-q` 的失败详情本来攒到会话末尾才打，进程被杀死就全丢。开关 `DSPET_TEST_DIAG_DIR`，GH Actions 自动落 `$RUNNER_TEMP/dspet-pytest-diag/`，未开启时两个钩子第一行返回、不建文件不写一行；不碰 pytest 自己的 faulthandler、不装信号处理器 |
| `.github/workflows/pr-test.yml` | +13 / −0 | 主套件之后加 `if: failure()` 的 `Pytest crash diagnostics` 步骤，**只 `tail -n 30`** 面包屑（全量两万多行，绝不整篇进日志） |

测试（跨平台判据与确定输入）：

| 文件 | 增/删 | 改了什么 + 为什么 |
|---|---|---|
| `tests/test_cursor_visibility.py` | +25 / −5 | 三处 `monkeypatch.setattr(vision.sys, 'platform', …)` 与 `setattr('pet.window.os.name', 'nt')` 换成**模块命名空间垫片** `_ns_shim`（显式成员覆盖、其余转发真模块）。原写法看着像命名空间、改的其实是**全局** `os`/`sys` 模块，而 `pathlib` 的平台分派只看全局 `os.name` ⇒ 窗口期里 pytest 生成失败报告时抛 `NotImplementedError: cannot instantiate 'WindowsPath'`= 整场 INTERNALERROR，正是 mac runner 的死法 |
| `tests/test_updater.py` | +20 / −1 | 同上一族：`setattr(updater.os, "name", "nt")` → `setattr(updater, "os", _ns_shim(os, name="nt"))` |
| `tests/test_frameseq_provision.py` | +10 / −2 | 同上一族：`test_creation_flags_hide_ffmpeg_console_on_windows` 的全局 `os.name` 伪装换成 `fp.os` / `fp.subprocess` 两个模块级垫片（POSIX 的 `subprocess` 也没有那两个 Windows 常量）。这一例正是 mac 崩溃前已报告 1728 例处的 `order.txt:1792` |
| `tests/test_fps_monitor.py` | +45 / −0 | 两条新回归：① 注入能力为真 + 真实平台判据说"非 Windows" ⇒ 断言 `start() is True`、会话真起、段非 `unsupported`（**在 Windows 上改前也是红的**，所以它本身就是跨平台回归）；② 默认判据 + 无能力 ⇒ 不起会话/线程、不枚举目标、原因逐字等于平台那句 |
| `tests/test_game_fps_exit_teardown.py` | +7 / −0 | 修的是真缺陷、不是加 skip：该用例用**默认**闸门建段，非 Windows 上 `sync()` 会走 `_detach()` ⇒ `assert isinstance(slot.monitor, _Monitor)` 必然失败。建段前把 `gf.platform_support` 与 `gf.platform_problem` **两个视图一起钉**（只钉一个会造出"没能力却报有能力"的自相矛盾的替身世界）；未删改任何既有断言 |
| `tests/test_final_interaction_regressions.py` | +56 / −0 | 新增 `autouse` 夹具把 DSH 探活（真连 3080/19387/38080 + 全 miss 时枚举 OS 进程）钉成"在线"：本模块手动驱动 `_poll` 且都要"桥接记录被消费"，不钉就取决于**跑测试这台机器上有没有 DSH**（本机有 ⇒ 假绿；CI 没有 ⇒ 第 2 拍转 offline、`_on_parsed_record` 早退且 `dismiss_all_interactions()` 清空本地 pending ⇒ 一批断言红）。另加一条**离线口径**回归：用例体内把探活钉回真离线，断言离线收敛、屏上提醒被撤、pending 清空、离线期间记录不再进收敛器。只钉网络/OS 边界，产品探活行为一字不改 |
| `tests/test_interaction_identity_ambiguity.py` | +15 / −0 | 同一个共享夹具 + `from pet import harness_launcher`（该模块此前没导入它）。离线反向回归只在上一行那个模块保留一条，避免两处重复 |
| `tests/test_cleanup_mei_cache_cli.py` | +13 / −0 | `test_delete_removes_owned_and_keeps_unmarked` 在 POSIX 上必红：标记里写的是**当前** PID，跑测试时它当然活着，产品按"在用"保守跳过是**正确行为**（不是缺陷）。夹具改成先把标记 PID 改写成**一个已退出进程**的 PID（起一个立即退出的子进程取 PID），模拟"崩溃遗留"，让该用例真正测它要测的那条路径 |

**审查留档与工作树的差异（如实记录）**：`.scratch/ci243/staged-fixes/fps-platform-gate/` 的
`pet/fps_monitor.py` 与 `tests/test_fps_monitor.py` 与工作树**逐字节相同**；
`.scratch/ci243/staged-fixes/dsh-probe-tests/` 的两份副本与工作树**不同**（工作树是缩过的版本：
夹具 docstring 精简，且离线反向回归只落在 `test_final_interaction_regressions.py`），
记账以上表的 `git diff --numstat` 为准，staged 目录只作审查留档。

### 14.2 性能分析

**这是微基准，不是产品整树 CPU 测量，也不是真实 FPS 测量**：只测 `FpsMonitor._blocked()`
这一个同步判据调用本身的开销与它触发的边界。**全程不开启采集**——不调
`start()` / `subscribe()` / `configure()`，实测两个监视器 `running is False`、`_thread is None`、
订阅集合为空；整个基准运行窗口内 `socket.socket.connect` / `socket.create_connection` 调用 **0** 次、
`subprocess.Popen` **0** 次、线程数 1 → 1（无新增线程）。

命令与环境（样本量写在命令里）：

```
.scratch/venv311/Scripts/python.exe .scratch/ci243/fps_blocked_bench.py --rounds 5 --calls 10000
  → EXIT=0（2026-10-11T21:48:49+0800；脚本 + 机器可读结果：.scratch/ci243/fps_blocked_bench.py / .json / .out）
Python 3.11.15（与 CI 同档）· win32 · 16 逻辑核 · 本机**同时在跑**收口全量套件（§14.3）
```

**判据是默认接线，无 fake platform**：`platform_supported=None` ⇒ 真 `game_fps.platform_support()`
（实测 `True`）；`backend_path=None` ⇒ 真实随包路径
`resources/presentmon/PresentMon-2.6.0-x64.exe`（实测 `is_file() is True`）。
**对照**：`git show HEAD:pet/fps_monitor.py`（blob sha256 `31a540e1…`）加载成独立模块
`fps_monitor_baseline`；当前模块＝工作树 `pet/fps_monitor.py`（sha256 `706d720c…`），两者字节不同。

每轮 10000 次调用、共 5 轮；因机器同时有负载，HEAD 与 worktree **在同轮内相邻测、顺序逐轮对调**
（配对）。单位 µs：

| 轮 | HEAD mean | HEAD p50 | HEAD p90 | HEAD p99 | HEAD max | worktree mean | worktree p50 | worktree p90 | worktree p99 | worktree max |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 669.5 | 617.3 | 888.8 | 1539.6 | 22796.3 | 638.3 | 601.6 | 797.6 | 1216.5 | 10017.2 |
| 2 | 638.1 | 605.8 | 786.5 | 1149.4 | 17332.6 | 650.0 | 617.8 | 813.5 | 1162.3 | 2559.6 |
| 3 | 652.0 | 620.8 | 813.5 | 1177.6 | 10638.0 | 662.0 | 628.6 | 827.8 | 1233.9 | 20757.1 |
| 4 | 691.4 | 658.1 | 868.0 | 1289.9 | 14106.2 | 680.4 | 639.4 | 873.8 | 1383.3 | 5023.4 |
| 5 | 707.2 | 659.4 | 918.2 | 1462.4 | 8842.6 | 626.2 | 599.7 | 772.6 | 1115.6 | 2767.7 |
| 均值 | **671.6** | 605.8–659.4 | — | — | — | **651.4** | 599.7–639.4 | — | — | — |

- 逐轮配对差值（worktree − HEAD，mean）：−31.2 / +11.8 / +10.0 / −10.9 / −81.0 ⇒
  **均值 −20.2 µs，标准差 34.2 µs**（`|差值| < sigma`）。
- 空循环地板（同一 per-call 计时方式，只 `perf_counter` 与循环）：mean 0.104 µs、p50 0.1 µs
  ⇒ 计时仪器开销不是这几百微秒的来源。`max` 列的毫秒级尖刺是并发负载/调度抢占。
- **结论**：本次改动在 `_blocked()` 上**没有统计上可分辨的耗时差异**（它省下的两次平台判据
  查询被下面那个固定成本淹没）。省掉的部分本身有确定量级：`game_fps.platform_problem()` 实测
  mean **1.6 µs / 次**，而改动把每调用的它从 2 次减到 1 次 ⇒ 量级 **≤ 约 2 µs/次**。

`_blocked()` 的成本落在哪（同一台机器、每项独立 10000 次；两侧共用，故不构成差异来源）：

| 组成部分 | mean µs | p50 µs | 说明 |
|---|---|---|---|
| `game_fps.bundled_backend_path()` | 483.7 | 454.4 | 固定成本主体：`pathlib.Path(__file__).resolve()` 的 Windows 真实路径解析；两侧都调 |
| `game_fps.backend_problem(真实路径)` | 111.6 | 107.7 | 其中 `Path.is_file()` 实测 mean 100.1 µs |
| `game_fps.platform_problem()` | **1.6** | 1.5 | 改动把它从 2 次/调用减到 1 次 |
| 三者相加 ≈ 597 µs | — | — | 与上表实测 626–707 µs（含循环与计时开销）一致 |

**文件系统调用的归属（独立探针，1000 次/项，`os.stat`/`os.lstat` 挂在全局 `os` 上数、finally 还原）**：
`bundled_backend_path()` = 1 次 `os.stat`（`Path(__file__).resolve()`）、`Path.is_file(真实 exe)` = 1 次 `os.stat`、
`backend_problem(None)` = 2 次 `os.stat`（上面两者之和 = `_blocked()` 每次那 2 次）、
`backend_problem(真实路径)` = 1 次、**`platform_problem()` / `platform_support()` 各 0 次文件系统调用**、
`os.lstat` 全程 0 次。日志 `.scratch/ci243/fps_blocked_syscall_split.log`。

逐条回答三份证据纪律要求的问题（下表全部为**实测计数**，每批 2000 次调用；`os.stat` 从全局 `os` 上数、
`sys.platform` 与 `os.environ` 从 `game_fps` 模块命名空间垫片上数）：

| 每次 `_blocked()` | HEAD | worktree | 差值 |
|---|---|---|---|
| `sys.platform` 属性读取 | 4 | **2** | −2（纯进程内属性读取，非 syscall） |
| `os.environ` 读取 | 4 | **2** | −2（纯进程内 mapping 读取，非 syscall） |
| `sys._MEIPASS` 读取 | 1 | 1 | 0 |
| `os.stat`（文件系统） | 2 | 2 | 0（一次来自 `bundled_backend_path()` 里的 `Path.resolve()`，一次来自 `Path.is_file()`；两者在两侧完全相同） |

- **稳态开销**：`_blocked()` 只被 `snapshot()` 的降级路径、`subscribe()`、`_build_fallback()`、
  `_maybe_start_worker()` 调用（宿主按岛刷新率取 `snapshot()`；有快照时走 `self._snapshot` 提前返回，
  根本不进 `_blocked()`）。改动**没有**新增任何调用点。
- **新增路径成本与触发频率**：零新增路径——改的是既有路径内部少问一次平台判据。
- **新的系统调用 / 网络 / 磁盘 / 线程**：**无**。文件系统调用数不变（2 次/调用，两侧相同）；
  网络连接实测 0 次；子进程实测 0 次；线程数 1 → 1。磁盘读写只在 `is_file()` 的元数据查询上，
  与改前完全一致。
- **内存有无增长**：**无随调用次数的增长**。不装 tracemalloc 的独立探针：每个模块连续 6 个子轮 ×
  5000 次调用（累计到 30000 次），GC 后对象数 delta 恒定（HEAD 恒 −10、worktree 恒 +1，
  从 5000 次到 30000 次不漂移），进程 WorkingSet 与 Private 增量**恒为 0.0 KB**。
  tracemalloc 那条线出现过一个**测量层伪影**：某些子轮次 GC 后留存 ≈ 406 KB，来源是单次
  415088 B、`count=1` 的分配（`pathlib.py` 的 `sys.intern` 行），它在 HEAD 与 worktree
  **两侧、两种测量顺序下都出现过也都没出现过**（同一模块的相邻子轮从 406 KB 掉回 0.4 KB），
  空函数对照（同样 tracemalloc 节奏、不调 pathlib）从不出现 ⇒ 记为伪影，**不作为内存结论**。

### 14.3 实机运行记录（本机真实 Windows，非 CI、非 mock）

| # | 做了什么 | 命令 | 真实结果 |
|---|---|---|---|
| 1 | `FpsMonitor._blocked` 微基准（默认判据、真实随包 PresentMon 路径、HEAD 对照） | `.scratch/venv311/Scripts/python.exe .scratch/ci243/fps_blocked_bench.py --rounds 5 --calls 10000` | EXIT=**0**；数字见 §14.2；`running=false`、`socket=0`、`Popen=0`、线程 1→1 |
| 2 | 取值等价性（5 组接线，证明改动只减少一次平台查询、不改返回值） | `.scratch/venv311/Scripts/python.exe .scratch/ci243/fps_blocked_equivalence.py` | EXIT=**0**，`all_identical=true`：S1 默认接线（真平台判据+真实随包路径）⇒ 两侧 `("","")`、段状态同为 `unknown`；S2 注入缺失后端路径 ⇒ 两侧同为 `unsupported` + 逐字相同的原因串；S3 注入能力为假 ⇒ 两侧同为 `unsupported` + 同一句平台原因；S4 能力为真+缺失后端 ⇒ 同上；S5 能力为真+真实后端 ⇒ 两侧同为空。日志 `.scratch/ci243/fps_blocked_equivalence.log` / `.json` |
| 3 | 收口全量门（`final_prepush311`，与 `.github/workflows/pr-test.yml` 主套件同口径） | `python -m pytest -q --ignore=tests/test_webm_reader_lifecycle.py --ignore=tests/test_webm_clip_lifecycle.py --ignore=tests/test_webm_first_frame_lock.py --ignore=tests/test_low_priority_warm_interaction_yield.py` | **未结束，待补**（见 §14.6）。日志 `.scratch/ci243/final_prepush311_full.log`：21:36:39 起跑，写作期间复查进度 **21:51 → 75%、21:52 → 79%、21:53 → 86%**，进程仍在跑。**本节点不写通过、不写 passed 数字** |
| 4 | 文件系统调用归属（那 2 次 `os.stat` 从哪来） | `.scratch/venv311/Scripts/python.exe .scratch/ci243/fps_blocked_syscall_split.py` | EXIT=**0**：`bundled_backend_path()` 1 次 / `is_file()` 1 次 / `backend_problem(None)` 2 次 / `backend_problem(真实路径)` 1 次 / **`platform_problem()` 与 `platform_support()` 各 0 次** / `os.lstat` 0 次；`restored: True True`。日志 `.scratch/ci243/fps_blocked_syscall_split.log` |
| 5 | 前一轮同命令全量门（**只覆盖本批一部分**，仅作基线参考） | 同上 | `.scratch/ci243/prepush311_full.log` → **6735 passed, 18 skipped**（1035.87 s，21:29:42 结束）。按文件 mtime 核对：它覆盖本批的 `tests/conftest.py`（21:10:24）、workflow（21:10:00）与 `tests/test_frameseq_provision.py`（20:22:32），但**早于** `pet/fps_monitor.py`（21:30:47）与另外 7 个测试文件（21:30:52–21:35:00）⇒ **不覆盖本批全部改动**，**不能**当作本次收口的通过证据 |

**本机做不到、因此没有做的**（不用沉默代替结论）：

- 三端 runner：macOS / Linux 都没有真机，本批的跨平台结论来自 `.scratch/ci243/` 里的
  隔离沙箱与一次性子进程探针（真 `sys.platform='darwin'` 只在子进程的模块命名空间里构造过），
  **不是**三端真机、也**不是**三端 CI 已通过。
- 真实 FPS 读数与 ETW 会话：本机权限边界未变（未入 Performance Log Users 时不采集、不伪报 0），
  本批没有开启任何采集会话，因此**没有任何实测 FPS**。
- GUI 目视：本批全是测试/判据/CI 诊断位，没有起界面、没有截屏。

### 14.4 覆盖与不吸收（#239 / #240 / #241，精确口径）

上游三条开放 PR 的核真结论沿用 `.scratch/product-release-continuation-20261009/UPSTREAM-TRIAGE-20261011.md`
§3，本节给出**准确口径**，避免被读成"本版遗漏"：

- **#239（恢复默认设置入口，对应 issue #220）已覆盖**：本树 `pet/settings_reset_defaults.py` 是
  **双作用域 + slot 路由 + 位置相干预留 + 重置后关窗**，PR 只做单一作用域 ⇒ **不吸收**（吸收会造同一功能两份真值）。
- **#240（动作菜单点后不收起，对应 issue #221）已覆盖**：本树 `pet/context_menus/shared.py`
  的 `_populate_animation_category` 已对触发动作叶子设 `closeOnTrigger`，并多一层
  `anim_menu_stay_open` 偏好 ⇒ **不吸收**。
- **#241（低速松手重力下落，对应 issue #219）已有产品范围，不是遗漏**：本树 `drop_gravity`
  在 **overlay / sprite 路径**下已实现（`pet/pet_sprite.py` 消费、`pet/overlay_shell.py` 注入、
  每宠键 + 设置行）；capture（legacy 单窗）拓扑下该行按设计**置灰并带 tooltip**——这是
  **既有的产品口径**（capture 模式下宠是真实带标题窗口、无 sprite 路径），**不是本版没做完的缺口**。
  PR 把同名键接到 legacy `pet/window.py` 低速分支 + 仅配置文件无 UI + 全局键语义，
  与本树**键名相同而语义不同** ⇒ **不吸收**（否则两套语义/两份真值）。

三条都属于"本树是超集或已有既定量法"，因此**本轮 CI 收口不把它们当作待办**。

### 14.5 未确证与未修（诚实边界）

1. **Windows 的 access violation 与 Linux 的 SIGABRT 两次原生崩溃根因仍未确证**。本轮只加取证位
   （面包屑 + 失败实时回显 + CI 失败时回读 tail-30），**没有**声称修好它们；
   Linux 那次连一行原生栈都没有，`faulthandler.register` 兜底那条路已被证伪
   （CPython 对致命信号一律 `RuntimeError` 拒绝），详见
   `.scratch/ci243/WIN-LINUX-NATIVE-CRASH-FINDINGS-2026-10-11.md` §5、§7。
2. **mac 的 `INTERNALERROR` 是确证根因**（全局 `os.name` 伪装 ⇒ `pathlib` 实例化 `WindowsPath`），
   本批已消除该写法：当前全仓 `monkeypatch.setattr(os, "name", …)` 站点数 = **0**（grep 实测）。
3. **同一族但未动**：仍有 **53 处**测试在改**全局 `sys.platform`**（12 个文件：`test_feature_gating.py`、
   `test_game_fps.py`、`test_island_fps_integration.py`、`test_lyric_sources.py`、`test_memory_trim.py`、
   `test_music_player_settings.py`、`test_now_playing_media_type.py`、`test_platform_mac_shadow.py`、
   `test_platform_passthrough.py`、`test_proactive.py`、`test_requested_regressions.py`、
   `test_wayland_platform.py`）。`pathlib` 只按 `os.name` 选路径类，所以它们**不是** mac 那条
   INTERNALERROR 的成因；本批未动，登记为下一批候选（不在本轮 CI 收口范围内）。
4. 本批**没有**验证任何真实 FPS、**没有**起 GUI、**没有**跑三端 runner（见 §14.3）。

### 14.6 本地收口与待验边界

1. **收口全量门已结束**：Python 3.11.15 / PySide6 6.12.0，
   `.scratch/ci243/final_prepush311_full.log` = **6738 passed / 18 skipped**，
   1082.35 秒，后台任务真实退出码 **0**；按 CI 主套件命令隔离四个文件，不冒称其包含所有隔离族。
2. **时序高负载三轮**：12 个纯 CPU worker 下，四文件每轮 **91 passed / exit 0**，
   用时 20.37 / 24.82 / 52.18 秒，日志 `.scratch/ci243/highload/round{1,2,3}.log`。
   负载未绑核，不能声称固定保留四核空闲；负载子进程退出后无残留。
3. **诊断末次加固**：写入错误不得打断 pytest；回读步骤移到全部 pytest 步骤之后。
   这是全量后两处诊断调整，未再跑全量；启用诊断的工作流、FPS/交互、报告契约及四隔离文件
   合并复验 **319 passed / 5 skipped / exit 0**，77.66 秒；ruff 与 diff-check 通过。
4. **三端 runner 待修复后复跑**：用户已授权继续自主推进及候选分支验证，不再以缺许可阻塞。
   本地通过不代表 Windows/macOS/Linux CI 已通过，原生崩溃仍待新日志核真。
5. 真实 DSH 桌面端中止回合端到端、多 DSH 实例聚合作用域（§十二末条）等既有欠项不受本节影响。
