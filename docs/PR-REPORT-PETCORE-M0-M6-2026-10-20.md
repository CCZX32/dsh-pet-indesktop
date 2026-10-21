# petcore：最小 core + mod 宿主

- 分支：`feat/petcore-vpet-architecture`
- 基线：`main` / `147170f`
- 日期：2026-10-20
- 环境：Windows 11，Python 3.12.10，PySide6 6.12.0，imageio-ffmpeg 0.6.0

## 修改文件说明

### 新增（62 个 Python 文件 / 6,125 行）

| 区域 | 内容 |
|---|---|
| `petcore/engine/` | 枚举、几何、动画目录、动画链、行为决策、位移夹取、宠物状态 |
| `petcore/contracts/` | 内容模型、Host 端口、事件、贡献、能力、feature、worker 协议 |
| `petcore/media/` | WebP 帧序列 / WebM / GIF 适配、ClipLibrary、fallback、音效 |
| `petcore/content/` | 旧素材只读 provider、mod 角色构建、收集、`pack-legacy` |
| `petcore/mods/` | manifest 校验、发现/启停、安装/卸载、feature 加载、CLI |
| `petcore/platform/` | 逐像素穿透、屏幕/多屏、会话结束、开机自启 |
| `petcore/ui/` | 透明窗、渲染、气泡、菜单模型、托盘 |
| `petcore/ui/settings/` | 设置宿主 + 常规/外观/菜单/扩展/关于五页 |
| `petcore/builtin/feature_demo/` | feature 接缝演示（菜单项 + 气泡命令） |

### 新增测试（15 个文件 / 2,950 行）

`tests/test_petcore_{architecture,manifest,loader,install,catalog,animation,behavior,motion,legacy,screens,menu,settings,feature,cli,window_smoke}.py`。

### 新增文档

`docs/PETCORE-{ARCHITECTURE,MOD-FORMAT,CHARACTER-PACKS,ROADMAP}.md`、本报告；`docs/INDEX.md` 登记。

### 修改既有文件（`git diff --numstat`）

| 文件 | 增/删 | 原因 |
|---|---|---|
| `.github/workflows/pr-test.yml` | +1/−1 | ruff 门禁加入 `petcore/` |
| `.gitignore` | +5/−0 | 忽略 `.venv/`、`/data/`、`/mods/` |
| `docs/INDEX.md` | +10/−0 | 新文档与 PR 报告登记 |

未修改 `pet/` 任何产品代码。

## 性能分析

命令与环境：

```
QT_QPA_PLATFORM=offscreen .venv/Scripts/python .scratch/petcore-evidence/perf_probe.py
# 每个路线 3 次：start→首帧；随后 4s 空闲，CPU = Δ(os.times user+system) / Δwall
```

| 路线 | 首帧（3 次） | 首帧中位数 | idle CPU（3 次） | CPU 中位数 |
|---|---|---|---|---|
| WebM（`shenshen`，106 段） | 532.3 / 190.3 / 182.1 ms | **190.3 ms** | 17.57 / 16.01 / 15.23 % | **16.01 %** |
| WebP 帧序列（1 段 idle） | 41.1 / 13.7 / 13.6 ms | **13.7 ms** | 21.85 / 22.23 / 19.14 % | **21.85 %** |

- 首帧收益来自不启动 ffmpeg：WebM 冷启动含解码进程 spawn，帧序列只加载 WebP。
- **帧序列 idle CPU 反而高约 5.9pp**（21.85% vs 16.01%）。如实登记：该探针下 `FrameSeqClip` 的预取线程持续解码，而 WebM clip 走了解码节流；这不是“帧序列更省 CPU”的证据。帧序列的价值在于首帧与免 spawn，不在稳态 CPU。
- 两条路线都未新增网络；WebM 路线有 ffmpeg 子进程（由 `win_job` 绑定进程生命周期），帧序列路线有预取线程（`pet.frameseq_clip` 既有实现）。

启动导入成本：

```
python -c "import time,sys; t=time.perf_counter(); import petcore.ui.app; print(...)"
→ 0.331 s，222 个模块（含 PySide6）
python -c "... import petcore.cli ..." → 0.081 s，124 个模块
```

`--check` 不创建窗口、不启动解码线程；不装 PySide6 也能跑到内容扫描（帧序列采纳会跳过）。

内存未做长时 soak；本轮不新增长期采样。

## 实机运行记录

```
.venv/Scripts/python -m petcore --check
→ 退出码 0；角色 shenshen，106 段，后端全部 webm；body_box [212,60,428,330]，head_box [185,60,436,195]（实际输出见终端）
```

真实窗口（非 offscreen）：

```
.venv/Scripts/python <evidence script>
→ SHOT True 692 389 visible True pos 761 471
```

- 692×389 = 逻辑 461×259（0.72 缩放）× 1.5 DPR，截图见 `.scratch/petcore-evidence/window.png`，角色正常渲染。
- 窗口为无边框、透明、置顶；`platform/win.py` 逐像素控制器已启动。
- 设置窗口实机构造：5 页（常规/外观与交互/菜单/扩展管理/关于与诊断）、搜索框与 5 页 stack 均存在；截图由无头渲染确认（见下）。

自动化门：

```
.venv/Scripts/python -m pytest tests/test_petcore_*.py -q      → 203 passed
.venv/Scripts/python -m pytest tests/test_architecture.py -q   → 5 passed
.venv/Scripts/python -m pytest tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q → 259 passed, 5 skipped
.venv/Scripts/ruff check pet/ tests/ petcore/                  → All checks passed
```

**未实机验证（如实登记）**：

- 多屏：本机 `WmiMonitorBasicDisplayParams` 只有 1 块物理屏；多屏行为仅由 `tests/test_petcore_screens.py` 的伪造几何覆盖，未做真实双屏。
- 逐像素穿透与拖拽/点击：由无头测试覆盖透明像素判定与窗口 API；未做人工鼠标操作确认。
- 设置页里的「扩展管理」真实安装/卸载：由 `test_petcore_install.py` 覆盖文件系统操作，未在 UI 中手点。
- 开机自启：只做了注册表读写函数，未实际重启验证。

## P1-A 增量：菜单风格 + 可自定义菜单（2026-10-20）

### 修改文件说明

新增：

- `petcore/menu_templates/petcore-default-v1.json`：默认布局，schema 与主分支 `modern-default-v1` 同构。
- `petcore/ui/menu_layout.py`：校验、隐藏/不可用过滤、分割线归一化、默认动作合并、mod 动作入「扩展」、旧 `menu_hidden/menu_order` 迁移。
- `petcore/ui/menu_actions.py`：Core 动作注册表（character/size/hide_pet/on_top/click_through/autostart/return_corner/move_to_primary/reload_mods/open_data/extensions_hub/modern_settings/about/quit）与可用性判定。
- `petcore/ui/menu_style.py`、`petcore/ui/icons.py`：26px 行高浅/深 QSS、菜单图标绘制（不 import `pet`）。
- `petcore/ui/settings/menu_editor.py`：树形编辑器（拖拽/显隐/子菜单/分割线/别名/内置图标/本地图片图标 ≤5 MB/重置/预览）。
- `tests/test_petcore_menu_layout.py`、`tests/test_petcore_menu_editor.py`。

修改：`petcore/ui/menu_model.py`（布局驱动渲染 + 兼容层）、`petcore/ui/menu.py`（注册表入口）、`petcore/ui/app.py`（加载/迁移/重载菜单）、`petcore/config.py`（`menu_layout` 键）、`petcore/ui/settings/pages_core.py`（菜单页换编辑器）、`petcore/ui/settings/{style,base,dialog}.py`（34px 行高、3px 选中条、侧栏图标、阅读宽度、Accent）。

### 性能分析

命令：`.venv/Scripts/python <inline probe>`，本机 Win11 / Python 3.12.10 / PySide6 6.12.0。

| 路径 | 实测（n） | 说明 |
|---|---|---|
| `resolve()` 默认布局 | **0.481 ms/次**（5000） | 菜单打开时调用一次 |
| `resolve()` 用户布局 | **0.506 ms/次**（5000） | 含默认动作合并 |
| `MenuModel.build()` | **0.315 ms/次**（200） | 含 QSS/图标，11 个根项 |
| `MenuEditor` 构造 | **11.6 ms**（1） | 设置页打开时一次性 |

稳态无新增线程、网络、磁盘轮询；菜单只在右键/托盘打开时解析与构建。设置保存会写一次 `config.json`（既有原子写路径）。

### 实机运行记录

- 默认菜单顺序（实机渲染）：切换角色 / 大小 / 隐藏桌宠 / 桌宠控制（窗口置顶、点击穿透、开机自启、回到右下角、移到主屏、重新加载扩展、打开数据目录）/ 扩展 / 桌宠设置 / 关于 / 退出。
- 浅色与深色截图：`.scratch/petcore-evidence/menu-light.png`、`menu-dark.png`、`settings-menu-light.png`、`settings-menu-dark.png`。
- 自定义链路（offscreen 端到端）：打开设置 →「菜单」→ 把首项改名为「主角色」→ 保存 → 重建菜单首项显示「主角色」；`config.menu_layout` 落盘。
- 门禁：`tests/test_petcore_*.py` **222 passed**；`ruff check pet/ tests/ petcore/` 全绿。
- 未验：真实双屏下「移到主屏」的可用性（仅单测伪造）；macOS/Linux 菜单外观（本机只有 Windows）。
