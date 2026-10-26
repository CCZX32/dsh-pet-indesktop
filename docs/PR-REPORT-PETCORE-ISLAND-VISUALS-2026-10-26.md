# PR 报告：灵动岛视觉动效收尾（五态点/声纳/呼吸/淡化/质感）（2026-10-26）

> 关联日志：`docs/PETCORE-LOG.md` L099。

## 0 结论先行

主分支 `pet/dynamic_island.py` 里上一轮明确「未做」的五项，这轮全部落地，且都按
「判定下沉零 Qt、绘制留在 UI」的分工来写：

| 项 | 主分支口径 | 落地位置 |
|---|---|---|
| 状态点五态 | 实心 / 空心环 / 红底白感叹；优先级 错误 > 待确认 > 工作 > 隐藏 > 完成 > 空闲；完成 4s 瞬态 | `layout.dot_state()` / `dot_style()` + `DynamicIsland._paint_status_dot()` |
| 工作态声纳环 | 1600ms、半径 5→13、α = 90·(1−t)³、1.5px 笔、30fps | `layout.sonar_ring_params()` + `_sync_sonar/_on_sonar_tick/_paint_sonar` |
| 回复后呼吸浮动 | 5s、1.5px·sin(2.6t)、整数像素 | `layout.breath_offset()` + `paintEvent` 平移 + `notify_event("reply")` |
| 130ms 内容淡化 | 旧图 α 1→0 线性、新图恒 1.0、按新图透明区遮罩 | `_content_layer/_render_content_pixmap/_start_content_fade/_on_fade_tick` |
| 三层投影 / sheen / 软陶 bevel / glass 渐变 | (1,+1,α28)(2,+2.5,α16)(3,+4,α8) / α14·42% / 上白 26 下黑 46 / 214·168·146·196 | `_paint_shell/_paint_sheen/_paint_bevel` + `layout` 常量 |

顺带补齐同一批口径里的小项：段间竖线竖直 alpha 渐变、头标内环（白 α46 / 黑 α20，
替代旧的深色实心圆）、单位盒 α×0.7。

## 1 修改文件说明

| 文件 | 改了什么 | 为什么 | 行数 |
|---|---|---|---|
| `petcore/island/layout.py` | 新增零 Qt 段：`dot_state()`（六态优先级）、`dot_style()`（形状/颜色角色）、`sonar_ring_params()`、`breath_offset()`、`content_fade_alpha()`、`sheen_alpha()/bevel_colors()/icon_ring_color()` 与全部常量（`DOT_*`、`SONAR_*`、`BREATHE_*`、`CONTENT_FADE_MS`、`CAPSULE_SHADOW_LAYERS`、`SHEEN_*`、`BEVEL_*`、`GLASS_STOPS`、`UNIT_ALPHA`） | AGENTS 红线：判定/几何必须能脱窗单测 | +172 |
| `petcore/ui/island.py` | 新增状态输入 `set_agent_state/notify_event/set_pet_visible`；三张新表（完成瞬态 4s、声纳 33ms、淡化 16ms）；`paintEvent` 拆成 shell/sheen/内容层/bevel/反馈/声纳；内容位图缓存 + 结构键 + 淡化；五态点绘制；`_animating()` 计入呼吸；`stop()/showEvent/changeEvent/refresh_from_config` 收口缓存与表 | 五项动效全部落在这里 | +517/−38 |
| `petcore/ui/chat/controller.py` | 首个 token / 起流 → `working`；`_apply_done` → `done`；`_apply_error` → `error`（经 `host.notify_agent_state`，缺方法时静默） | 状态点需要真实来源 | +14 |
| `petcore/ui/screen/ask_window.py` | 新增 `waiting_changed` 信号，`begin_waiting/end_waiting` 各发一次 | 截图识别期间也要「工作中」声纳 | +4 |
| `petcore/ui/screen/controller.py` | 连接 `waiting_changed` → `host.notify_agent_state("working"/"idle")` | 同上 | +11 |
| `petcore/ui/app.py` | 新增 `notify_agent_state()`；`set_all_visible()` 同步 `island.set_pet_visible()`；`ensure_island()` 初始可见性；新增 `_any_pet_visible()` | 「隐藏」态由宠物可见性派生 | +23 |
| `tests/test_petcore_agent_state_wiring.py`（新增） | 4 例：宿主把 `source` 转发给岛、旧签名岛降级不抛、无岛静默、截图窗 `waiting_changed` 起落 | 状态来源是「点会动」的前提 | +73 |
| `tests/test_petcore_island_visuals.py`（新增） | 30 例：优先级/形状映射/声纳曲线/呼吸整数量化与 5s 截断/淡化线性/常量对照；完成瞬态与定时器、隐藏派生、声纳起停与「状态点关掉就不播」、错误红感叹色；空心中心透明 vs 实心中心不透明 vs 感叹白笔画；缓存命中不重建、读数换字不淡化、结构变化播淡化并收表；三层投影像素、sheen 顶部更亮且 light 跳过、glass 竖直渐变、bevel 两半都有墨、头标不是黑洞 | 把「观感」变成可回归断言 | +400 |

## 2 性能分析

在 offscreen 环境、3 个指标段（CPU/内存/网络）、DPR=1、窗口宽约 330px 下实测：

| 路径 | 耗时 |
|---|---|
| `_render_content_pixmap()`（重排 + 绘制一张内容位图） | mean **0.151 ms**，median 0.138，p95 0.195（200 次） |
| `_content_layer()` 命中（键比对 + 返回缓存） | mean **0.0044 ms**，p95 0.0046（500 次） |

- 上一版每帧（16ms 动画、1Hz 时钟、声纳 33ms）都要重新做 CJK shaping 与逐段排版；
  现在只有**像素真的变了**才重建（读数换字、开关变化、宽度/DPR/字体变化），
  其余帧只做一次 blit + 键比对，**约快 34 倍**。
- 三张表都按需启停：声纳只在 `working` + 可见 + 非停靠 + `show_status` 时跑；
  完成瞬态 4s 单发；淡化 130ms 自停。空闲时没有任何新增定时器在走。
- 位图缓存只保留**一张**（宽度 × 44 逻辑像素，DPR 缩放），没有 LRU、没有无界增长；
  淡化期间额外一张「旧图 + 遮罩」，130ms 后释放。
- 新增的 `_content_cache_key()` 每帧算一次：13 个分量 + 段元组，微秒级。

## 3 实机运行记录

- `pytest -q tests/test_petcore_island_visuals.py` → **30 passed**。
- 全量 `pytest -q $(ls tests/test_petcore*.py)` → **1795 passed in 132.02s**。
  过程中先遇到 `test_petcore_websearch.py::test_fetch_page_text_is_truncated` 的**环境失败**：
  本机 fake-ip DNS 把 `e.test` 解析到 `198.18.0.0/15`（RFC 2544 保留段），
  `is_private_host` 依法拒绝，截断断言跑不到。已把该用例的目标校验收口到放行
  （截断与目标校验各管各的，单独一个提交），此后全量稳定全绿。
- 打包冒烟：`rel-visual-2026-10-26/dsh-pet-core-setup.exe`，268,556,584 B，
  sha256 `d9a43c575ddc22629e970cbdc331302736a16b4989b80dd240d8a79bc8011ca1`，
  `Get-AuthenticodeSignature` = **Valid**（CN=DSH Pet Core Dev）；打包内
  `--check --strict` 的 `check.json` 为 `strict.enabled=true, problems=[]`。
- `ruff check petcore tests examples scripts` → 通过。
- 离屏渲染核对：`.scratch/island-visuals.png`（五态点 + dark/glass/light + 淡化半程）、
  `.scratch/island-{dark,glass,light,fade}.png`。目视确认：dark 有外投影与顶部 sheen、
  glass 出现四停点竖直渐变、light 无 sheen、淡化半程是旧/新内容交叉而非白块。
- 未做真机目视：停靠细条与声纳环在真实多屏/混合 DPI 下的落点与观感仍待人工验收
  （离屏环境缺中文字体，文字渲染成方块，只用于几何与像素核对）。

## 4 子 agent 审查发现与修复（同一提交内）

实现完成后用只读子 agent 对整份 diff 做了一轮审查（对照旧主分支口径）。被采纳的
发现与修法如下——其中第 1、2 条是「越改越差」的真缺陷，不是风格问题：

| # | 发现（证据） | 修法 |
|---|---|---|
| 1 | **结构键含窗口宽度**：`_structure_key()` 首位是 `self.width()`，而几何动画每帧改宽度 → 每帧重起一次淡化（180ms ≈ 11 帧、11 次位图重建 + 掩码）；新旧宽度不同时 `setMask` 尺寸不匹配会被 Qt **静默丢弃**，`_fade_mask_for` 返回的副本其实没有掩码 → 旧图新图各画一遍 = 重影 | 结构键改「行预算 + 段 id 序列」；`_content_layer()` 只在 `previous.size() == rendered.size()` 时起淡化；`_fade_mask_for()` 尺寸不符直接返回 `None` |
| 2 | **状态单标量后写覆盖**：截图收尾发 `idle` 会把仍在流式回答的 `working` 关掉；一次余额刷新也会把 `working` 打回 `idle`；`error` 无 TTL → 一次「没配余额服务」的点击把红感叹永久钉住 | `set_agent_state(state, *, source=)` + `layout.resolve_agent_state()`（错误 > 待确认 > 工作）；`error` 加 8s TTL；**余额结果不再写状态点**（失败已有卡片红字） |
| 3 | **位图内容在悬停 1.02 缩放下是最近邻**（只开了 Antialiasing）→ 正文发毛 | `paintEvent` 开 `SmoothPixmapTransform` |
| 4 | **「隐藏」只接了一条路**：全仓只有 `set_all_visible` 调 `set_pet_visible`，快捷键/托盘逐宠/右键隐藏都绕过去了 | 新增 `_sync_island_pet_visible()`，`PetWindow.set_visible()` 回调宿主；四条路都收口 |
| 5 | 缓存键漏 `box_text` / `elide_px`（GPU/FPS 换样本时盒宽不更新）；`opacity` 多余 | 补齐两个字段、去掉 `opacity` |
| 6 | `_sync_sonar()` 缺「回到胶囊态」的调用点（最多等 1s 心跳才起环） | 展开/收起、停靠落定、细条收回、滑出四处显式调用 |
| 7 | 展开态 `_animating()` 仍把呼吸算作「在动」→ 16ms 表空转 5s | 加 `not self._expanded` |
| 8 | 果冻 1.12 + 悬停 1.03 + 呼吸 +2 会把底部投影推过 44px 窗高（被切平） | 投影 `drop` 按剩余高度收敛 |
| 9 | 声纳环末相位顶出胶囊右缘 1–2px | 裁剪到胶囊 `path` |
| 10 | 测试断言太松：错误感叹采样点落在红底上（`#f2777a` 亮度 181 → 断言恒真）；投影/bevel 只断言「有像素」 | 感叹改采竖杠（(8,6)，要求 lightness>220 且 α>200）+ 圆点区域取最大值；新增 7 例状态机用例（多来源归并、余额不动点、`stop()` 停四表、展开/停靠抑制声纳、缓存键含状态点、**宽度变化不淡化**、指标换序才淡化） |

未被采纳的：`_paint_status_dot` 里感叹用「两笔线段」而非主分支的 `QPainterPath`
（视觉等价，免去一条无测试覆盖的路径）；「胶囊点不再表达指标告警」——保留为语义切换，
已在 SPEC 里写明「点只表达智能体五态，指标告警在段上」。
