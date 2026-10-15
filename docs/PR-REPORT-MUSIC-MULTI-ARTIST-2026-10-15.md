# PR 报告：多歌手分隔符归一（酷狗/汽水歌词）+ 设置页文案指引

> **基线**：`99bdc7f`（main，含 #277）
> **分支**：`feat/music-multi-artist`　**日期**：2026-10-15
> **范围**：5 个文件（实现 2、测试 1、文档 2）
> **关联**：用户需求「酷狗音乐/汽水音乐看不到歌词」；调研记录见本报告 §三

## 一、核心特性

用户反馈酷狗音乐/汽水音乐放歌时桌宠没有歌词。调研结论（本机实测 + 公开资料）：
**两个播放器都已注册 Windows SMTC**（汽水时间轴完整；酷狗需在其设置里开
「支持系统播放控件」且无时间轴），"正在播放"层零改动即可识别——填 exe 路径
没用是因为那只影响右键「打开播放器」菜单，与歌词链无关。

真正丢词的原因（实机复现）：酷狗 SMTC 报的歌手是 `FLOW、GRANRODEO`（CJK 顿号），
歌词源返回 `FLOW/GRANRODEO`（斜杠），`_name_matches` 只做整串子串比对 →
「搜索到 10 个候选但无人匹配歌手」→ 丢词。**这是取词链的通用缺陷**，
对网易云/QQ 的多歌手曲目同样有效。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 多歌手分隔符归一 | `、` `/` `／` `&` `×` `,` `； feat. ft.` 两侧都是多歌手形态时逐段比对 |
| 2 | 设置页指引 | 「显示歌词」行写明酷狗的开关位置；酷狗/汽水无需填路径 |

**红线 / 不变量**：单侧无分隔符保持原语义（防单名误命中）；整串子串命中
优先于逐段比对（既有行为逐位保留）；逐段比对是去空白后**相等**（不用子串，
防碎片假命中）。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/music_lyric.py` | +23 / −2 | `_name_matches`：整串子串命中后，新增「两侧都含分隔符 → 归一逐段**相等**比对」分支；`_ARTIST_SEP_RE` 模块级编译一次，feat/ft 带**双侧**词边界且在去空白前切分（两轮盲审返修：左侧无边界会拆碎 swift/craft，右侧无边界会拆碎 Featherstone/FTIsland）；逐段比对为去空白后相等 |
| `pet/modern_settings_dialog.py` | +1 / −1 | 「显示歌词」行 hint：补酷狗开关的具体位置（设置 → 常规设置 → 播放 → 支持系统播放控件）+「酷狗/汽水无需填路径」（防止再有人往音乐关联槽里填 exe） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_music_lyric.py` | +46 / −0 | 四条：分隔符变体互认（含实机样本 `FLOW/GRANRODEO` × `FLOW、GRANRODEO`、中文、feat.、英文逗号）；防误伤（单侧无分隔符/多歌手互不相干）；词边界反例（盲审两轮：swift/craft/daft punk 不被拆碎、碎片不假命中、Featherstone/FTIsland 词首不误拆） |

红→绿：改前 `test_name_matches_multi_artist_separator_variants` 红在
`assert _name_matches("FLOW/GRANRODEO", "FLOW、GRANRODEO")`（False）；
改后 105 + 17 条全绿（见 §六）。

### 未改动（有意）

- **窗口标题通道**：不新增。汽水标题恒为「汽水音乐」（读不到内容）；酷狗暂停时
  标题残留上一首会串台。SMTC 已通，标题通道是下位替代。
- `pet/music_players.py` 的 PLAYERS 表：不加酷狗/汽水条目——该表服务右键
  「打开播放器」菜单，与歌词无关；等真有"打开酷狗"需求再说。
- QQ 音乐歌词源 500（本机当日整体故障，curl 直测同样 500）：源侧问题，非本仓可修。

## 三、实现要点与调研记录

调研方式：本机枚举 SMTC 会话（酷狗 20.1.51.27967 / 汽水 3.7.0 均在运行），
直接调 `get_now_playing()` 验证汽水在播曲目可读；酷狗/汽水的 SMTC 支持情况
对照 Lyricify 官方支持表（酷狗"无时间轴信息"、汽水"完美"）。

分隔符集合的取法：CJK 顿号（酷狗实测）、ASCII/全角斜杠（网易云/QQ 歌词源）、
`&`/`×`/逗号/分号（常见曲库）、`feat.`/`ft.`（英文曲库，带词边界——否则 swift/
craft/daft punk 会被拆碎，盲审 P1）。逐段比对是**去空白后相等**（不用子串——
2-3 字符碎片几乎什么都命中，盲审 P2）。`&`/`/` 会拆开 Simon & Garfunkel / AC/DC
这类组合名，由「两侧都是多歌手形态」闸门限幅（盲审 P3，已知取舍）。逐段比对要求
**两侧**都是多歌手形态（`len(raw) >= 2`），单侧无分隔符直接退回原语义——
防止 "A" 误中 "Aimer、B" 这类单名误命中；1 字符段（罕见单字母歌手）不参与
逐段比对。

## 四、性能分析

实测（本机 Windows 11，Python 3.13，混合样本（含多歌手命中/单名子串/无关拒绝），
n=30000 取均值；复现命令：
`python -c "import time;from pet.music_lyric import _name_matches;pairs=[('FLOW/GRANRODEO','FLOW、GRANRODEO'),('周杰伦','周杰伦/Jay Chou'),('其他歌手','周杰伦')];t0=time.perf_counter();[[_name_matches(c,w) for c,w in pairs] for _ in range(10000)];print((time.perf_counter()-t0)/30000*1e6)"`）：

| 路径 | 实测 | 触发频率 |
|---|---|---|
| `_name_matches`（含分隔符归一分支） | **3.31 µs/次** | 每次取词的候选比对（每次查歌词十来个候选，用户触发级） |

无新增 IO/网络/线程；`_ARTIST_SEP_RE` 模块级编译，摊销为零。

## 五、实机运行记录

本机 Windows 11（两个播放器真实在跑）：

- 汽水音乐在播《爱要怎么说出口(R&B女生版)》/ 七分可可：`get_now_playing()`
  直接返回结构化曲目（`app_id='汽水音乐'`，时间轴完整）；网易云源命中完整 LRC。
- 酷狗在播 Howling / `FLOW、GRANRODEO`：修复前取词失败（候选 10 条无人匹配），
  修复后 `_name_matches('FLOW/GRANRODEO', 'FLOW、GRANRODEO') = True`（回归测试锁住）。
- 设置页文案改动已跑 copy lint（`test_settings_copy_lint.py` 绿）。

局限：酷狗的 SMTC 开关（它自己设置里的「支持系统播放控件」）在本机已开；
未开时的行为 = 读不到会话（既有行为，文案已指引）。

## 六、验证

- `test_music_lyric.py` + `test_lyric_sources.py` + 音乐族 + 设置文案 lint 合计
  **207 passed, 0 failed**（`QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:randomly`
  tests/test_music_lyric.py tests/test_lyric_sources.py tests/test_music_title.py
  tests/test_music_detect.py tests/test_music_player_cache.py tests/test_music_player_settings.py
  tests/test_music_sing_grace.py tests/test_music_sing_timer.py tests/test_overlay_music_sing.py
  tests/test_settings_copy_lint.py）。
- `ruff check` 改动文件干净。
- 全量套件结果见 PR 描述。
