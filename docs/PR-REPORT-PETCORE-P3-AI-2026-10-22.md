# petcore P3 收口：AI 对话、截图提问与三个全局热键

> **基线**：P3 账户提交 `5451b67`
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-22
> **范围**：流式传输、ChatPort/ChatWindow、截图端口、四条全局热键、菜单/设置、`ai.chat` 扩展
> **关联**：[交接计划](PETCORE-HANDOFF-PLAN-2026-10-22.md)、[功能矩阵](PETCORE-FUNCTION-MATRIX-2026-10-22.md)、[LOG L036/L037](PETCORE-LOG-INDEX.md)

## 一、核心特性

P3 的账户/余额与会话存储在 `5451b67` 已落地；本轮补齐剩余三块：

1. **流式对话**：`petcore/api/chat.py` 做 SSE、一次性 JSON 回退、取消、超时、代理兜底；
   `ApiPort.stream_chat()` 是 mod 唯一入口。
2. **聊天宿主**：`ChatPort` + `petcore/ui/chat/`（Markdown 流式合帧、停止/清空/历史、
   按 `(owner, slot)` 隔离），跨线程只用 Qt 信号。
3. **截图提问 + 热键**：`ScreenPort` 抓整屏到内存 PNG（不落盘），三条新全局热键与
   显示/隐藏并列。

**红线 / 不变量**：`petcore/chat/` 零 Qt、零网络；截图不写盘；worker 线程不碰控件；
热键失败必须可见；AI 的 prompt/路由在 mod，传输/窗口/密钥在 core。

## 二、修改文件说明

`git diff --numstat`（已跟踪文件）+ 新增文件行数：

| 文件 | 增删/行数 | 改动意图 |
|---|---|---|
| `petcore/api/chat.py` | 新 194 | SSE 解析、一次性回退、取消、错误分类 |
| `petcore/contracts/chat.py` | 新 32 | `ChatPort` 协议（含 `history`/`on_submit`/`on_stop`） |
| `petcore/contracts/screen.py` | 新 22 | `ScreenCapture` 数据类（stdlib-only） |
| `petcore/platform/screenshot.py` | 新 75 | `capture_screen()` + `data_url()`，仅内存 |
| `petcore/ui/chat/window.py` | 新 289 | Markdown 流式窗口、Enter/Shift+Enter、停止/清空 |
| `petcore/ui/chat/controller.py` | 新 296 | ChatPort 实现、信号排队、按宠会话、历史 |
| `petcore/platform/hotkeys.py` | +51 / −27 | 单条 → 四条命名注册，保留旧 `apply` 签名 |
| `petcore/ui/app.py` | +72 / −6 | 热键映射、`run_feature_command`、ChatController 持有 |
| `petcore/ui/ports.py` | +80 | `stream_chat` 转发、`QtScreenPort`、`WorkerNoticePort`（worker 失败提示）、`chat`/`screen` 注入 |
| `petcore/config.py` | +21 | 三个热键键 + `ai_service/ai_model/ai_system_prompt` |
| `petcore/contracts/api.py` | +12 / −1 | `ApiPort.stream_chat` |
| `petcore/contracts/host.py` | +4 | `HostPorts.chat/screen` |
| `petcore/menu_templates/petcore-default-v1.json` | +3 | 三个菜单动作（JSON 与内置常量同步） |
| `petcore/ui/menu_layout.py` / `menu_actions.py` / `coverage.py` | +3 / +21 / +3 | 菜单动作、回调与设置落点 |
| `petcore/ui/icons.py` | +8 | `chat` 图标 |
| `petcore/ui/settings/pages_core.py` | +51 | 「AI 快捷键」三条 + 截图隐私说明 |
| `petcore/ui/pet_window.py` | +8 | `run_ai_command()` 入口 |
| `examples/petcore-mods/ai.chat/**` | 新 399 + `mod.json` | 参考扩展（prompt/路由/截图/设置页） |
| `packaging/petcore.iss` | +3 | `mod_aichat` 可选任务（默认不勾） |
| `examples/petcore-mods/README.md` | +3 / −1 | 5 个 → 6 个扩展，补安装命令 |
| `tests/test_petcore_api_chat.py` | 新 169 | SSE/回退/401/429/取消/payload |
| `tests/test_petcore_chat_ui.py` | 新 132 | 流式、Enter 约定、按宠隔离、清空、错误 |
| `tests/test_petcore_screenshot.py` | 新 72 | PNG 内存、不落盘、失败 reason |
| `tests/test_petcore_hotkeys.py` | 新 121 | 四条并存、独立注销、配置键映射 |
| `tests/test_petcore_ai_mod.py` | 新 239 | manifest、prompt、流式、截图、无服务 |
| `tests/test_petcore_architecture.py` | +36 | chat Qt-free、mod 不 import 传输、engine 不 import ui |
| `tests/test_petcore_worker.py` | +24 | worker 出错/异常退出有用户提示 |
| `tests/test_petcore_menu_layout.py` / `test_petcore_installer.py` | +3 / +2 | 菜单顺序与安装清单 |

## 三、性能分析

方法：本机 Windows / Python 3.12 `.venv`；探针 `.scratch/p3_probe.py`，各 5 次取均值
（SSE 100 段、每段 11 字；截屏 1920×1200@1.5）。

| 指标 | 实测 | 说明 |
|---|---:|---|
| SSE 首段延迟（localhost） | **38.3 ms** | 含 TCP + 请求头 + 首块解析 |
| 100 段总耗时 | **45.8 ms** | 每段约 0.08ms 解析开销 |
| 窗口渲染 | **0.4 ms / 次合帧** | 300 段 / 50 次 flush = 21.8ms |
| 整屏抓取（1920×1200@1.5） | **204.7 ms** | 同步在 GUI 线程；min 193.7ms |
| 截图 PNG 大小 | **367 KB** | 解码后约 9.2 MB 瞬时内存 |
| 新增常驻线程 | **0** | 每次请求 1 个 daemon 线程，结束即回收 |
| 新增磁盘写入 | **0**（对话）；会话按条写入 `sessions/` | 截图不落盘 |

- 稳态开销：窗口只在有 delta 时按 50ms 合帧重排，空闲不发定时器；`ScreenPort` 无缓存。
- 已知代价：抓屏 205ms 阻塞 GUI 线程（用户主动触发，非热路径）；视觉请求会把
  367KB base64（约 490KB）放进请求体，不同服务对图片上限不同。
- 内存：流式文本按窗口累积（单会话上限由 `session_store` 的 200 条/24k 字约束）。

## 四、实机运行记录

```text
QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py tests/test_architecture.py \
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
1019 passed in 95.54s

ruff check pet/ tests/ petcore/   → All checks passed!
python -m petcore --check         → exit 0
```

关键行为验证（offscreen，真实 Qt 事件循环）：

- 流式：`token` 逐段渲染、`done` 后停止按钮隐藏；`error` 会清掉占位 assistant 条目。
- 按宠隔离：slot 0/1 各一个窗口，会话分别落 `sessions/` 与 `sessions-slot-1/`。
- 截图：`ScreenCapture.png` 以 `\x89PNG` 开头，目录内无新文件。
- 热键：四条注册拿到不同 id，`clear(name)` 只注销一条。
- 扩展：`ai.chat` 的 `submit` 组装 system + 历史，截图路径内联 `data:image/png;base64,`。
- 无扩展时：`run_feature_command` 返回 False 并气泡提示「AI 扩展未安装」。
- Worker 失败：`WorkerNoticePort` 把 on_error/异常退出转成气泡提示（有测试）。

**打包与签名（已完成）**

根因是环境：本机 **Smart App Control** 拦截未签名的新构建
（`WinError 4551 = "An Application Control policy has blocked this file."`），
PyInstaller 的空 hello 程序同样被拦，与 petcore 代码无关。解决方式：

- 新增 `scripts/make_dev_signing_cert.ps1`：创建本机开发证书（CurrentUser\My），
  把公钥导入 `CurrentUser\Root` + `CurrentUser\TrustedPublisher`（不需要管理员）。
- `scripts/build_petcore.ps1` 新增 `-SignThumbprint`：**exe 在 `--check` 之前签名**，
  setup 在 ISCC 之后签名；时间戳服务器不可用时退回无时间戳签名并给出提示。
- 签名后 Smart App Control 放行。

```text
dsh-pet-core.exe    | Valid | CN=DSH Pet Core Dev, O=DSH Pet, C=CN
dsh-pet-core-setup.exe | Valid | CN=DSH Pet Core Dev, O=DSH Pet, C=CN
setup: 194,139,120 字节（ISCC 112.953s）
packaged --check: exit 0, menu_template=json, diagnostics=[]
ai.chat 安装到临时数据根后 --check: mods=['ai.chat'], diagnostics=[]
```

边界：这是**本机开发证书**，别的机器不信任它；正式分发必须换 CA 证书。
完整安装向导 E2E（升级/卸载）未在本机执行，避免影响现有安装。

**未验证 / 限制**

- 真实 DeepSeek / 视觉模型端到端（本机无可用密钥，首 token 延迟只测了传输层）。
- 抓屏在 GUI 线程同步执行，按下热键会有约 200ms 可感知停顿。
- OCR、翻译、框选、主动识屏、Agent、TTS 均未做（P4）。
- macOS/Linux 的抓屏与热键未实机（Windows 专用 `RegisterHotKey`）。

## 五、风险与回滚

- 新增的 `Hotkey.apply(name=)` 保留旧签名，回滚只需还原 `hotkeys.py` 与 `app.py`。
- 截图端口与 ChatPort 都是新增，不影响既有 mod；`ai.chat` 是可选安装（默认不勾），
  卸载后菜单/热键只提示不报错。
- 流式线程均为 daemon，`stop()` 置位取消；窗口关闭不中断会话保存。
