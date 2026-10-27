# PR 报告：音乐识别重写 + 设置「扩展管理」两轴弹性（2026-10-26）

> 需求原文：「音乐识别有问题，在 GitHub 上搜索有没有这方面的实现，我们重写音乐识别
> 功能。另外还有个小改进：让设置的「扩展管理」页的两个轴都能随设置缩放适当调整，
> 当前的显示范围就作为下限。」
>
> 口径确认：症状=漏检 / 误检 / 认错歌（全都要，整体重写）；路线=多源元数据（不做
> 听声识曲）；两轴=宽 + 高随窗口/字号弹性，当前范围作下限。

---

## 1. 修改文件说明

### 1.1 音乐识别（`examples/petcore-mods/media.music`，1.1.0 → 1.2.0）

| 文件 | 增/删 | 改了什么 + 为什么 |
|---|---:|---|
| `host/audio_sessions.py` | +324 / 新 | **新增**。WASAPI 逐进程音频会话（Active / 静音 / 峰值）。旧实现只有 SMTC，播放器被静音、或会话停了而元数据没更新时照样唱歌；这条证据回答"这个进程到底在不在出声"。缓存 endpoint 的 `IAudioSessionManager2`（实测 24ms → 2ms），COM 在调用线程 `CoInitialize/CoUninitialize`，设备切换/异常按 30 秒节流重建。 |
| `host/window_source.py` | +209 / 新 | **新增**。`EnumWindows` 找已登记播放器的无属主可见顶层窗口（foobar2000/AIMP/Winamp 不注册 SMTC，旧实现完全看不到）。同 pid 只留最长标题（网易云实测有两个顶层窗口），进程名按 pid 单次采样内缓存。 |
| `host/title_clean.py` | +683 / 新 | **移植**主分支 `pet/music_title.py`（`clean_web_title` + `parse_foobar_title`）+ 新增 `parse_window_title(title, exe, fmt)`（剥 AIMP/Winamp 的窗口标题后缀）。`pet/` 是待删的兼容层，mod 不能 import 它；移植后做了差分验证（见 §3.1）。 |
| `host/recognizer.py` | +349 / 新 | **新增**。三源合并判定的唯一真源（纯函数）：SMTC 主源、音频会话裁判"在不在出声"、窗口标题兜底；产出 `Decision(status/source/track/confidence/reasons/evidence)`。判定表写进 `docs/PETCORE-MOD-FORMAT.md` §13.3。 |
| `host/sampling.py` | +95 / 新 | **新增**。采样编排：SMTC 与音频恒定、**窗口标题按需**（SMTC 没有在播会话时才枚举）。设置页按钮与运行时共用同一份编排，诊断才不会"说的和判的不是一回事"。 |
| `host/diagnostics.py` | +163 / 新 | **新增**。把一次采样渲染成诊断文本（设置页「识别诊断」与 `scripts/music_probe.py` 共用）。只含 app_id / 可执行名 / 曲名 / 状态与数值；无 URL、路径、代理、歌词正文。 |
| `host/runtime.py` | +466 / -159 | **重写状态机**。修 8 个缺陷：①单拍采样失败就清歌词并重新取词 → 区分"读失败"与"没在放"，缺席只冻结时钟；②唱歌重试 4 次后永久放弃 → 2^n 拍退避、永不放弃；③取词一次失败拉黑整首 → 60 秒冷却、每曲 ≤3 次、首次失败说原因；④切宠后循环残留 → 逐 slot lease/release；⑤无采样令牌 → 每拍一个；⑥纯音乐先唱 1–8 秒 → 曲目开始先观察一拍；⑦`say` 失败仍推进行号 → 不推进；⑧`_post` 抛错时 `_inflight` 卡死 → 复位。 |
| `host/now_playing.py` | +133 / -32 | SMTC 采样收敛为 `read_sample() -> SmtcSample`（会话事实 + 曲目 + 原因 + `failed`），旧接口 `read_playback_with_reason` 保留为薄封装；补上主分支的**位置外推** `_extrapolate()`（消除 ≤1 秒的音画滞后；时间戳无效时不外推）。 |
| `host/lyrics.py` | +287 / -66 | 取词前清洗查询词（只用于搜索，不改显示）；候选按「歌名 1.0 / 歌手 1.0 / 专辑 0.4 / 时长 1.0」加权、缺失字段重归一、阈值 0.55，**取分最高者**而不是"第一个歌手名命中的"（认错歌的根因）；新增 lrclib 源（海外曲目 + 显式 instrumental 标记）。 |
| `host/players.py` | +53 | 新增**识别用**播放器表 `KNOWN_MUSIC_EXES` 与 `recognition_targets()`（已知 ∪ 用户配置 ∪ 额外识别名）。刻意不含 VLC/mpv/PotPlayer——那些以放视频为主。 |
| `host/settings_page.py` | +162 / -85 | 「识别诊断」H3（按钮 + 只读多行 + 复制 + 一行结论）、「播放器标题格式（高级）」行；`_snapshot()` 从位置元组改字典（插键不再静默错位）；隐私说明改为三源口径。 |
| `mod.json` | +7 / -2 | 版本 1.1.0 → 1.2.0（行为面变化）。 |

### 1.2 设置「扩展管理」两轴（`petcore/ui/settings`）

| 文件 | 增/删 | 改了什么 + 为什么 |
|---|---:|---|
| `page_extensions.py` | +138 / -5 | 新增纯函数 `font_scale / nav_bounds / nav_width`（导航宽 = 最宽标签 + 35，夹在 `[190, 260×字号系数]`）；浏览器容器 `stretch=1` 且尾部 spacer stretch 置 0（高度吃满窗口，不再恒 420）；`_apply_geometry / reflow / resizeEvent / changeEvent` 在字号、样式 polish、标签变化后重算；`content_max_width=None`（本页宽轴跟视口）。 |
| `base.py` | +13 / -1 | `SettingsPage.content_max_width = 860` 类属性（默认不变）+ `reflow()` 默认空钩子。 |
| `dialog.py` | +40 / -5 | `refresh_style()` 之后按字号重算主侧栏行高并调用各页 `reflow()`；行高改用 `nav_row_heights()`（13→34、18→39）。 |
| `style.py` | +21 / -2 | `nav_row_heights()` 成为 QSS 与 Python 的同一份真源；两个导航加 `font-size`（否则 `ui_font_size` 只放大标签、导航被 min-height 切字）。 |
| `config.py` | +22 / -4 | 新全局键 `music_title_format`（默认 `""`，≤120 字符，走 `SETTINGS-CHANGE-GATES` 记录）+ 迁移别名 `foobar_title_format`。 |

### 1.3 工具与测试

| 文件 | 增/删 | 说明 |
|---|---:|---|
| `scripts/music_probe.py` | +132 / 新 | 命令行识别探针（只读）：逐拍打印三源采样与判定，`--profile` 打采样耗时。实机验收与用户报障用。 |
| `tests/test_petcore_music_sources.py` | +374 / 新 | 判定表 26 例（三源合并逐行、白名单跨源、UWP 无 exe、读失败≠缺席、标题不重复贴两遍）。 |
| `tests/test_petcore_music_sources_probe.py` | +296 / 新 | 两个探针的纯逻辑 20 例 + **10 个运行期模块的 import 纪律**（参数化，扫描整条识别链路）。 |
| `tests/test_petcore_music_title.py` | +511 / 新 | 主分支 24 条真值 + 4 条 `parse_window_title` + 1 条**与 `pet/music_title.py` 的常驻差分等价性**（15+7 组真值，防止两份实现漂移）。 |
| `tests/test_petcore_music_lyric_quality.py` | +257 / 新 | 打分 14 例（翻唱被拒、缺失字段归一、时长阈值、查询词清洗、候选不是取第一个、lrclib、全失败点名各源）。 |
| `tests/test_petcore_music_runtime_state.py` | +422 / 新 | 状态机 15 例（抖动不清歌词、缺席不遗忘、退避可恢复、取词冷却上限、原因只报一次、say 失败不推进、每宠 lease/释放、迟到采样丢弃）。 |
| `tests/test_petcore_music_diagnostics.py` | +156 / 新 | 诊断文本 6 例（三源都在、暂停/失败措辞、平台不可用、不泄 URL/路径）。 |
| `tests/test_petcore_extensions_geometry.py` | +263 / 新 | 两轴 12 例（纯函数边界、填充高度、宽轴跟窗口、其它页仍 860、字号热切换、最小窗口不回退、行高与 QSS 同源、键盘可达）。 |
| `tests/test_petcore_music_mod.py` | +56 / -17 | 采样接缝改名（`sample_smtc/_audio/_windows`）、退避语义替代"4 次后永久放弃"、三源计数、设置页新分组与标题格式 round-trip、诊断视图。 |

**合计**：新增 14 个文件（6 个产品模块 + 1 个脚本 + 7 个测试），修改 13 个文件；新增/重写测试合计 **152 例**（音乐 140 + 扩展几何 12），本批所有相关用例一次跑通。`git diff --numstat`（含上面各行）与未跟踪文件行数见上表。

---

## 2. 性能分析

### 2.1 受影响路径与实测数字（本机 Windows 11 / Python 3.12.10 / 2026-10-26）

| 路径 | 命令 / 方法 | 结果 |
|---|---|---|
| SMTC 全量采样（1 会话，含 props/timeline） | 30 次 `request_async` + `try_get_media_properties_async` | **median 3.08ms / p95 4.99 / max 19.75** |
| 音频会话枚举（缓存 endpoint manager，含峰值+静音+进程名） | 200 次 `audio_sessions.snapshot()` | **median 1.73ms / p95 2.48 / max 3.27**（纯枚举 0.9ms） |
| 同上但不缓存 manager（现成 `AudioUtilities.GetAllSessions()`） | 200 次 | **median 23.97ms** → 这就是必须缓存 manager 的原因 |
| 窗口枚举（全桌面带标题窗口 + 进程名，3 个目标进程） | 100 次 `window_source.snapshot(...)` | **median 0.57ms / p95 1.34 / max 2.33** |
| 运行时整拍（真实探针，同步路径） | `.scratch/verify_music_runtime.py` 4 拍 | 5.4–8.6ms（首拍 301ms 含 winrt import） |
| 设置页按钮一次诊断 | 同上 | 一次点击 = 一拍采样 + 文本渲染 |

### 2.2 稳态开销

- **节奏不变**：仍是 1 秒一拍、仍是**同一条** `music-smtc` 后台线程（没有新增常驻线程）；
  GUI 线程每拍只做判定（纯函数，20 余次字典/字符串运算）。
- **每秒新增系统调用**：`GetSessionEnumerator/GetCount/GetSession` × 会话数 + 每会话
  `GetPeakValue/GetMute`（约 10 次 COM 调用，2.1ms）；窗口枚举**按需**——SMTC 有在播会话
  时一次都不做（旧行为里窗口源根本不存在）。
- **占单核比例**：(3.1 + 2.1)ms / 1000ms ≈ **0.5%**，其中 2.1ms 在后台线程。
- **网络**：没有新增请求。lrclib 只在"前两个源都没命中"时发一次，且与前两源共享同一份
  8 秒 deadline 与 `max_bytes=2MB`；失败冷却重试（60s、≤3 次）反而**减少**了旧实现
  "一次失败永不重试"导致的用户手动重开设置/重启后的重复请求。
- **磁盘**：没有新增写入；歌词缓存仍是"一曲一 JSON + 上限淘汰"。
- **内存**：只保留当前一首的歌词（换歌即替换），缓存上限不变（默认 80 首）；
  没有新增常驻缓冲（`audio_sessions` 只缓存一个 COM manager + 30 秒节流时间戳）。

### 2.3 设置页几何

- 纯计算：一次 `_apply_geometry()` = 一次 `QFontMetrics.horizontalAdvance` × 导航行数
  （≤20）+ 两次 `setFixedWidth/setMinimumHeight`（值不变时不调）。
- 触发频率：构造、`resizeEvent`（窗口拖动）、`FontChange/StyleChange`（字号切换）、
  导航标签变化（装/卸载扩展）。**没有定时器**，空闲时零成本。
- 界面效果：1600×1000 窗口下浏览器高度 420 → **864**（下方空白 464 → 20px 内边距）、
  内容宽 860 → **1400**；720×500 下导航仍 190、Mods 页横向滚动仍是 110px（不回退）。

---

## 3. 实机运行记录

### 3.1 标题清洗移植的差分验证（子代理执行，本机）

把主分支 `pet/music_title.py` 与 mod 里的 `title_clean.py` 各自单独加载，逐条比对：

```
17 条真值表 × 3 种 artist + 4000 组随机 (标题, artist, fmt)（固定种子，语料含
《》/【】/「」/站名/噪声词/病态 fmt）→ diffs = 0
22 个模块级常量的 pattern/取值、8 个字面量正则逐字符相同
```

### 3.2 识别探针（`scripts/music_probe.py`，真实播放器）

```text
[probe] 平台=win32 间隔=1s 时长=3s
[probe] 识别范围=（不过滤） 窗口源允许=9 个可执行名
===== 23:31:16 第 1 拍（采样 301.5ms）=====
SMTC：1 个会话
  cloudmusic.exe  MUSIC(1)  PLAYING
音频会话：2 个（Active 1）
  steam.exe  pid=3640  inactive  mute=no  peak=0.00
  cloudmusic.exe  pid=24076  active  mute=no  peak=1.00
播放器窗口标题：0 个已登记播放器的窗口
判定：在播 · 来源=系统媒体会话 · 进程=cloudmusic.exe · 曲目=《开不了口》—周杰伦 · 置信度=有音频证据
证据：
  · cloudmusic.exe 音频会话 state=active mute=no peak=1.00
[profile] 采样耗时 ms：median=6.74 p95=6.74 max=301.49 n=3
```

### 3.3 运行时端到端（`.scratch/verify_music_runtime.py`，只读、不开窗口）

A 组：真实三源 + 真实运行时状态机（用户当时正在用网易云听《开不了口》）：

```text
第 1 拍   6.8ms  status=playing  source=smtc    track=周杰伦 - 开不了口   singing=True
第 2 拍   8.6ms  status=playing  source=smtc    track=周杰伦 - 开不了口   singing=True
第 3 拍   7.2ms  status=playing  source=smtc    track=周杰伦 - 开不了口   singing=True
第 4 拍   8.4ms  status=playing  source=smtc    track=周杰伦 - 开不了口   singing=True
运行时事件： [('anim', '悠闲哼歌', True)]
```

B 组：**SMTC 置空**（模拟"该播放器不注册系统媒体"），窗口枚举与音频会话仍是真的：

```text
SMTC：没有会话
音频会话：2 个（Active 1）  cloudmusic.exe active mute=no peak=1.00
播放器窗口标题：1 个  cloudmusic.exe pid=24076 「开不了口 - 周杰伦」
判定：在播 · 来源=播放器窗口标题 · 置信度=有音频证据
第 1 拍  status=playing  source=window  track=开不了口 - 周杰伦  singing=True
```

**这一轮抓到并修掉一个真实缺陷**：无格式串时解析器把整条标题同时当歌名与歌手
（气泡显示成《开不了口 - 周杰伦》—开不了口 - 周杰伦）。已改为"顺序不可知时显示只给
整条标题"，并补了 `test_window_source_does_not_repeat_the_title_as_artist`。

### 3.4 设置页两轴：六张截图与实测几何

`.scratch/petcore-evidence/extensions-geometry/extensions-<宽>x<高>-font<字号>.png`
（720×500 / 900×620 / 1600×1000 × 字号 13 / 18）：

```text
720x500  font13: nav=190 stack=242x420 minH=420 content=506
720x500  font18: nav=190 stack=242x420 minH=420 content=506   ← 最小窗口不回退
900x620  font13: nav=190 stack=436x484 minH=420 content=700   ← 高度 420→484
900x620  font18: nav=190 stack=436x479 minH=420 content=700
1600x1000 font13: nav=190 stack=1136x864 minH=420 content=1400 ← 宽 860→1400、高 420→864
1600x1000 font18: nav=190 stack=1136x859 minH=420 content=1400
```

（导航宽度在本机这些配置下仍是 190，因为 `FakeHost` 里没有长 mod 名——它是
"内容驱动 + 下限 190 + 上限随字号放大"，长标签场景由
`test_larger_font_grows_the_nav_and_its_text` 用 20 字的加装页标题验证。）

### 3.5 门禁

```text
.venv/Scripts/ruff check pet/ tests/ petcore/ examples/ scripts/   → All checks passed!
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/ -q  → 见 §3.6（全量）
.venv/Scripts/python -m petcore --check                            → 见 §3.6
```

### 3.6 门禁真实输出（最终树）

```text
$ .venv/Scripts/ruff check pet/ tests/ petcore/ examples/ scripts/
All checks passed!

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/ -q -k "petcore"
2165 passed, 8412 deselected in 183.68s (0:03:03)

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/ -q -k "music or settings or extensions or docs or pr_report"
542 passed in 26.99s

$ .venv/Scripts/python -m petcore --check --strict   → exit=0
  version=0.2.0  menu_template=json  characters=1
  strict={"enabled": true, "problems": []}  diagnostics=[]

$ .venv/Scripts/python scripts/build_petcore_extensions.py --packs media.music --strict
  [build] media.music 1.2.0 -> media.music-1.2.0.zip (14 files, 71645 bytes, sha256 b9053d45418f)
  [build] media.music excluded: blocked=0 generated=13 unknown=0
```

全量（`pytest tests/ -q`，整仓，含主分支遗留用例，25 分 37 秒）：

```text
1 failed, 10558 passed, 18 skipped, 18 warnings in 1537.91s (0:25:37)
FAILED tests/test_chat_subsystem.py::test_append_message_atomic_across_store_instances
```

**唯一失败与本批无关，是主分支 chat store 的既有时序 flake**（证据）：

- 该用例与 `pet/chat/*` 在本批**完全未改动**（`git status` 对这两条路径为空）；
- 隔离复跑：工作树 5 次里 1 次失败（4 通过）；用 `git worktree` 检出**未含本批改动的
  HEAD**（3bfe193c）同样 6 次里 1 次失败（5 通过）——与工作树无关，是
  `SessionStore.delete()` 的异步 writer + pending 层读旧快照的竞态
  （`pet/chat/session_store.py:499-520` 的 `append_messages` 与 `:580-586` 的 `delete`）；
- 复现命令：
  `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_chat_subsystem.py::test_append_message_atomic_across_store_instances -q`
- 按仓库的 flake 纪律（"连续两轮修同一族测试不绿就隔离出主套件"），本批**不**顺手改
  主分支 chat store（那属于另一张票，且 `pet/` 是待删的兼容层）；在报告里登记为已知 flake。

---

## 4. 独立审查发现并修复（对抗式 review）

写完代码后开了一个只读子代理做对抗式审查（带变异测试与行为探针）。它抓到 **1 个阻断、
2 个高点、6 个中点**，逐条处置如下（每条都补了会红的回归用例，做过变异验证）：

| # | 问题 | 处置 |
|---|---|---|
| **B1 阻断** | `control_playback = now_playing.transport` 写成**类属性** → 经实例访问被绑成方法，`self` 塞进 `action` 位，四个播放控制命令 100% 抛 `TypeError` 再被吞成「系统媒体控制调用失败」。测试全程替换了这个接缝，所以没抓到 | 改成 `__init__` 里的**实例属性**；`transport()` 改到后台线程执行、结果回 `_post`（原来在 GUI 线程同步调 WinRT，可能卡住界面）。新增 2 例：一条走默认接缝打真 `commands["pause"]()`，一条断言它不是绑定方法。**变异验证：把类属性改回去，两例立刻红** |
| **H1 高** | SMTC 里挂着**暂停**会话时，`sampling` 照采窗口源、`recognizer` 却永不采信 → 「挂着的客户端 + foobar 在放」仍漏检，且诊断里证据齐全、理由为空 | `decide` 在「SMTC 暂停 + 已登记播放器窗口可解析且音频 Active」时改判为窗口源在播，理由写明"以窗口标题源为准"；另两例锁住反向（另一台没在出声时仍判暂停） |
| **H2 高** | `exe_name()` 没取 basename：路径形状的 app_id（`C:\Program Files\...\cloudmusic.exe`）让静音/Inactive 证据全失配（回到"照 SMTC 唱"），并把安装路径漏进诊断与气泡 | `exe_name` / `normalized_exe` 统一先取 basename；新增用例：路径 app_id + 静音会话 → 判暂停、`exe == cloudmusic.exe`、无 `Program Files` |
| M1 | `MusicRuntime.diagnose()` 是死代码，注释却声称"设置页与探针共用" | 删除（两处调用点本来就各自走 `sampling.collect` + `recognizer.decide` + `diagnostics.render`） |
| M2 | `lyrics.py` 里 `_get_json` 定义了两次（第一份被覆盖，F811 漏报） | 删掉旧的一份（34 行） |
| M3 | 设置页两次点击各起一条线程，不 `close_thread_loop()` / `audio_sessions.close()` → 漏事件循环、把音频会话缓存绑到将死线程 | 两个 `work()` 都加 `finally` 收尾 |
| M4 | 文档与实现冲突：§13.3 写「气泡说明一次」但没实现；AGENTS 里「歌词不重试」与「60 秒冷却重试」自相矛盾 | 实现"认不出曲目"的一次性提示（同一台播放器只报一次）；AGENTS 改成"不重复换路；取词重试由运行时按 60s 冷却控制" |
| M5 | 本报告性能表的 p95 小于 median（两轮样本混写）；§3.6 门禁数字缺席 | 重测后填入真实 median/p95/max（§2.1）；§3.6 用最终一次全量跑的真实输出补齐 |
| M6 | 纯音乐仍会先唱到取词返回（只削掉 1 秒） | 取词**在飞**期间最多再等 `LYRIC_PROBE_MAX_TICKS=3` 拍；缓存命中/没网立刻失败时不等（不会让普通曲目每次多等 3 秒）。新增用例锁住"等满后无条件放行" |
| M7 | 端口纪律测试只守 2 个模块 | 参数化到 **10 个运行期模块**（排除 `settings_page.py` / 入口文件），允许 `petcore.contracts.*`。**变异验证：给 `diagnostics.py` 加一行 `import PySide6`，该参数立刻红** |
| L1 | 用例名与断言语义相反 | 改名 `…falls_back_to_title_only_when_audio_metering_is_unavailable` |
| L2 | 多台播放器被同一条规则挡下时理由刷屏 | `_note()` 去重；新增用例断言只出现一条 |
| L3 | 缓存命中后 `score` 丢失（重启即丢诊断信息） | 缓存里存 `score`，`CACHE_VERSION` 1→2（旧缓存自然失效）；补读取 |
| L6 | `title_clean` 与主分支只做过一次性差分脚本 | 做成**常驻差分测试**（15 组清洗真值 + 7 组 titleformat 真值，两个模块都在仓库里） |

**未改的**：L4（`stop()` 不 join worker，重启最长约 3 秒不采样）——现有用例已固化该行为，
在 `start()/stop()` 注释里说明即可；L5（`_say_sung` 用 `TypeError` 探测端口是否支持
`subtitle`）——端口契约已固定带 `subtitle`，该分支只为旧版 mod 兼容保留；L7 ——
`audio_sessions.close()` 已有"谁建谁清"守卫（`_manager_thread == 当前线程` 才清缓存），
不成立。

## 5. 未验证 / 边界 / 明确不做

1. **未实机复现**：蓝牙/独占输出（音频会话不可见 → 按 SMTC 判）、播放器静音、切歌瞬间、
   多宠同时唱歌的观感。这些只有单测与静态论证（判定表逐行有用例）。
2. **视频站点标题否决刻意没做**：B 站 MV 标题同样带站点后缀，按标题否决会把正经音乐
   视频也挡掉；仍由"浏览器会话开关默认关闭"兜住。
3. **不做听声识曲**：用户已选"多源元数据"；`shazamio`/`dejavu` 需要 12 秒缓冲 + 联网或
   自建库，与 1 秒一拍的节奏不匹配（调研结论见 GitHub 侧笔记）。
4. **不做跨特性气泡仲裁**：歌词 `say(force=False)` 仍会被提醒/告警覆盖；本次只保证
   "say 失败不推进行号"。按 `petcore/AGENTS.md`「同一行只冒一次」，没有引入同句续期。
5. **`music_title_format` 只在窗口标题源生效**；SMTC 主源不需要它（元数据是结构化的）。
6. **Windows 以外**：`audio_sessions`/`window_source` 返回空，识别退化为 SMTC（与改前一致）。
