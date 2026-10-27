# PR 报告：语音全链路 + champion 彩蛋 + 关于页致谢体系（2026-10-27）

> **基线**：`3bfe193c`（分支 `feat/petcore-vpet-architecture` 的 HEAD；worktree 在本批开始前已有未提交改动）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-27
> **范围**：新增 21 个文件（实现 11 / 测试 8 / 数据 2）+ 修改 26 个文件（实现 16 / 测试 3 / 文档 7）
> **关联**：`docs/SETTINGS-CHANGE-GATES.md`（2026-10-27 记录）、`docs/PETCORE-LOG.md` L106

## 一、核心特性

一句话：让 petcore 的「说话」真正可用（含本地部署模型），并给关于页补上完整的致谢体系
（作者、贡献者、特别鸣谢、issue/PR 协作者、B 站粉丝、签名），同时把「自言自语」变成
会出声、偶尔连续说 5 句 champion 台词的彩蛋。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 语音页 | 新侧边栏「语音」：后端链/音色/语速/音量/缓存/试听 + 本地模型 + 在线 Key + 清缓存 |
| 2 | 本地 TTS | 新 `local` provider：OpenAI 兼容 `/v1/audio/speech` 或可配路径的 `{text,voice,speed}`；强制直连 |
| 3 | 自语/点击出声 | `self_talk_voice_enabled`、`click_talk_voice_enabled` 默认开；朗读失败不影响气泡 |
| 4 | champion 彩蛋 | 8% 概率连说 5 句（英文主文案 + 中文副标题），`say_sequence` 多气泡队列 |
| 5 | 关于页致谢 | 六个可折叠区：作者账号（抖音 @張墨林）、贡献者、特别鸣谢、issue/PR、B 站粉丝、签名 |
| 6 | 粉丝分页/搜索 | 3929 人只渲染当前 60 条；搜索不联网；打开关于页后台刷新一次（总数变化/超过 24h 才拉全量） |
| 7 | 签名 | 昵称 + 手写签名，固定 `<data_root>/community/signature.png`，全局唯一、覆盖式保存 |
| 8 | Quark | 「夸克网盘」改为 `https://pan.quark.cn/s/68fc681ae486` |

**红线 / 不变量**：随包名单只读、失败不覆盖；SESSDATA/API Key 只进钥匙串；本地 TTS 不走系统
代理；新的 `say/show_image/隐藏` 取消多气泡队列；隐藏的桌宠不说话。

## 二、修改文件说明

> worktree 在本批开始前已有未提交改动（分支既有工作）；下表「修改」行数是**该文件当前
> `git diff --numstat` 的累计值**，不是本批独有行数。新增文件行数精确。

### 实现（新增）

| 文件 | 行数 | 改动意图 |
|---|---|---|
| `petcore/community/__init__.py` | +71 | 导出致谢数据模型/服务 |
| `petcore/community/model.py` | +352 | 解析、静态/动态合并、粉丝过滤分页、登录名/时间戳规范化 |
| `petcore/community/store.py` | +192 | 随包 JSON 读取、运行期缓存原子写、签名 PNG/meta |
| `petcore/community/service.py` | 357 | 装载/刷新策略（含 `known_total()` 与 stat 口径）、B 站凭据、签名、失败保留 |
| `petcore/net/github.py` | +138 | 贡献者（1 请求）+ issue/PR 作者（≤6 页） |
| `petcore/net/bilibili.py` | 206 | 免登录粉丝总数（缺 `follower` 报 protocol，不造假 0）；SESSDATA 拉全量；`-352` → auth；分页/预算 |
| `petcore/ui/settings/page_voice.py` | +722 | 语音设置页（差异写回、密钥、试听、缓存） |
| `petcore/ui/settings/folds.py` | +58 | `CollapsibleSection`（标题按钮 + SettingsCard） |
| `petcore/ui/settings/signature_pad.py` | +322 | 手写画布（归一化笔迹）、PNG 渲染、保存/预览/删除 |
| `petcore/ui/settings/credits_job.py` | +91 | 守护线程刷新 + 信号；取消只断信号 |
| `petcore/ui/settings/page_about_thanks.py` | 578 | 六个折叠区、粉丝分页/搜索/凭据、刷新状态、3948/3950 双数字说明 |
| `scripts/fetch_community_credits.py` | 181 | 生成 `petcore/community/data` 快照；partial 拒绝写入；保序去重后写 `total`；Cookie 只从环境/文件读 |

### 实现（修改）

| 文件 | 增/删（累计） | 改动意图 |
|---|---|---|
| `petcore/net/tts.py` | +179 / −0 | `local` provider + `local_synthesize` + 分派 + JSON/base64 解析 |
| `petcore/speech/service.py` | +91 / −6 | local 可用性/音色/后缀/flavor；`optional_secrets` 不强制 Key |
| `petcore/config.py` | +108 / −5 | 8 个语音键（7 个 `speech_local_*` + `speech_sapi_voice`）、4 个自语/点击语音与彩蛋键、归一化；**不 import urllib**（架构门） |
| `petcore/ui/settings/dialog.py` | +44 / −5 | 注册「语音」页、图标/深链 key |
| `petcore/ui/settings/page_about.py` | +80 / −6 | 始终建两个分页、致谢面板、诊断快照加 speech/community |
| `petcore/ui/settings/base.py` | +69 / −16 | `reveal_text` 展开折叠区、优先折叠区里的命中 |
| `petcore/ui/settings/style.py` | +56 / −2 | 折叠头/粉丝名/签名画布/协作者列表 QSS |
| `petcore/ui/icons.py` | +64 / −6 | `voice` 字形（喇叭 + 声波） |
| `petcore/contracts/host.py` | +9 / −1 | `PresentationPort.say_sequence(on_show=...)` |
| `petcore/ui/app.py` | +103 / −1 | `_PresentationAdapter.say_sequence`；`CoreHost.community` |
| `petcore/ui/pet_window.py` | +189 / −16 | `say_sequence` 定时器链 + 取消点（say/show_image/隐藏/关闭） |
| `petcore/ui/bubble.py` | +25 / −0 | `full_text()` 只读访问器（测试/诊断） |
| `petcore/builtin/features/fun.self-talk/host/factory.py` | +175 / −7 | 语音、champion 彩蛋、页面三行 |
| `petcore/builtin/features/fun.click-talk/host/factory.py` | +67 / −3 | 点击朗读、页面一行 |
| `petcore/builtin/features/fun.self-talk/mod.json` | +4 / −2 | 1.0.0 → 1.1.0 |
| `petcore/builtin/features/fun.click-talk/mod.json` | +4 / −2 | 1.0.0 → 1.1.0 |
| `petcore/builtin/features/tool.links/host/factory.py` | +1 / −1 | 夸克链接换成用户的分享地址 |
| `petcore/net/http.py` | +1 / −1 | 新增 `direct_only`（本地请求失败也不切代理） |
| `petcore/contracts/speech.py` | +6 / −2 | `rate/volume` 默认 None = 沿用全局语音页设置 |
| `dsh-pet-core.spec` | +1 / −1 | datas 增加 `petcore/community/data`（随包致谢/粉丝快照） |
| `scripts/build_petcore.ps1` | +3 / −0 | PyInstaller `--add-data` 同步社区数据目录 |

### 测试

| 文件 | 行数 | 覆盖 |
|---|---|---|
| `tests/test_petcore_speech_local.py` | +350（新） | provider 声明、两种协议、endpoint 校验、缓存键、配置归一化 |
| `tests/test_petcore_settings_voice.py` | +331（新） | 后端切换、音色、本地设置、试听、密钥、缓存、脏/回滚 |
| `tests/test_petcore_say_sequence.py` | +185（新） | 5 条推进/打断/隐藏/图片取消、adapter 闸门与岛消息 |
| `tests/test_petcore_community_store.py` | +176（新） | 解析/合并/搜索分页/原子写/签名/随包只读 |
| `tests/test_petcore_community_service.py` | 413（新） | 刷新策略、失败保留、partial 不覆盖、cookie、签名；重名占位/stat 口径/老缓存自愈 |
| `tests/test_petcore_net_credits.py` | 211（新） | GitHub/B 站解析、限流、truncated、`-352`、Cookie 不泄漏、粉丝数缺字段不造假 0 |
| `tests/test_petcore_about_thanks.py` | 358（新） | 六区、折叠、粉丝分页/搜索、刷新合并、签名覆盖、诊断 `fans_total` |
| `tests/test_petcore_community_bundle.py` | 88（新） | 随包数据验收：非空/去重/幂等/total 关系/时间窗/UTF-8 无 BOM/两个打包入口 |
| `tests/test_petcore_credits_job.py` | +80（新） | 刷新任务正常信号、取消后不发、`cancel_all` |
| `tests/test_petcore_self_talk.py` | +214 / −1 | 彩蛋 0/100、5 条序列、自语/点击语音开与关 |
| `tests/test_petcore_settings.py` | +50 / −1 | 9 页标题、About 5 个分页顺序 |
| `tests/test_petcore_about_page.py` | +2 / −0 | 关于页始终有「致谢」分页 |

### 数据

| 文件 | 行数 | 说明 |
|---|---|---|
| `petcore/community/data/credits.json` | +745（新） | 生成于 2026-10-27：17 位贡献者 / 124 位 issue·PR 协作者 + 4 位作者账号 + 4 条特别鸣谢 |
| `petcore/community/data/fans.json` | 3956（新，86KB） | 2026-10-27 用浏览器登录态抓的全量粉丝名单：3950 条记录 → 去重后 3948 个用户名（3 条「账号已注销」占位合并为 1），`total=3950`（与 `x/relation/stat` 的 `follower` 同源），`vmid=293026389` |

### 文档

`docs/PETCORE-SPEC.md`（+64/−15）、`docs/PETCORE-ARCHITECTURE.md`（+48/−4）、
`docs/PETCORE-MAIN-PARITY-BACKLOG.md`（+6/−6）、`docs/SETTINGS-CHANGE-GATES.md`（+58/−0）、
`CONTEXT.md`（+29/−8）、`README.md`（+2/−1）、`petcore/AGENTS.md`（+91/−12）。

### 未改动（刻意）

- `pet/`（legacy）不动：本批只改 petcore，legacy 的自语语音/作者账号入口保持原样。
- `voice.chime` 的安装默认值与调度口径不动：它本来就走 `HostPorts.speech`，新语音页只统一下
  后端/音色。
- `dsh-pet-core.spec` 与 `scripts/build_petcore.ps1` 各加一行 `petcore/community/data`；
  数据随包，`assets/` 的媒体规则不变。

## 三、实现要点

- **多气泡**：`PresentationPort.say_sequence(items)`，`PetWindow` 用一条单次 `QTimer` 推进，
  每条 `duration_ms` + 200ms 间隔；`say()/show_image()/set_visible(False)/shutdown()/closeEvent()`
  统一 `_cancel_say_sequence()`。`_advance_say_sequence()` 直接调 `bubble.show_text`，避免
  自己触发 `say()` 的取消。端口缺失时 feature 回退为单条合成气泡。
- **本地 TTS**：`local_synthesize` 只做一次请求；URL 由 `local_url` 校验（http/https、
  非空主机）；`fetch_url(..., prefer_direct=True, allowed_schemes=("http","https"))`；
  响应支持音频字节或 JSON 的 `audio|data|audio_base64`。缓存 flavor 追加
  `endpoint/protocol/path/model/format`，后缀由 `speech_local_format` 决定。
- **社区数据**：`Credits` 静态项永远取随包；动态项取「较新且非空」的一份。
  `CommunityService.refresh` 先查免登录粉丝总数：总数不变且缓存新鲜时**不做** 79 页全量
  （比较的是持久化的 B 站口径 `total`，不是去重后的名字数）；
  全量 `partial=True` 时只报 `timeout`，不写缓存、不覆盖随包。刷新是守护线程，只写缓存，
  GUI 完成后 `reload()`。
- **关于页**：`AboutPage` 始终建「版本与诊断 / 致谢」两个页内分页，再嵌入特性页；
  致谢面板的折叠区用 `CollapsibleSection`；`reveal_text` 命中折叠区里的文案时先展开，
  并优先选折叠区里的命中（避免只滚到顶部的摘要行）。
- **签名**：笔迹存归一化坐标，渲染 800×300 透明 PNG；保存一次写 PNG + `signature.json`；
  只写 `<data_root>/community`，不参与设置窗回滚。
- **默认值**：语音/彩蛋默认开，但 `self_talk_enabled` 本身仍默认关——用户启用自语后才出声；
  彩蛋概率默认 8%，0% 表示永不触发。

## 四、性能分析

**方法（可复现）**：`.venv/Scripts/python .scratch/bench_thanks.py`（200/200/200/1000 次）
环境：Windows 11 10.0.26200、Python 3.12.10、PySide6 6.12.0、offscreen。

| 指标 | 实测（合成数据 3929 名） | 归属 |
|---|---|---|
| 关于页构造（缓存数据、无网） | median 12.09ms / p95 17.20ms | 新增（目标 p95 < 250ms） |
| 致谢面板构造（17 贡献者 + 124 协作者 + 3929 粉丝） | median 10.70ms / p95 15.78ms | 新增（目标 < 30ms） |
| 粉丝翻页（60 条） | median 3.80ms / p95 6.41ms | 新增（目标 < 15ms） |
| 粉丝搜索（3929 条） | median 0.65ms / p95 1.11ms | 新增（目标 < 3ms） |
| 致谢面板内存增量 | 0.26MB | 新增（目标 < 5MB） |
| 缓存命中语音合成 | 既有 `SpeechCache.hit` < 1ms | 既有 |

**随包真实快照复测**（`.venv/Scripts/python .scratch/bench_thanks_real.py`，3948 粉丝 /
17 贡献者 / 124 协作者，200/200/200/1000 次，同环境）：

| 指标 | 实测 | 对比合成数据 |
|---|---|---|
| 关于页构造 | median 24.62ms / p95 42.43ms | +12.5ms（真实用户名更长，行内换行测量更贵） |
| 致谢面板构造 | median 12.91ms / p95 21.27ms | +2.2ms |
| 66 页随机翻页 | median 5.99ms / p95 8.93ms | +2.2ms |
| 3948 条搜索 | median 0.78ms / p95 1.20ms | +0.13ms |
| 面板内存增量 | 0.26MB | 持平 |

同机复测（第二轮审查修复后，机器上还跑着测试进程）：关于页 30.29/47.53ms、致谢面板
13.71/22.95ms、66 页随机翻页 6.75/10.03ms、3948 条搜索 0.79/1.32ms、内存 0.26MB——
与上表同量级，差异来自同时运行的测试进程，结论不变。

**结论**：
① 稳态开销：关于页/语音页无常驻定时器；粉丝区只保留当前页 60 个 QLabel，3948 条名单
只在内存（约 0.26MB）；打开设置窗不触发网络，只有关于页 `showEvent` 且超过 10 分钟冷却才
起一次后台刷新。
② 新增路径成本：一次自动刷新最多 1 次粉丝总数 + 5 次 GitHub（contributors 1 + issues 4）；
粉丝全量只在「总数变化 / 超过 24h / 手动刷新」时发生，约 79 次请求、共享 60 秒预算。
③ 新系统调用/网络/线程：刷新新增 1 条守护线程（无刷新时不创建）；语音合成沿用既有
`petcore-speech` 单 worker；本地 TTS 是 1 次 HTTP POST，无新子进程。
④ 内存/缓存：粉丝名单 3948 条约 0.26MB；语音缓存沿用既有上限（默认 200 文件，可调
10–2000）；GitHub/粉丝缓存各一个 JSON，原子覆盖。
⑤ 随包体积：`fans.json` 86KB、`credits.json` 约 24KB，合计 <0.2% 安装包。

## 五、实机运行记录

1. **静态检查**：`.venv/Scripts/ruff check pet/ tests/ petcore/` → `All checks passed!`
2. **headless 自检**：`.venv/Scripts/python -m petcore --check` → 输出完整 JSON，
   `strict.enabled=false`、`problems=[]`。
3. **真实 GUI 启动**：`.venv/Scripts/python -m petcore --root .scratch/gui-app-root --verbose`
   → 日志 `2026-10-27 01:50:52,333 INFO petcore.cli: starting petcore 0.2.0`，进程正常
   创建窗口与锁文件；随后手动结束测试实例（未残留进程）。
4. **真实平台渲染**：`.venv/Scripts/python .scratch/gui_smoke.py` → 生成
   `.scratch/about_thanks.png`、`about_thanks_open.png`、`about_thanks_full.png`、
   `voice.png`；确认作者账号（抖音 @張墨林）、17 位贡献者、特别鸣谢 4 条、124 位协作者、
   粉丝区与签名区均可见，折叠头为左对齐文本而不是默认按钮。
5. **本地模型**：未在本机启动真实本地 TTS 服务；两种协议用注入传输验证请求形状与
   音频解析，**真实发声未验证**（见 §七）。
6. **B 站粉丝快照（2026-10-27 补抓，真实数据）**：用户装好 Kimi WebBridge 浏览器扩展后，
   在 `space.bilibili.com/293026389/relation/fans` 页面内用同源 `fetch` 逐页抓
   `x/relation/fans`：79 页 × 50，`0` 报错，取回 3950 条记录 → 去重后 3948 个用户名，
   写进 `petcore/community/data/fans.json`（86KB）。未登录时同一接口返回 `-352`（早前实测），
   所以这条路径必须带登录态，CI 无法复现。
7. **真实数据渲染**（windows 平台，`.scratch/shot_thanks_real.py` →
   `.scratch/shots/thanks_real_fans_p1.png` / `_search.png` / `_p66.png`）：状态行显示
   「贡献者 17 位 · issue/PR 协作者 124 位 · 粉丝 3948 位 · 名单 2026-10-27」；第 1/66 页
   60 个用户名 4 列排布；搜「鱼」筛出 90 位、分 2 页；第 66 页正常；SESSDATA 行与签名区
   无重叠。搜索框输入的中文可正常显示（默认调色板 `#ffffff`）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `.venv/Scripts/ruff check pet/ tests/ petcore/` | All checks passed |
| 全量 petcore | `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py -q` | **2160 passed in 278.84s（0:04:38）**（第二轮审查修复后终跑；粉丝快照 + `total` 修复时为 2154/281.43s；首次实现阶段 2148/183.37s） |
| 全仓 | `.venv/Scripts/python -m pytest -q` | 10652 passed, 19 skipped in 1375.53s（0:22:55）——跑在本批最后几条社区/数据改动之前，那几条都在 petcore 域内，已由上面的全量 petcore 覆盖 |
| 关于/语音/社区聚焦 | `pytest tests/test_petcore_about_thanks.py tests/test_petcore_settings_voice.py tests/test_petcore_community_*.py tests/test_petcore_net_credits.py tests/test_petcore_speech_local.py tests/test_petcore_say_sequence.py tests/test_petcore_self_talk.py tests/test_petcore_credits_job.py -q` | 131 passed（语音/自语/时序/社区/致谢/架构）+ 2 passed（刷新任务）；快照批次后 `community_store/service/bundle/about_thanks` 聚焦 40 passed |
| 架构红线 | `pytest tests/test_petcore_architecture.py -q` | 通过（曾抓到 `config.py -> urllib.parse`，已改为手写前缀校验） |
| 文档/报告门 | `pytest tests/test_petcore_docs.py tests/test_pr_report_discipline.py -q` | **317 passed**（本机实测；先前记录的 326 是另一个检查集的数字，以这条命令的输出为准） |
| headless 自检 | `python -m petcore --check` | 通过 |
| 断言有效性 | 变异：`self_talk_champion_chance` 改 0 / `merge_fans` 反向 / `partial` 允许写入 | 对应测试转红（人工执行） |

> 全仓 `pytest -q` 已通过（10652 passed / 19 skipped）；此后本批又追加了 B 站粉丝快照、
> `Fans.total` 变更判断修复、`fans_total` 诊断字段这几处，全部落在 petcore（community /
> about 诊断）与随包数据内，已由 2160 passed 的全量 petcore 与上面的聚焦用例覆盖，因此
> 没有重跑 23 分钟的全仓。

## 七、独立审查与修复

实现完成后开了一个只读子代理做代码审查（线程/取消、Qt 生命周期、Cookie/Key 泄漏、缓存键、
刷新策略、搜索/折叠）。**P1/P2 全部修复并补测试**：

| 级别 | 发现 | 修复 |
|---|---|---|
| P1 | 隐藏桌宠仍按定时朗读自语/彩蛋 | `_speak`/`_play_champion` 按 `say` 结果与 `visible()` 闸门；新增 2 例隐藏不出声 |
| P1 | 「有没有新粉丝」拿去重后的名字数比 B 站 `total`，真数据天然差 2 → 配了 SESSDATA 的用户每次开关于页都重拉 79 页 | `Fans.total` 持久化 B 站口径人数（`parse_fans`/`save_cached_fans`/`fans.json`），`refresh` 用 `known_total()` 比较；`fans_changed` 改为集合比较；新增 2 例 |
| P1 | 语音页语速/音量滑条没人读 | `SpeechRequest.rate/volume` 默认 None，服务端用 `speech_rate/volume` 填充；新增 1 例 |
| P2 | 彩蛋开头把 5 条语音全塞进队列 | 改 `say_sequence(on_show=…)` 逐条朗读；测试改为按条断言 |
| P2 | 保存后 `dirty()` 不消（音色截断 64 字） | `confirm_save` 同步音色控件；新增 1 例 |
| P2 | `_on_job_done/_on_job_failed` 先碰控件后判 disposed | 守卫提前；`_clear_layout` 先 `setParent(None)` |
| P2 | 刷新线程与 Qt 退出无协调 | `cancel_all()`（守护线程 + 0.5s join）在 `quit_app`/`aboutToQuit` 调用；无 QApplication 时不 emit |
| P3 | SAPI 与 Edge 共用音色键 | 新增 `speech_sapi_voice` |
| P3 | 无 SESSDATA 的整段 Cookie 被当凭据保存 | 保存前校验并只存 SESSDATA 值；新增 1 例 |
| P3 | `prefer_direct` 失败仍会走代理 | `fetch_url(direct_only=True)`；本地请求只直连 |
| P3 | endpoint 带 `?`/`#` 拼出错误 URL | 归一化拒绝；新增 1 例 |
| P3 | `reveal_text` 展开所有命中且按旧几何滚动 | 只展开选中命中，滚动延后一拍 |
| P3 | 每次开关于页都打 5 次 GitHub | credits 6h TTL 真正生效；新增 1 例 |
| P3 | 半程/结尾多次 reload memo | 只在所有请求结束后 reload 一次，文档同步 |

### 第二轮审查（B 站真数据到位后，另一个只读子代理）

| 级别 | 发现 | 修复 |
|---|---|---|
| P2 | 比较用 `x/relation/stat` 的 `follower`，持久化用 `x/relation/fans` 的 `total`；两接口差 1 就「拉完仍不等」永久循环 | `_refresh_fans(..., stat_total)` 优先记录 stat 的数，名单接口 total 只兜底 |
| P2 | 名单接口缺 `total` → `total or 0` 被夹到名字数，等于把上一条的缺陷原样恢复 | 同上（改用 stat）；`parse_fans` 的夹取只用于防御坏数据 |
| P2 | `fetch_fan_count` 缺 `follower` 时静默返回假 `0`，每次都触发全量 | 改为必填校验→`NetworkError(reason=protocol)`；补 3 例参数化测试 |
| P2 | `--fans` 脚本不去重，按文档重跑会写出 3950 条并让验收测试误报「normalize 失败」 | 脚本改为与 `parse_fans` 同样的保序去重；测试报错文案拆开 |
| P3 | `fans_changed` 比元组，页序抖动也算变了 | 改为集合比较；删掉返回名字数的旧方法 `fan_total()` |
| P3 | 验收测试放过「total 偏大/快照被截断/未来时间/normalize 不幂等/打包漏项」 | 加 `total-len(names)∈[0,20]`、±1 年时间窗、`normalize` 幂等、spec 与 ps1 双打包入口断言；补「老缓存自愈」「stat 口径优先」两例 |
| P3 | 同一页出现 3948 与 3950 两个数 | 粉丝数与状态行都补「· B 站显示 3950 位（含同名占位）」 |

未修（有意）：折叠时不在设置全局搜索里索引 3948 个粉丝名——粉丝区自带搜索框覆盖全部名单，
把 3948 个 `QLabel` 常驻会违背本页的性能目标。

## 八、已知限制与后续

- **粉丝快照是一个时间点**：`petcore/community/data/fans.json` 抓于 2026-10-27 08:43，
  之后新关注的粉丝不会自动进随包文件；运行期在「关于页 → 致谢 → 粉丝 → B 站登录凭据」
  粘贴 SESSDATA 后点「刷新名单」可增量更新本机缓存（只进钥匙串），或维护者运行
  `python scripts/fetch_community_credits.py --fans` 重新生成随包快照。抓取必须带登录态，
  CI 不可复现。`tests/test_petcore_community_bundle.py` 会拦住「快照退化成空占位」。
- **本地 TTS 真实发声未验证**：没有在本机启动 Kokoro/GPT-SoVITS/CosyVoice 服务；已验证
  请求形状、错误分类、缓存键与回退。真实音频播放属于用户环境验收项。
- **GitHub 未登录限流**：60/h；自动刷新最多 5 次请求，失败只提示原因并保留旧数据。
- **粉丝名单是第三方数据**：会随仓库/安装包分发（用户确认）。
- **非 Windows 平台**：本地模型与 UI 走通用 Qt/HTTP；未在 macOS/Linux 实机验证。

## 九、风险与回滚

- 新增配置键均有默认值与归一化；本地 endpoint 为空时自动「未配置」并回退，不会阻断启动。
- 回滚：`git revert` 后新键留在 `config.json` 会被当作未知键写入 `extra`，不影响旧代码；
  `<data_root>/community/` 与语音缓存是独立数据，可手动删除。
- 语音默认开启只影响已经启用「自言自语/点击台词」的用户；关闭对应开关即恢复只冒泡。
