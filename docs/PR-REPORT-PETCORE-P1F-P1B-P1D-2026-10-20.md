# PR 报告：petcore P1-F 边缘探头 + P1-B 核心体验 + P1-D 角色包导入

> **基线**：`feat/petcore-vpet-architecture`（P1-E 完成后的工作区）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-20
> **范围**：边缘探头、快捷键/自启/多实例/打包入口/首跑供给、角色包导入；`pet/` 产品代码未改。
> **关联**：[`PETCORE-ROADMAP.md`](PETCORE-ROADMAP.md) §8–§10、[`PETCORE-LOG.md`](PETCORE-LOG.md) `L005`–`L007`。

## 一、核心特性

### P1-F 边缘探头
贴到屏幕左/右缘后自动 45° 探头，只露头/上半身；点击拉直并短暂全出，5 秒后回到探头；
拖拽/关闭开关立即取消；设置与右键菜单都可开关。

### P1-B 核心体验
- 全局「显示/隐藏桌宠」快捷键（Windows `RegisterHotKey`），设置页可改；
- 开机自启命令文本区分源码/打包，CLI `petcore autostart on/off/status`；
- `--instance NAME` 多实例：每个实例一只宠、独立数据目录与 lock；
- PyInstaller onedir 入口与构建脚本（未实际构建）；
- WebM→WebP 首跑供给包装，复用主分支 `provision_once`（含世代退役/GC）。

### P1-D 角色包导入
`petcore pack-character` 从 `manifest.json` + 媒体目录生成标准 `character.<id>` content mod；
校验 body/head、媒体存在、id 与输出目录；安装复用 `mods install`。

**红线 / 不变量**：`engine/` 禁 Qt、`contracts/` 只用标准库、`pet.*` 只在
`media/`/`content/legacy.py`；`pet/` 产品代码不改。

## 二、修改文件说明

### P1-F
| 文件 | 改动 |
|---|---|
| `petcore/engine/edge.py`（新） | 贴边判定、旋转投影、目标 x、探头放宽域。 |
| `petcore/ui/edge_probe.py`（新） | 六态状态机、16ms timer、可注入时钟、拖拽/点击/暂停/取消。 |
| `petcore/ui/pet_window.py` | 旋转绘制、反向命中、探头移动、事件与生命周期接线。 |
| `petcore/config.py` | `edge_probe_enabled`。 |
| `petcore/ui/settings/pages_core.py` | 「边缘探头」复选框 + 取消回滚。 |
| `petcore/ui/menu_actions.py` / `coverage.py` / 默认菜单模板 | 菜单项与设置落点。 |
| `tests/test_petcore_edge.py` / `test_petcore_edge_probe.py`（新） | 几何与状态机。 |

### P1-B
| 文件 | 改动 |
|---|---|
| `petcore/platform/hotkey_spec.py`（新） | 纯文本快捷键解析/规范化。 |
| `petcore/platform/hotkeys.py`（新） | Windows `RegisterHotKey` + `WM_HOTKEY` 服务。 |
| `petcore/platform/autostart.py` | `command_text()`，`sys.frozen` 分支。 |
| `petcore/paths.py` / `petcore/cli.py` / `petcore/ui/app.py` | `--instance`、autostart/provision 子命令、应用名。 |
| `petcore/media/provision.py`（新） | `provision_character()` + 后台线程包装。 |
| `petcore/ui/settings/pages_core.py` | 快捷键输入行。 |
| `packaging/petcore_entry.py`（新）、`scripts/build_petcore.ps1`（新）、`packaging/petcore.iss`（新） | 打包入口/脚本/安装器模板（未实际编译）。 |
| `tests/test_petcore_platform.py`（新） | 快捷键、自启、多实例、供给包装。 |

### P1-D
| 文件 | 改动 |
|---|---|
| `petcore/content/character_pack.py`（新） | `validate_character_source()` + `build_character_pack()`。 |
| `petcore/content/pack.py` | `pack_legacy()` 复用同一构建器。 |
| `petcore/cli.py` | `pack-character` 子命令。 |
| `tests/test_petcore_character_pack.py`（新）、`tests/test_petcore_cli.py` | 成功/失败路径与 CLI。 |

### 文档
- `docs/PETCORE-ARCHITECTURE.md` §10–§12；`docs/PETCORE-SPEC.md`；`docs/PETCORE-ROADMAP.md` §8–§10；
- `docs/PETCORE-LOG.md` L005–L007 + `PETCORE-LOG-INDEX.md`；
- `petcore/README.md`、`petcore/AGENTS.md`。

## 三、实现要点

- **探头状态机**：`OFF→ENTERING→PEEKING→STRAIGHTENING→STRAIGHTENED→RETURNING`；
  过渡用 `1-(1-t)^3`；隐藏冻结进度；拖拽不恢复 x，功能关闭/换角色/换缩放 restore x。
- **旋转与命中**：`paintEvent` 绕窗口中心旋转；`is_transparent_at()` 用 `-angle`
  反向旋转后再映射到图像 alpha，保证点击位置与画面一致。
- **探头目标 x**：分母是「身体框绕帧中心旋转后的投影宽度」，不是整窗宽度；
  `probe_body_bounds()` 左右各放宽一个身体宽并减去 `body_local.x`。
- **快捷键**：`RegisterHotKey` 失败返回 `(False, 原因)`，设置页只写规范化值；
  非 Windows 明确不支持。
- **多实例**：数据根 `dsh-pet-core-<name>`，lock 在各自 root；单进程多宠仍未实现。
- **首跑供给**：`provision_once` 自己处理源哈希、原子发布、退役标记与清扫；
  petcore 只负责选角色、线程与预算。
- **角色包**：从 `manifest.json` 读 `body_box/head_box`，把 `media_root` 复制到
  `videos/`，写 `mod.json`；`pack_legacy` 与外部包同一路径。

## 四、性能分析

| 指标 | 实测 | 归属 |
|---|---|---|
| `rotated_bounds()` n=20000 | 中位 **0.0014 ms**，P95 **0.0015 ms** | 探头 16ms tick |
| `edge_side_at_rest()` n=20000 | 中位 **0.0001 ms**，P95 **0.0002 ms** | 进入判定 |
| 快捷键服务 | 无常驻 timer；只在 `WM_HOTKEY` 时 `QTimer.singleShot(0)` | 新增 |
| 首跑供给 | 后台 daemon 线程；shenshen 实机转 2 段（idle/move），其余 104 段仍 webm | 新增 |

**结论**：探头只在会话期间有 16ms timer，PEEKING 稳态停表；快捷键无稳态轮询；
供给只在启动后跑一轮，失败只记日志，不影响主界面。

## 五、实机运行记录

1. **边缘探头**：shenshen 0.72、150% DPI、单屏；贴右缘自动 45°，窗口部分出屏，
   只露头/上半身；点击后拉直（窗口截图回到 0° 全角色），5s 后回到 45°。
   截图：`.scratch/petcore-evidence/p1f-right-probe.png`、`p1f-return.png`。
2. **自启**：`python -m petcore autostart status` → `off`。
3. **多实例**：`python -m petcore --instance test --check` → 数据根
   `C:\Users\...\AppData\Roaming\dsh-pet-core-test`，与默认隔离。
4. **首跑供给**：正常启动后后台把 shenshen 的 idle/move 转成 frameseq；
   `--check` 输出 `{'webm': 104, 'frameseq': 2}`，无诊断。
5. **角色包**：合成 source → `pack-character` 生成 `character.clipet`；
   `mod.json` 的 `body_box` 正确，`mods` 收集识别。

**未能实机验证**：
- 真实全局按键（只测 fake user32 注册/失败路径）；
- PyInstaller 实际构建（本机未安装）；
- 单进程多宠（未实现）；
- 左缘探头的真实鼠标验收（本轮主要右缘，左缘由单测覆盖）；
- 真实大素材角色包导入（只用合成包）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `.venv/Scripts/ruff check pet/ tests/ petcore/` | All checks passed |
| petcore 聚焦 | `QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py -q` | **279 passed** |
| 结构 + 文档/CI 纪律 | 加 `test_architecture.py` / `test_pr_report_discipline.py` / `test_ci_workflows.py` | **560 passed, 5 skipped** |
| 内容自检 | `python -m petcore --check` | webm 104 + frameseq 2，无诊断 |

## 七、已知限制与后续

- 打包脚本未实际构建；安装器未做。
- 多实例已完成，单进程多宠仍延后。
- 快捷键非 Windows 不支持；真实按键未自动化。
- 边缘探头在 macOS/Linux 的窗口出屏与旋转命中未实机；大身体框可能被窗口裁切。
- 角色包导入只用合成包，未做真实大素材。
- 后续：P2 功能域迁包（F08/F10/F07/F11）；P3 平台/worker；P4 切换发布入口。
