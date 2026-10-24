# P5-a1 交付：灵动岛 v1（2026-10-23）

> 主分支 4661 行的 `pet/dynamic_island.py` 在这里拆成「零 Qt 契约 + 零 Qt 布局 +
> 平台采样 + 唯一 Qt 窗口」四层，只交**能天天看见的骨架**：胶囊 + 3 个内置段 +
> 展开卡片 + 设置。动效、停靠细条、第三方段、GPU/FPS、聊天与碰撞见 ROADMAP §28「未做」。

## 1. 修改文件说明

| 文件 | 增/删 | 做了什么 & 为什么 |
|---|---|---|
| `petcore/island/segments.py` | +396 | 状态词表、`SegmentSnapshot`、盒宽自测量（`max_text` 声明样本 + 字体指纹缓存）、字段盒右省略护栏、`split_value_unit`、四态 `render_compact`、两级告警 + 3pt 滞回。移植自主分支同模块的宿主侧一半。 |
| `petcore/island/layout.py` | +532 | 段落位（19px 槽位 / 竖线 / 双盒单位）、`plan_info_row` 收缩流水线（名字省略→隐藏→尾部折 `+N`→保底）、`apply_shrink`（按 id 折、chip 取当刻最高告警）、`anchored_x` 三分区锚点。`_InfoSeg` 新增 `detail` 给卡片用。 |
| `petcore/platform/sysmon.py` | +198 | `CpuMeter`（首拍只建基线）、`SysMonitor` 1 Hz 单线程（间隔硬上限 1 Hz）、`format_cpu/mem`、`MAX_TEXT="888%"` 盒宽样本。**GPU 分支未移植**。 |
| `petcore/platform/netmon.py` | +214 | `NetRateMeter`（计数器差分 + EMA，首拍不伪造 0、回绕按 0）、`format_rate` 5 列定宽、`format_network_slot`、`NetMonitor` 线程。**不做延迟探测**（socket 只许在 `net/`）。 |
| `petcore/ui/island.py` | +740 | 唯一 Qt 面：44px 胶囊、三套配色 + 五档强调色、自绘胶囊/面板、状态点、展开卡片（一行一段）、拖动换位与坐标持久化、15s 自动收起、隐藏即停采样。 |
| `petcore/config.py` | +90 | 13 个 `island_*` 全局键 + 归一化：指标白名单/去重/≤8、透明度 0.4–1.0、配色与强调色枚举、坐标有限值与 ±100000 校验。 |
| `petcore/ui/app.py` | +75 | `ensure_island()/apply_island_settings()/toggle_dynamic_island()`；`apply_live_settings()` 顺带刷新（设置页实时预览）；`quit_app()` 停线程；启动时按配置显示。 |
| `petcore/ui/pet_window.py` | +5 | `toggle_dynamic_island()` 转发到 host（菜单项要一个窗口级入口）。 |
| `petcore/ui/menu_actions.py` | +9 | 菜单项 `dynamic_island`（「灵动岛」，勾选项，`pet_controls` 组）。 |
| `petcore/ui/settings/pages_core.py` | +190 | 「外观与交互 → 灵动岛」7 行：启用、显示元素、信息位、指标段、配色与强调色、不透明度、单击行为；改动即写全局配置。 |
| `petcore/ui/settings/coverage.py` | +1 | 菜单项 → 设置落点登记（`dynamic_island` → appearance/灵动岛）。 |
| `petcore/menu_templates/petcore-default-v1.json` + `menu_layout.py` | +2 | 模板两个副本同步插节点（`edge_probe` 之后）；旧布局由 `_merge_template_actions()` 递归补入，无需新迁移函数。 |
| `tests/test_petcore_island_segments.py` | +351 | 主分支同名单测移植（40 条：单行约束、label 截断、盒宽公式/缓存/字体失效、字段盒护栏、四态、告警滞回）。 |
| `tests/test_petcore_island_layout.py` | +280 | 17 条：落位槽位/双盒/无 OK 不画单位、chip 内边距与告警点不改宽、收缩各级、尾部优先、计划可逆、读数不进宽、`apply_shrink` 用当刻文案与当刻告警、三分区锚点。 |
| `tests/test_petcore_island_sampling.py` | +190 | 33 条：间隔夹取、速率/百分比格式、定宽不变量、EMA 与首拍、计数回绕、线程生命周期、读数失败降级。 |
| `tests/test_petcore_island_window.py` | +270 | 21 条：固定高/最小宽、指标顺序、未知 id 不占位、读数不改宽、展开/收起、卡片行（含纯 glyph 段中文名、采样态、错误态）、点击分叉、拖动收起与坐标保存/恢复、配置刷新、隐藏即停采样、悬停暂停自动收起、配色透明度、告警只染数值。 |
| 文档 | — | SPEC §29（键表/四态/收缩/采样纪律/不做项）、ARCHITECTURE §26（数据流与宽度白名单）、ROADMAP §28、parity、function matrix、`petcore/AGENTS.md` 灵动岛红线、LOG `L053` + 索引、本报告 + `docs/INDEX.md`。 |

## 2. 性能分析

| 路径 | 样本 | 实测 / 预算 |
|---|---|---|
| 采样线程 | 1 Hz × 2 条（sys / net） | 每条一拍一次 psutil 调用（毫秒级），空转零唤醒；岛隐藏/段折叠即 `stop()` |
| GUI 刷新 | 1 s 一拍 | 只读快照 + 组段 + 行计划（纯函数，无 syscall）；宽度键不变时不重排窗口 |
| 行计划 | 一次 `plan_info_row` | 3 段时 ≤ 6 个候选、每候选一次 `place_info_segments`（每段 2–3 次 `horizontalAdvance`），微秒级 |
| 盒宽缓存 | 按 `(id, 字体指纹)` | 字体不变就不重测；`clear_width_cache()` 在 `FontChange` 时调用 |
| 绘制 | 每帧自绘 | 胶囊 + 一行文字 + 至多 3 条竖线 + 1 个点；无位图缓存（v1 简化），展开时卡片是原生 QLabel |
| 真机尺寸 | 150% DPI | 收起 434×44 逻辑 / 651×66 物理；展开 349×205 逻辑 |

**为什么不做位图缓存**：主分支缓存内容层是因为它有形变/渐隐动效（每帧重绘昂贵）；
v1 没有动效，1 Hz 重绘一次的开销远小于缓存失效逻辑的风险。等 P5-a2 加动效时再引入。

## 3. 实机运行记录

```
$ .venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods/
All checks passed!

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
    tests/test_petcore_*.py tests/test_architecture.py \
    tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
1541 passed in 84.18s          # 基线 1430，本轮 +111

$ .venv/Scripts/python -m petcore --check
exit 0
```

真机渲染（`.scratch/probe_island_real.py`，真字体 + 150% DPI，抓图后退出）：

```
collapsed 434 44 dpr 1.5
expanded  349 205 plan ('primary', 'network', 'cpu', 'chip') level 4
```

抓图核对（`.scratch/island-real-dark.png` / `island-real-card.png`）：
`深深 | 22:30 | ↓1.2M ↑340K | CPU 87%(琥珀) | 内存 61% •`；
展开卡片是圆角面板，尾部 `+1` chip 折掉内存段，行内 CPU 值保持琥珀色。
**这一轮抓图发现并修掉了两个真机缺陷**：① 状态点按「窗口右缘反推」算 x，比内容右缘多退
一个间距 → 压在末段上；② 展开态没画面板背景、行仍按屏宽排版 → 内容被卡片裁掉。

整程序冒烟（`python -m petcore --root .scratch/island-app --portable --verbose`，9 秒后 kill）：

```
DEBUG petcore.ui.app: island apply: metrics=['network', 'cpu', 'mem'] style=dark character=shenshen
（0 条 ERROR / 0 次 Traceback）
```

**未做真机交互验收**：拖拽换位、15s 自动收起、多屏迁移由用户实际使用时确认；
打包未重跑（新增纯 Python 模块，PyInstaller 静态分析可收集，`psutil` 早已在构建脚本）。


## 2026-10-24 补充：测试范围口径

保留上文原始执行记录。上文「全量」应理解为命令中列出的 `test_petcore_*.py`
及公共门禁文件的选定测试，不是仓库全量 `python -m pytest -q`。不能用这些历史
数字代表本轮验收；本轮环境、整仓失败/崩溃、实机与限制见
[已有能力质量审查](PR-REPORT-PETCORE-QUALITY-REVIEW-2026-10-24.md)。
