# petcore P3 收口：对话窗 / 看看屏幕 / 截图提问效果对齐（2026-10-22）

> 分支：`feat/petcore-vpet-architecture`；基线：`ac32c58`（P3 打包签名收尾）。
> 目标不是重写功能，而是把主分支已验证的**窗口与交互**搬进 Core，`ai.chat`
> 继续只负责 prompt/路由；新增 `ScreenAskPort` 把「截图提问」的 UI 与业务分开。
> 规格见 [`PETCORE-SPEC.md`](PETCORE-SPEC.md) §19，批次见
> [`PETCORE-ROADMAP.md`](PETCORE-ROADMAP.md) §22，改动史见 L039。

## 1. 修改文件说明

### 1.1 对话窗口（Core）

| 文件 | 改动（+ / −） | 为什么 |
|---|---:|---|
| `petcore/ui/chat/themes.py` | +244 / −0（新） | 移植主分支背景主题注册表：9 张 `assets/chat/*.jpg`、明暗面板、纱罩、取景框、cover/contain 偏移；源码树与 `_MEIPASS` 双路径。 |
| `petcore/ui/chat/markdown_view.py` | +85 / −0（新） | 移植主分支 Markdown→Qt 富文本：md4c GitHub 方言、禁原始 HTML、单换行保留、代码等宽、标题缩一档。 |
| `petcore/ui/chat/styles.py` | +162 / −0（新） | 把 `modern_styles.qss` 变成 Python 常量，避免打包漏 QSS；`@ACCENT@`/`@FONT_SIZE@` 占位符与 10–18 字号钳制。 |
| `petcore/ui/chat/icons.py` | +129 / −0（新） | 主分支工具栏图标的等价绘制（add/pin/minimize/exit/sidebar/send/stop/copy/attach/clear/remove/retry），不依赖 `pet.*`。 |
| `petcore/ui/chat/widgets.py` | +905 / −0（新） | 移植 `MessageBubble`、`ChatComposer`（含附件/拖放/粘贴图）、`ChatTitleBar`、`SessionListRow`、`SidebarScrim`；assistant Markdown、流式/错误/停止态、复制。 |
| `petcore/ui/chat/window.py` | +926 / −197 | 用现代双栏窗替换原极简窗口：960×700、无边框圆角、侧栏会话、头部状态、空态、浮动输入框、紧凑抽屉、边缘缩放、壁纸。 |
| `petcore/ui/chat/controller.py` | +138 / −40 | `record()` 走信号静默写会话（不建窗口）、`take_attachments()` 取走附件；窗口可选；`chat_always_on_top` 持久化。 |
| `tests/test_petcore_chat_ui.py` | +215 / −36 | 15 条行为 + 视觉结构测试（布局对象、QSS、抽屉、附件、record、字号/背景、置顶）。 |

### 1.2 截图提问（Core 框选 + 提问窗）

| 文件 | 改动（+ / −） | 为什么 |
|---|---:|---|
| `petcore/ui/screen/__init__.py` | +14（新） | 导出 `ScreenAskController` / `ScreenAskWindow` / `select_region`。 |
| `petcore/ui/screen/brand_icons.py` | +85（新） | DS 鲸鱼与鲸蛙素材加载；`pick_loading_icon()` 10% 鲸蛙彩蛋，素材缺失按序回退。 |
| `petcore/ui/screen/selection.py` | +235（新） | 真实框选：冻结帧、反向拖拽归一化、8px 门槛、DPR 裁剪、取消异常、可注入 grab/overlay 便于测试。 |
| `petcore/ui/screen/overlay.py` | +421（新） | 覆盖层：未框选不压暗、选区才压暗、白虚线+深色垫线、尺寸 chip、提示行、Enter/Esc、双击确认、「问问肥鱼/取消」动作条、外部关闭不挂起。 |
| `petcore/ui/screen/ask_window.py` | +591（新） | 主分支同款截图问答窗：无边框卡片、DS 鲸鱼标题、图片 chip、左右纯文本气泡、加载鲸鱼脉冲、输入行与等待态。 |
| `petcore/ui/screen/controller.py` | +197（新） | 每个 `(owner, slot)` 一个窗口；回调在后台线程，结果经信号回 GUI；失败/空回复/无接管都有可见状态。 |
| `tests/test_petcore_screen_ask.py` | +620（新） | 23 条：彩蛋抽取、窗口发送/等待/错误、控制器后台线程/历史/失败、覆盖层拖拽/取消/DPR 裁剪。 |

### 1.3 端口、Core 接线与 AI 扩展

| 文件 | 改动（+ / −） | 为什么 |
|---|---:|---|
| `petcore/contracts/screen.py` | +70 / −2 | `ScreenCapture.app_info`、稳定错误分类、`capture_region()`、`foreground_app()`、`ScreenAskPort`。 |
| `petcore/contracts/chat.py` | +15 / −0 | 公开 `record()` / `take_attachments()` 语义（静默历史、附件）。 |
| `petcore/contracts/host.py` | +2 / −1 | `HostPorts.screen_ask`。 |
| `petcore/platform/foreground.py` | +92（新） | 只读前台窗口的进程名/标题，给识屏提供低成本上下文。 |
| `petcore/platform/screenshot.py` | +27 / −6 | 抓屏附带 `app_info`；拆出 `grab_screen_image()` / `capture_from_image()` 供框选复用。 |
| `petcore/ui/ports.py` | +19 / −6 | `QtScreenPort.capture_region()` / `foreground_app()`；`build_ports` 接 `screen_ask`。 |
| `petcore/ui/app.py` | +23 / −2 | CoreHost 持有 `ScreenAskController`；`run_feature_command(slot=)` 对声明 `slot` 的扩展命令按发起宠派发。 |
| `petcore/config.py` | +33 / −0 | 持久化 `ai_vision_enabled`/`ai_temperature`/`ai_look_screen_auto_open`/`chat_always_on_top`/`chat_follow_pet`/`chat_background`/`chat_accent`（`ai_vision_enabled` 之前会被 normalize 丢掉）。 |
| `examples/petcore-mods/ai.chat/host/factory.py` | +371 / −81 | 看看屏幕：气泡答复 + `record()` 静默入历史 + 冷却/忙碌 + 自动打开开关；截图提问：框选 + `on_ask` 回调；对话提交去重当前问题、支持附件图。 |
| `examples/petcore-mods/ai.chat/mod.json` | 版本 1.0.0→1.1.0 | 行为变化，升级版本号。 |
| `tests/test_petcore_ai_mod.py` | +165 / −7 | 13 条：看看屏幕气泡/记录/开关、框选回调、历史去重、附件图、配置持久化。 |
| `tests/test_petcore_feature_command_slot.py` | +27（新） | 验证 `slot` 只传给声明参数的扩展命令。 |

### 1.4 文档与规则

| 文件 | 改动（+ / −） | 为什么 |
|---|---:|---|
| `petcore/AGENTS.md` | +13 / −2 | 对话窗唯一实现、`record()` 不得唤窗、看看屏幕口径、`ScreenAskPort` 边界、截图彩蛋独立、按宠派发。 |
| `docs/PETCORE-SPEC.md` | +27 / −5 | §16 更新聊天/截图口径；§19 冻结 Core/mod 边界。 |
| `docs/PETCORE-ROADMAP.md` | +15 / −1 | P3 状态与 §22 收口表。 |
| `docs/PETCORE-MAIN-PARITY-BACKLOG.md` | +3 / −2 | AI 对话 / 看看屏幕 / 截图提问三行更新为实际状态。 |
| `docs/PETCORE-LOG.md` / `PETCORE-LOG-INDEX.md` | L039 | 改动记录与索引。 |

## 2. 性能分析

环境：Windows，`QT_QPA_PLATFORM=offscreen`，`.venv/Scripts/python`（Python 3.12）。
探针脚本 `.scratch/ui/bench.py`（临时，不入库）：

```text
首次打开对话窗（ChatController.open）：23.7 ms
record() 追加一条静默历史        ：median 1.72 ms / p95 2.78 ms（n=20）
append_message 追加一条气泡      ：median 1.18 ms / p95 1.70 ms（n=20）
ScreenAskWindow.start(1920×1080)：median 13.99 ms / p95 15.31 ms（n=20）
ScreenAskWindow.begin_waiting    ：median 0.02 ms / p95 0.03 ms（n=50）
pick_loading_icon                ：<0.01 ms（n=200，素材已缓存）
foreground_app_info              ：median 0.02 ms / p95 0.03 ms（n=50）
```

- **稳态开销**：对话窗没有新增定时器；流式仍由 `token/done/error` 信号 + 50ms 合帧
  刷新。壁纸只在窗口 resize 时重新缩放，`paintEvent` 每帧只 draw 缓存 pixmap。
- **新增路径成本与频率**：`record()` 每次看看屏幕 2 次（用户行 + 回答行），约 3.4ms
  总计；`ScreenAskWindow.start` 每次截图提问 14ms，只在用户点一次时发生；
  `pick_loading_icon`/`foreground_app_info` 都是微秒级。
- **系统调用 / 网络 / 磁盘 / 线程**：对话窗与截图窗不新增网络；图片仍只在内存。
  截图提问每次发送起一个后台守护线程（Core），回调返回后结束；看看屏幕同样一条
  短线程。`record()` 落盘复用 `SessionStore.save()` 的原子写（每次看看屏幕 2 次小
  JSON 写，与主分支同步对话记录同级）。
- **内存**：截图问答窗持有本次 PNG（1920×1080 白图压缩后 8.6KB，真实桌面图通常
  数百 KB）直到下一次 `open()` 覆盖；对话窗只持消息文本与当前壁纸缩放图。没有
  跨窗口的图片缓存增长。
- **未测**：真实桌面框选的覆盖层绘制帧率、真实 4K/双屏 DPR 下的裁剪延迟；真实
  API 首包延迟与主分支一致，未在本轮改动传输层。

## 3. 实机运行记录

本机真实环境（Windows，1280×800 @1.5），不是 CI：

1. **测试门禁**

```text
$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
    tests/test_petcore_*.py tests/test_architecture.py \
    tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
1058 passed in 41.05s

$ .venv/Scripts/ruff check pet/ tests/ petcore/
All checks passed!

$ QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m petcore --check
exit 0（diagnostics=[]、menu_template=json）
```

2. **视觉渲染**（offscreen `grab()`，临时脚本 `.scratch/ui/render_chat.py` /
   `render_ask.py`）：

- 对话窗 960×700：左侧 `deepseek-sidebar`（品牌、开启新对话、会话行）、右侧
  `chat-main-header`（标题/状态/置顶/最小化/关闭）、右对齐用户气泡、Markdown
  助手气泡、底部浮动输入框与圆形发送键；CJK 在 offscreen 下显示为方块
  （无 CJK 字体），布局与配色正常。
- 截图问答窗 380×480：DS 鲸鱼标题、隐私提示、图片 chip、蓝色用户气泡、底部
  加载鲸鱼 + 状态文字、输入行与发送键；`loading_icon()` 返回 512×512 鲸蛙/鲸鱼。

3. **真实扩展流程**（`tests/test_petcore_ai_mod.py`，真实 Qt 事件循环 + 假 API）：

- 看看屏幕：气泡先「让我看看…」，完成后气泡答复；`record()` 写入
  `（看看屏幕）code.exe | main.py` 与回答；默认不 `open`，打开
  `ai_look_screen_auto_open` 后才 `open(pet_slot=2)`。
- 截图提问：`capture_region(pet_slot=2)` → `ScreenAskPort.open`；`_on_ask` 首轮消息
  带 `data:image/png;base64,…`，后续轮次复用历史并把图挂在第一条 user 消息上。
- 对话提交：控制器已追加本轮 user 消息时，mod 不再重复发送同一句；附件图进入
  multimodal 消息。

4. **未做的实机验证**（如实登记）：真实 DeepSeek/视觉模型端到端（无可用密钥）、
   真实桌面拖选/框选（只跑了 offscreen 事件循环路径）、安装包重出与签名（本轮未改
   构建链，沿用 `ac32c58` 的签名流程）。
