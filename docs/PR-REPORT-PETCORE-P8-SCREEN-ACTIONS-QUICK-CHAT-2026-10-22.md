# PR 报告：截图动作条补全（OCR 归 mod）与快速对话气泡（P8）

- **分支**：`feat/petcore-vpet-architecture`
- **日期**：2026-10-22
- **范围**：`petcore/contracts`、`petcore/ui/screen`、`petcore/ui/chat`、`petcore/ui/bubble.py`、
  `petcore/ui/app.py`、`petcore/ui/ports.py`、`examples/petcore-mods/ai.chat`、
  `examples/petcore-mods/tool.ocr`（新）、`packaging/petcore.iss`、`scripts/build_petcore.ps1`

## 摘要

1. **截图动作条补齐四项**：提取文字 / 翻译 / 问问肥鱼 / 复制图像。core 只做框选、
   按钮可点性、结果窗和剪贴板；动作处理走 `ScreenAskPort.on_action(priority=)`，
   空串/异常自动换下一个。菜单仍只有「截图提问」一个入口（用户口径）。
2. **本地 OCR 是扩展**：新增 `tool.ocr`（加装扩展，安装任务 `mod_ocr` 默认不勾），
   rapidocr + 随包模型、显式 onnxruntime session、不下载模型；失败返回空串交给
   `ai.chat` 的视觉模型兜底。core 不 import rapidocr、不含任何业务提示词。
3. **翻译在 ai.chat**：有本地 OCR 原文时纯文本翻译，没有时视觉翻译；目标语言自动
   判定（中日韩占多→英文，否则中文）。
4. **快速对话气泡**：点桌宠气泡 → `SpeechBubble.clicked` → `CoreHost.open_quick_chat`
   → `QuickChatPort`；窗口/输入在 core，流式回答在 `ai.chat`，与完整聊天窗共用同一
   会话，「去聊天窗」接着看。
5. 附带：`ResourcesPort`（mod 读取随包资源的通用只读端口）、`packaging/petcore.iss`
   新增 `mod_ocr`、构建脚本打包 rapidocr 与模型、ai.chat 版本 1.3.0 → 1.4.0。

## 修改文件说明

| 文件 | 增/删 | 改了什么 + 为什么 |
|---|---|---|
| `petcore/contracts/screen.py` | +54/−2 | `ACTION_*` 常量、`RegionPick`、`ScreenPort.capture_region(ai_available=)`；`ScreenAskPort.open_action/on_action(priority, actions)`。**为什么**：动作条与「本地优先、AI 兜底」需要通用端口，core 不认识引擎。 |
| `petcore/contracts/chat.py` | +25 | `QuickChatPort`（open/token/reasoning/status/done/error/history/on_submit/open_full_chat）。**为什么**：快速气泡的窗口在 core、模型在 mod。 |
| `petcore/contracts/host.py` | +9/−1 | `ResourcesPort.bundle_path()`、`HostPorts.resources`、`HostPorts.quick_chat`。**为什么**：mod 取随包模型/驱动快捷气泡，不用 import `petcore.paths`。 |
| `petcore/ui/screen/overlay.py` | +69/−14 | 四按钮动作条、capabilities/reasons（禁用 tooltip）、`accepted(action, rect)`、Enter 默认动作（ocr→ask→copy）。**为什么**：主分支同款四动作；不可用动作要如实置灰。 |
| `petcore/ui/screen/selection.py` | +60/−11 | `select_region` 返回 `RegionPick`、capabilities 透传、`copy` 写系统剪贴板；兼容旧单参数 `accepted` 替身。 | 
| `petcore/ui/screen/controller.py` | +148/−1 | `on_action` 注册表（priority/actions）、`supports_action`、`open_action` 后台调度、动作结果窗的 generation 校验。**为什么**：动作执行不能阻塞 GUI，迟到的结果不能写进新会话。 |
| `petcore/ui/screen/ask_window.py` | +6/−2 | `start(..., chip=)`、`status_text()`。**为什么**：动作结果窗要显示「识别结果会显示在这里」并便于测试/诊断。 |
| `petcore/ui/chat/quick.py`（新） | +286 | 紧凑气泡：标题/状态/Markdown 输出/输入/发送/去聊天窗；贴桌宠定位与 40ms 跟随。 | 
| `petcore/ui/chat/quick_controller.py`（新） | +238 | 按 `(owner, slot)` 隔离、排队信号、共用会话、去聊天窗。 | 
| `petcore/ui/chat/controller.py` | +14/−6 | `append_to_session()` 同步写会话（快速对话用），`_apply_record` 复用它。 | 
| `petcore/ui/bubble.py` | +12/−1 | `clicked` 信号、左键 release 发射；内部 QLabel 设 `WA_TransparentForMouseEvents`。**为什么**：否则点击被标签吞掉，快速对话打不开。 | 
| `petcore/ui/pet_window.py` | +7 | 连接气泡点击 → `host.open_quick_chat(slot)`。 | 
| `petcore/ui/app.py` | +13/−1 | 创建 `QuickChatController`、`open_quick_chat(slot)`（无 handler 时提示 AI 扩展未安装）。 | 
| `petcore/ui/ports.py` | +42/−2 | `ResourcesAdapter`、`QtScreenPort.capture_region` 计算能力表（动作处理者 + AI 可用）并返回 `RegionPick`、`quick_chat` 端口。 | 
| `examples/petcore-mods/tool.ocr/`（新） | +291 | `engine.py`（rapidocr 惰性加载、显式 session、阅读顺序、失败降级）、`runtime.py`（priority=10 只接 `ocr`）、`mod.json`。 | 
| `examples/petcore-mods/ai.chat/host/prompts.py` | +44 | `ocr_messages`、`translate_messages`、`target_language`。 | 
| `examples/petcore-mods/ai.chat/host/runtime.py` | +156/−5 | `RegionPick` 分派（copy/ocr/translate/ask）、`_on_action`（AI 回退/翻译）、快速对话提交与流式。 | 
| `examples/petcore-mods/ai.chat/host/constants.py` | +3 | `QUICK_HISTORY=8`。 | 
| `examples/petcore-mods/ai.chat/mod.json` | +1/−1 | 版本 1.4.0。 | 
| `packaging/petcore.iss` | +4/−1 | `mod_ocr` 任务（默认不勾）+ `tool.ocr` 文件 + `.trusted`。 | 
| `scripts/build_petcore.ps1` | +18 | 打包 `resources/rapidocr_models`、rapidocr 配置、`--collect-submodules rapidocr`、onnxruntime/cv2/numpy/omegaconf。 | 
| `petcore/AGENTS.md` | +14 | 五条红线：动作条只放 core UI、OCR 归 mod、快速对话共用会话、气泡标签透传鼠标、`mod_ocr` 默认不勾。 |
| `tests/test_petcore_screen_ask.py` | +83/−15 | 四动作条、gating/tooltip、Enter 默认、copy、RegionPick。 | 
| `tests/test_petcore_screen_actions.py`（新） | +128 | priority 回退、原文传递、全失败原因、异常降级、迟到结果丢弃。 | 
| `tests/test_petcore_quick_chat.py`（新） | +188 | 开窗、提交/流式/落会话、去聊天窗、按宠隔离、气泡点击。 | 
| `tests/test_petcore_ocr_mod.py`（新） | +163 | 模型判据、阅读顺序、运行时注册/降级、真实 rapidocr 识别。 | 
| `tests/test_petcore_ai_mod.py` | +150/−3 | RegionPick 分派、OCR/翻译提示词、快速对话流式与无服务错误。 | 
| `tests/test_petcore_example_mods.py` / `test_petcore_installer.py` | +11/−2 | `tool.ocr` 进示例清单与安装任务断言。 | 

## 性能分析

环境：Windows 11，本机 `TM140VDXP02`，Python 3.12，rapidocr 3.10 + onnxruntime 1.31，
模型 `resources/rapidocr_models`（31MB）。

| 路径 | 实测 | 说明 |
|---|---|---|
| 本地 OCR 首次（冷） | **1954 ms** | 进程内加载 3 个 ONNX session + 一次识别（900×200 文字图）；只在用户第一次点「提取文字」时发生。 |
| 本地 OCR 后续（暖） | **791 ms** | 引擎常驻，只做推理；同主分支「一次识别」量级（主分支冷约 2.5s，但每次一个子进程）。 |
| OCR 进程内存（暖） | **145 MB RSS** | 测试进程含 numpy/cv2；主分支用子进程「用完即弃」，本实现把引擎留在桌宠进程里，这是已知代价（报告末尾的边界）。 |
| 覆盖层绘制 | **4.22 ms**（沿用 P7 实测） | 动作条从 2 个按钮变 4 个，paint 路径未变。 |
| 动作注册/查找 | 微秒级 | 每次点击线性扫描 ≤ 数个 handler；无网络/磁盘/线程新增（动作本身在既有后台线程里跑）。 |
| 快速对话 | 与主对话同一 SSE 路径 | 只多一层排队信号；无新增定时器（跟随复用 40ms 单次定时器）。 |
| 构建产物 | 预计 +100–180 MB | rapidocr/onnxruntime/cv2 进包、模型 +31MB；实际体积见「实机运行记录」。 |

- 稳态开销：不触发 OCR/快速对话时，新增的只有 `bubble.clicked` 一个信号连接和一个
  未显示的 `QuickChatBubble` 对象（按需创建，点过才存在）。
- 新增系统调用：`copy` 动作一次剪贴板写入；OCR 一次进程内推理；没有新增常驻线程。
- 内存：OCR 引擎常驻（上表）；快速气泡只在打开时分配，关闭不销毁但可复用。

## 实机运行记录

1. **本地 OCR 真实识别**（未装任何额外服务，直接调扩展引擎）：

   ```
   text 'HELLO 123'
   cold ms 1954.2 warm ms 791.4
   rss MB 145.2
   ```

2. **全量门禁**：

   ```bash
   QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py tests/test_architecture.py -q
   # 1151 passed in 68.33s
   .venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods
   # All checks passed
   QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m petcore --check --out .scratch/p8-check.json
   # exit 0
   ```

3. **打包与安装**（实跑）：

   ```
   setup  dist/dsh-pet-core-setup.exe  257,459,336 bytes  签名 Valid
   app    E:\dsh-pet-core              733 MB（含 _internal/resources/rapidocr_models）
   install exit 0；/TASKS 含 mod_aichat,mod_ocr + 原有 5 个扩展
   安装后 --check：version 0.1.0，diagnostics []
     ai.chat  1.4.0 enabled=True
     tool.ocr 1.0.0 enabled=True
   {app}\mods\tool.ocr\.trusted 存在；应用已重新启动
   ```

4. **未自动验证**：真实桌面上的动作条点击（离屏测试覆盖几何/信号/剪贴板，
   但「肉眼看四个按钮的位置与禁用 tooltip」需要人工确认）；快速气泡在真实多屏
   DPI 下的贴边定位同理。

## 边界 / 风险

- `rapidocr/onnxruntime/cv2` 随 exe 打包（冻结包无法让 mod 自行安装依赖），
  未安装 `tool.ocr` 时功能不启用但依赖仍在包里；模型 31MB 随包。
- OCR 引擎常驻进程内（约 145MB RSS），与主分支「一次识别一个子进程、用完即弃」
  不同；若要完全对齐，需要通用 mod worker 子进程入口（未在本轮做）。
- 翻译与 AI OCR 回退依赖已配置的 API 服务；没有服务时动作条如实置灰。
- 快速对话与完整聊天窗共用会话，不另建历史；没有快捷热键/菜单入口（按需求只做
  点气泡）。
- 主动识屏不在本轮。
