# 截图三功能（提取文字 / 翻译预留 / 截图问答）P0 —— 实机与打包证据

> 分支 `feat/screen-capture-p0`。范围：右键菜单「截图」三入口（提取文字 / 翻译（置灰预留）/ 问答），
> 采集闭环（藏窗 → 冻结帧 → 框选 → 选区像素），本地 OCR（RapidOCR 随包模型，断网可用），
> 结果浮层与灵动岛状态显示，问答走既有 vision 对话通道（上云前显式确认，fail-closed）。
> 全局热键、多屏、翻译引擎、macOS/Linux 实机不在本片（见末节遗留）。

## 一、修改文件说明

### 新增（产品）

| 文件 | 行数 | 改了什么 + 为什么 |
|---|---|---|
| `pet/screen_capture/session.py` | 204 | 采集会话状态机（idle→hiding→frozen→selecting→captured/cancelled→restoring），纯 Python 零 Qt，非法迁移拒绝 |
| `pet/screen_capture/host.py` | ~110 | `WindowHider`：隐藏/还原自家顶层窗口，账本含原激活态（恢复时还原），`restore_all` 异常也收口 |
| `pet/screen_capture/pixels.py` | 116 | 冻结帧抓取（grabWindow QPixmap→QImage 归一）、DPR floor/ceil 选区裁剪、统一 sRGB 8-bit |
| `pet/screen_capture/overlay.py` | ~290 | 框选覆盖层（压暗遮罩+拖框+Esc/Enter）、`MIN_SELECTION_SIDE=8` 防误触、`SelectionMemory` 按屏尺寸记上次选区 |
| `pet/screen_capture/controller.py` | ~220 | 采集闭环编排：hide → **DwmFlush 等一帧合成**（~5.5ms，审查 major 项的保险）→ grab → 框选 → 输出；收口单点 `_teardown` |
| `pet/screen_capture/ocr.py` | ~830 | RapidOCR 引擎封装：懒加载、推理串行、代次防竞态、`unload()`/`release_engine()`（用完就丢）、人话错误；模型 sha256 单一真相源 |
| `pet/screen_capture/actions.py` | ~770 | 三动作编排 + `ScreenCapturePresenter`（岛短结果/面板长结果）+ watcher 暂停恢复闸（现取式）+ 云端确认 fail-closed |
| `pet/screen_capture/result_panel.py` | ~430 | 结果浮层：可复制、双语槽位、Esc 关、贴边夹取+边缘翻转、不抢焦点、跟随宿主主题 |
| `pet/screen_capture/vision_bridge.py` | 103 | 问答桥：选区 QImage → 内存 JPEG → 既有 `vision.ask_about_screen`（不落盘） |
| `pet/screen_capture/reasons.py` | 小 | 置灰/待接入文案单一真相源（审查 m4） |
| `pet/qt_image_limits.py` | ~40 | 进程级图像解码上限抬到 1024MB（只抬不降；夹带项，见末节说明） |
| `scripts/verify_rapidocr_models.py` | ~150 | 构建期模型门（文件名+sha256）+ `--app-dir` 产物侧门（含引擎模块在 PYZ 图里的校验） |

### 修改（既有文件，逐处克制）

- `pet/__main__.py` / `pet/app.py`：启动点接 `apply_image_allocation_limit()`；app.py 注入取岛回调（+3）
- `pet/vision.py`：`ask_about_screen` 增可选 `user_text`（None 时逐字原行为）——问答话术与整屏陪伴话术不同
- `pet/window.py` / `pet/overlay_shell.py` / `pet/sprite_menu_facade.py` / `pet/context_menus/{registry,shared}.py` + `menu_templates/modern-default-v1.json`：右键「截图」子菜单接线（单 id 组、老用户布局自动并入有测试钉住、宿主为长寿命对象）
- `scripts/build_onedir.ps1` / `build_linux.sh` / `build_macos.sh`：去掉 numpy/cv2 排除（留着=冻结包 OCR 全灭，实测）、加 `--add-data` 模型与 rapidocr yaml、加 `--hidden-import pet.screen_capture.ocr`（**审查 blocker：动态 seam 导致引擎模块不进包**）、接模型双门
- `scripts/slim_bundle.py`：numpy 移出违禁清单（已是合法依赖）、OpenCV 视频后端 DLL（28MB，OCR 不用）进移除清单
- `requirements.txt`：+rapidocr/onnxruntime/numpy/omegaconf（`test_runtime_dependencies.py` 门）
- `THIRD_PARTY_NOTICES.md` + `resources/rapidocr_models/{LICENSE,MODEL_LICENSES,NOTICE}`：许可登记（Apache-2.0/MIT/BSD）
- `docs/ONEDIR_PACKAGING.md`：随包 OCR 模型一节 + 体积口径更正 + 门接线说明
- `docs/INDEX.md`：本报告登记

### 测试（新增 12 个文件，~340 例）

`tests/test_screen_capture_{session,host,pixels,overlay,controller,ocr,actions,menu,result_panel,packaging}.py`、
`test_qt_image_limits.py`、`test_verify_rapidocr_models.py`——全部先红后绿，含变异/消融校验（去锁变红、
去掉 hidden-import 的 A/B 包对照等）。菜单快照两处（`test_menu_layout`/`test_desktop_pet_features`）随模板同步。

## 二、性能分析

真机实测（2560×1440@170Hz HDR 屏，dpr=1.0；OCR 数字为 Python 3.13.7 + onnxruntime 1.20.1 + rapidocr 3.10）：

| 环节 | 实测 | 样本 |
|---|---|---|
| 触发→冻结帧到手（藏窗+抓帧+等帧） | ≈40–60ms | grab 47.1ms@1440p / 29.1ms@1080p（n=20），hide 6.3ms，settle 5.5ms |
| 选区裁剪 + sRGB 转换（1200×900） | 1.13ms / 0.69ms | max 2.2 / 6.2 |
| OCR 模型加载（懒加载首触发） | 1975ms | 含 rapidocr import ~1.7s |
| OCR 冷识别（加载后首帧 800×400） | 1020ms | 8 块全中，置信度 0.946~0.997 |
| OCR 热识别 P50/P95/max | **675 / 739 / 774ms** | n=30，中英混排 |
| 识别后闲置 CPU | **0.00%**（关自旋实测） | — |
| 内存增量（旧进程内口径，已被 aaafe91 取代） | 加载 +114.5MB、平台期 162.7MB 不涨；unload 回吐 ~30MB | native 堆不还 → 子进程化（B 方案）已落地，见末节 |
| 内存增量（子进程化后，aaafe91 实测） | **主进程 RSS Δ+0.0MB**（47.8→47.9，3 次识别前后）；子进程峰值 307~320MB，退出后全机扫描 0 残留 | 源码态探针 `.scratch/screen-capture/probe_ocr_subprocess.txt` |
| OCR 端到端（子进程化后，暖/冷模型文件） | 2556~2592ms / 2617ms | 每次识别付 spawn+重载模型，较旧进程内稳态（801ms）多约 1.8s——用户拍板的取舍 |
| 启动期新增成本 | 截图栈不进启动路径（菜单函数内 import，实测省 ~55ms）；`import ocr` 21ms 且不载重模块 | — |

打包体积：探针包实测 334MB（消融视频后端后 306MB），增量构成 cv2 99MB + 模型 31.6MB + onnxruntime 29MB + numpy 27MB；
产品变体全量体积下次出包顺手回填（文档已标注）。CI 成本提醒：`test_runtime_dependencies.py` 因新依赖 ~10s→~85s。

## 三、实机运行记录

1. **HDR/色准探针**（真显示器，HDR 开，H27T22S）：`DisplayConfig`+DXGI 双通道判定 HDR 启用；
   5 个已知色块经 `grabWindow` 逐字节命中（偏差 0），与 PIL ImageGrab 交叉一致 94.7%（残差全是动态视频区）
   → **P0 不需要 WGC 备选路径**（`.scratch/screen-capture/probe_hdr_output.txt`）。
2. **藏窗→抓帧正确性探针**：亮纯色标记窗口走产品 hide→settle→grab 路径，冻结帧里标记像素 **0/134400**
   （对照组成立）。本机不复现"藏不干净"，等帧为保险（代码注释如实标注）。
3. **冻结包 A/B 对照**（审查 blocker 复验）：同源码同机两包——不带 hidden-import 的包引擎缺席、菜单置灰、
   产物门 exit 1；带上的包认出 `'frozen bundle ocr 12345\nquick brown fox'` 逐字正确、零网络请求（requests 打桩抛异常仍成功）、
   unload 后 −37.8MB 可重载再认。构建日志 0 WARNING。
4. **OCR 链路探针**：真引擎走编排层全链（解析→识别→浮层状态），无聊天配置时问答如实报「AI 对话通道不可用」。
5. **本机未验（如实登记）**：框选覆盖层真机观感（offscreen 渲染断言过，差一次真人 30 秒烟测）、多屏/分数 DPR、
   HDR 源内容（PQ 视频）逐像素还原、Linux/macOS 构建与产物门（脚本接线有测试，未真跑）、完整产品变体构建体积。

## 遗留与后续

- **OCR 子进程化（用户拍板 B 方案）——已落地（aaafe91）**：识别改为 `--ocr-worker` 子进程用完即退，源码态主进程 RSS Δ+0.0MB、
  冻结探针包端到端 2837ms / 主进程 Δ+0.7MB / 残留 0（证据 `.scratch/screen-capture/probe_frozen_package.txt`）。
  代价明账：每次识别较进程内稳态多约 1.8s（spawn + 重载模型）。冻结复验用的是最小探针包，完整变体的 `--app-dir` 门待下次出包回填。
- 翻译引擎（`translate.py` seam 就位，面板双语槽就位，菜单置灰带说明）；全局热键；多屏采集；选区记忆跨重启（涉配置键门禁）。
- 夹带项说明：进程级图像解码上限 256MB→1024MB（聊天附件/头像等同受益，坏图头最多多申请 1GB；取舍与实测在
  `.scratch/screen-capture/note-pr-report-2026-10-13.md`）。
