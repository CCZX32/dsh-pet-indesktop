# PR 报告：截图蒙层全灰修复 + 深度思考/联网搜索（P7）

- **分支**：`feat/petcore-vpet-architecture`
- **日期**：2026-10-22
- **范围**：`petcore/api`、`petcore/net`、`petcore/contracts`、`petcore/ui/chat`、
  `petcore/ui/screen`、`petcore/platform/screenshot.py`、`petcore/config.py`、
  `examples/petcore-mods/ai.chat`

## 摘要

1. **修复截图提问整屏发灰**：`QScreen.grabWindow(0)` 在 Qt6 返回 `QPixmap`，
   旧代码把它当 `QImage` 交给 `QPainter.drawImage`，`paintEvent` 首行抛
   `TypeError`，覆盖层什么都没画 → 用户看到默认灰底；裁切/编码恰好走
   `QPixmap.copy/save`，所以「框出来的图正常」。现在 `grab_screen_image()`
   统一 `toImage()` + `devicePixelRatio=1.0`，覆盖层再兜底一次。
2. **补齐深度思考**：`build_payload()` 发送 `thinking` / `reasoning_effort`；
   `stream_chat(on_reasoning=)` 拆出 `reasoning_content`，不混进正文；
   只出思维链且 `finish_reason=length` 时报截断；聊天窗折叠面板与按会话回显接通。
3. **补齐联网搜索**：新增 `petcore/net/websearch.py`（百度 / DuckDuckGo 免 Key，
   博查 / Tavily 需 Key；免 Key 互为兜底）；`stream_chat(web_search=)` 先跑
   非思考 planner（`web_search` / `fetch_url`，≤3 轮 × ≤4 次），资料注入 system，
   状态行进气泡；搜索 Key 只进钥匙串。
4. **设置入口**：AI 对话设置页新增「深度思考」「联网搜索」两个分区，
   思考强度只在开启时显示，Key 行只在需 Key 的引擎显示。

## 修改文件说明

| 文件 | 增/删 | 改了什么 + 为什么 |
|---|---|---|
| `petcore/platform/screenshot.py` | +17/−4 | `grab_screen_image()` 接受 `QPixmap`/`QImage`，`toImage()` 后 DPR 复位 1.0。**为什么**：Qt6 真实抓屏返回 QPixmap，覆盖层 `drawImage` 不接受它（灰屏根因）。 |
| `petcore/ui/screen/overlay.py` | +9/−1 | 构造函数用 `_as_image()` 兜底非 QImage 输入。**为什么**：第三方/测试注入 QPixmap 时不再让 paint 崩掉。 |
| `petcore/config.py` | +29 | 新增 6 个全局键及默认值/归一化：`ai_thinking`、`ai_reasoning_effort`、`ai_web_search`、`ai_web_engine`、`ai_web_results`、`ai_web_fetch`。**为什么**：思考/联网可配置且非法值有稳定回落。 |
| `petcore/contracts/api.py` | +17 | 新增 `WebSearchOptions`；`ApiPort` 加 `on_reasoning/on_status/thinking/reasoning_effort/web_search` 与搜索 Key 读写、`credentials_available()`。**为什么**：mod 只能拿纯数据与端口；钥匙串降级要在界面说明。 |
| `petcore/contracts/chat.py` | +8 | `ChatPort` 加 `reasoning()` / `status()`。**为什么**：思维链与检索进度是聊天窗的一部分。 |
| `petcore/api/chat.py` | +417/−10 | `thinking_payload()`、`_extract_delta()` 三元组、`ChatResult.reasoning`、`ChatTruncated`、`research()`、`inject_search_context()`、`_post_json()`、`_run_tool()`；`stream_chat()` 先检索后回答。**为什么**：DeepSeek 思考模式带 tools 要求回传历史思维链，必须拆成独立非思考 planner 轮。 |
| `petcore/net/websearch.py`（新） | +407 | 四引擎检索、百度/DDG 解析器、`fetch_page_text()`、稳定错误分类、代理兜底（复用 `net.http.urlopen`）。**为什么**：联网搜索是网络能力，只能放 core。 |
| `petcore/ui/ports.py` | +43/−1 | `CoreApiPort` 透传新参数；从钥匙串取搜索 Key；`web_search_key_status()` / `set_web_search_key()`。**为什么**：设置页与 mod 都不得直接读写密钥存储。 |
| `petcore/ui/chat/controller.py` | +48/−1 | `reasoning_received` / `status_received` 排队信号；窗口不存在时丢弃；`_apply_done()` 把 `reasoning`/`activity` 落进 assistant 记录。**为什么**：worker 线程不能碰控件；重开会话要能回显。 |
| `petcore/ui/chat/window.py` | +38/−1 | `append_reasoning()` / `add_activity()` / `last_thinking()`；`load_messages()` 调 `restore_thinking()`；`finish_stream()` 记录思维链。**为什么**：UI 骨架早已存在但无调用方。 |
| `petcore/chat/session_store.py` | +12/−3 | `from_dict()` 保留可选 `reasoning` / `activity`；`messages` 类型放宽为 `Any`。**为什么**：旧会话（无字段）照常加载，新会话能回显。 |
| `examples/petcore-mods/ai.chat/mod.json` | +1/−1 | 版本 1.2.0 → 1.3.0。**为什么**：设置页与运行时行为都变了，升级/市场要能区分。 |
| `examples/petcore-mods/ai.chat/host/runtime.py` | +42 | 读 6 个配置键；`_start()` 传 `thinking`/`reasoning_effort`/`on_reasoning`/`on_status`/`web_search`；视觉请求沿用思考设置。**为什么**：运行时只做编排，传输在 core。 |
| `examples/petcore-mods/ai.chat/host/settings_page.py` | +225 | 两个新分区 + 引擎/Key 可见性 + Key 存钥匙串 + 取消时控件复位 + 搜索关键词。**为什么**：设置是唯一入口且要能搜到行。 |
| `petcore/AGENTS.md` | +10 | 新增四条红线：思考/联网传输只在 core、截图冻结帧必须 QImage、进度只进已开窗口、搜索 Key 只在钥匙串。**为什么**：防止后续又把网络/窗口重写一遍。 |
| `docs/PETCORE-SPEC.md` | +31 | 新增 §20 P7 边界（思考 payload、planner 轮、Key、面板、冻结帧契约）。 | 
| `docs/PETCORE-MAIN-PARITY-BACKLOG.md` | +2/−2 | AI 对话行更新为 P7 部分收口；截图提问行记录灰屏根因与 HDR 未移植。 |
| `tests/test_petcore_screenshot.py` | +38/−2 | QPixmap → QImage/DPR=1 回归；`capture_screen` 接受 QPixmap。 |
| `tests/test_petcore_screen_ask.py` | +14/−1 | QPixmap 冻结帧必须画出底图（不是灰底）。 |
| `tests/test_petcore_api_chat.py` | +212/−2 | thinking payload 三态、reasoning 不进正文、截断、planner/注入/状态行、关闭零额外请求、搜索失败降级、取消跳过回答。 |
| `tests/test_petcore_websearch.py`（新） | +150 | 百度/DDG 解析、工具文本、免 Key 兜底、缺 Key 稳定错误、读页限长与类型拒绝。 |
| `tests/test_petcore_chat_ui.py` | +48 | 面板路由、会话落盘/磁盘回显、无窗口时不建窗。 |
| `tests/test_petcore_ai_mod.py` | +145 | 配置映射到端口参数、reasoning/status 到达 ChatPort、设置页 Key 走端口、可见性联动。 |

## 性能分析

环境：Windows 11，本机 `TM140VDXP02` 1280×800 逻辑 / DPR 1.5 / 冻结帧
1920×1200；Python 3.12.10、PySide6；`QT_QPA_PLATFORM=offscreen`（除抓屏探针）。

| 路径 | 实测 | 说明 |
|---|---|---|
| `grab_screen_image()` | **49.1 ms**（n=5，中位） | 含 `grabWindow` + `QPixmap.toImage()` + DPR 复位；只在用户点「截图提问」时触发一次，与改动前的抓屏同量级（转换本身是隐式拷贝）。 |
| `SelectionOverlay` 绘制 | **4.22 ms**（n=20，中位） | 整层 1920×1200 缩放绘制；改动前这条路径直接抛异常（0ms 但不可用）。 |
| `_extract_delta()` | **1.0 µs**（n=20000） | 每个 SSE 事件一次；新增读取 `reasoning_content` 的成本在噪声内。 |
| `inject_search_context()`（24k 字资料） | **<0.01 ms**（n=2000） | 只在开启联网且拿到资料时执行一次/回合。 |
| `build_payload()`（thinking 开启） | **0.6 µs**（n=5000） | 每回合一次。 |
| 百度免 Key 搜索 | **0.83 s**（真实网络，3 条） | 只在开启联网时发生，且由 planner 决定是否调用。 |
| DuckDuckGo 免 Key 搜索 | **40.80 s 后落到百度兜底** | 本机网络下 DDG 不可直连；与主分支「国内通常需要代理」一致。 |

- **稳态开销**：不开思考/联网时，多出的只有 `_extract_delta` 读一个键（1.0µs/事件）
  和 `build_payload` 的 0.6µs；没有新增定时器、线程或磁盘写入。
- **新增路径成本与频率**：联网每回合最多 1 次 planner 循环（≤3 轮 × ≤4 工具调用）；
  思考仅改 payload 与事件分流；两者都由用户设置显式开启。
- **系统调用/网络/磁盘/线程**：新增网络请求只在联网开启时发生（planner + 搜索 +
  读页），无新增磁盘写入；搜索 Key 读写走既有 keyring 适配器；线程仍是 mod 原有的
  每对话/每次识屏后台线程，没有新增常驻线程。
- **内存**：会话里的 `reasoning` 截断到 24,000 字、`activity` 最多 40 行 × 500 字，
  与正文的 24,000 字上限同量级；检索资料上限 24,000 字，仅在单次请求生命周期内存在。

## 实机运行记录

1. **真实抓屏与覆盖层**（`QT_QPA_PLATFORM` 未设置，真实 Windows 桌面）：

   ```
   screen TM140VDXP02 1280 800 dpr 1.5
   type QImage dpr 1.0 size 1920 1200
   overlay frame type QImage
   paint ok, sample #1d1f26
   ```

   结论：冻结帧是 QImage/DPR=1，覆盖层成功画出桌面内容（采样点是桌面深色，
   不是默认灰底 `#efefef`）。

2. **真实联网搜索**（未配置任何 Key，直接调 `petcore.net.websearch`）：

   ```
   baidu ok 3 0.83s
     - DeepSeek V4 预告 … https://www.douyin.com/video/7632201633845349682
     - … https://www.163.com/dy/article/KMJRFJQN05118I96.html
   duckduckgo ok 3 40.80s   # DDG 超时后由百度兜底返回
   ```

3. **全量门禁**：

   ```bash
   QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
     tests/test_petcore_*.py tests/test_architecture.py \
     tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
   # 1114 passed in 71.69s

   .venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods/ai.chat
   # All checks passed

   QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m petcore --check --out .scratch/p7-check.json
   # exit 0；version 0.1.0；diagnostics []；self_talk_images 24/24 可读
   ```

4. **未在本轮验证**（不要当成已通过）：

   - 真实 DeepSeek 思考模型的端到端思维链（需要用户 API Key，未消耗额度）。
   - 博查 / Tavily 的真实检索（无 Key）。
   - 真实桌面框选交互的肉眼验收（本机探针只验证抓帧与绘制；拖拽逻辑由
     offscreen 事件测试覆盖）。
   - HDR 屏冻结帧仍走 Qt `grabWindow`，未移植主分支 DXGI FP16 通道，颜色可能发灰。
   - 思考/联网设置是**全局**（与 `ai_model`/`ai_temperature` 一致），不是主分支的
     per-provider。
