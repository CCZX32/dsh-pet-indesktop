# petcore P8：多宠推动、气泡跟随、设置重组与打包回归

> **基线**：`feat/petcore-vpet-architecture`（P7 收口，未提交 git）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-21
> **范围**：运行时 7 个实现文件 + 打包 2 个脚本 + 设置 10 个实现文件 + 测试 9 个 + 文档 8 个
> **关联**：[`PETCORE-MAIN-PARITY-BACKLOG.md`](PETCORE-MAIN-PARITY-BACKLOG.md)（差距台账）、
> [`PETCORE-LOG.md`](PETCORE-LOG.md) L023

## 一、核心特性

本轮把“多宠移动/碰撞”从“一碰就变抛掷态”修成主分支口径：轻碰只做位置分离并平移
漫游计划，只有真撞击（≥300px/s）才写速度、切 `thrown`、取消探头。探头宠物在轻碰时
按无限质量处理，不会再被走路宠物挤下边缘。

同时修掉四个用户可见问题：子宠右键退出带走主宠、气泡不跟随桌宠、右键菜单因打包漏
`menu_templates/` 而缺「播放动画/彩蛋图片」、安装向导因 `DisableDirPage=auto` 跳过路径页。
设置侧把「互动与物理」拆成 8 个页内分页，7 个内置特性并入 Core 并把设置页内嵌到
互动/菜单/关于，扩展管理分组改为可折叠。

**红线 / 不变量**：拖拽中的桌宠不参与碰撞结算；碰撞位移必须经 `_clamp_position()`
身体框钳制；探头/击飞期间只播 idle/转向；菜单/设置一一对应；Core 不 import 网络库。

## 二、修改文件说明

> 分支上 `petcore/` 与 `docs/PETCORE-*` 均为未跟踪文件，`git diff --numstat` 不适用；
> 行数用 `wc -l` 的当前值，括号内为改动前值（来自上轮记录）。

### 运行时

| 文件 | 行数 | 改动意图 |
|---|---|---|
| `petcore/ui/pet_manager.py` | 388（346） | `_collide_pair()` 轻碰不取消计划、不写速度；探头轻碰按 `static=True` 重算；分离后按实际位移 `shift_move_plan()`；`_apply_body(impact_speed=...)` 只在真撞击时 `set_velocity()`。 |
| `petcore/ui/pet_window.py` | 1301（1213） | 新增 `shift_move_plan()`、`abort_move_plan()`、`quit_from_menu()`、`moveEvent` 同帧合并气泡跟随、`show_easter_egg()` 气泡/窗口双模式。 |
| `petcore/ui/bubble.py` | 224（77） | 重写为「标题 + 图片/文本」布局；新增 `reposition()`（锚点+尺寸缓存）、`show_image()`、`content_kind()`。 |
| `petcore/ui/easter_egg_entry.py` | 185（新） | 菜单首行控件：27px 圆形头像 + 标题 + 「请点击」，菜单关闭后再执行。 |
| `petcore/ui/menu_model.py` | 230（224） | `MenuItem.builder`，支持直接追加 `QWidgetAction`。 |
| `petcore/ui/menu_actions.py` | 298（283） | `quit` 子宠显示「退出这只」并走 `quit_from_menu`；`easter_egg` 挂 builder。 |
| `petcore/ui/easter_egg.py` | 256（253） | 导出 `DEFAULT_EASTER_EGG_TITLE` 供菜单行复用。 |
| `petcore/config.py` | 356 | 新增 `easter_egg_display`（`bubble`/`window`，默认 `bubble`）与归一化。 |

### 打包 / 菜单

| 文件 | 行数 | 改动意图 |
|---|---|---|
| `petcore/ui/menu_layout.py` | 519 | 新增 `BUILTIN_DEFAULT_LAYOUT`、`load_default_with_source()`、`merge_user_layout()`；模板缺失时回退内置常量。 |
| `petcore/ui/app.py` | 416+ | `reload_menu()` 把合并后的布局一次性写回 `config.menu_layout`。 |
| `petcore/cli.py` | — | `--check` 报告新增 `menu_template` / `menu_layout_diagnostics`（零 Qt）。 |
| `scripts/build_petcore.ps1` | — | `--add-data petcore/menu_templates;petcore/menu_templates`。 |
| `packaging/petcore.iss` | — | `DisableDirPage=no`、`UsePreviousAppDir=yes`、`DefaultDirName={code:GetDefaultDir}`；`[Code]` 读卸载键 `InstallLocation` 预选旧路径。 |

### 设置 / Core 特性

| 文件 | 行数 | 改动意图 |
|---|---|---|
| `petcore/ui/settings/base.py` | 398 | `tab()` 上下文管理器、`embed_page()`、内嵌页生命周期辅助、搜索定位同步页内分页按钮。 |
| `petcore/ui/settings/page_interaction.py` | 621 | 8 个页内分页；彩蛋「显示方式」；内嵌点击台词/自言自语/免打扰。 |
| `petcore/ui/settings/pages_core.py` | 515 | 菜单页拆「菜单编排 / 快捷启动」并内嵌快捷启动设置。 |
| `petcore/ui/settings/page_about.py` | 192 | 关于页拆「版本与诊断 / 链接与项目 / 网络信息 / 回收内存」。 |
| `petcore/ui/settings/page_extensions.py` | 398 | 导航顺序改为 扩展管理 → 基础 → 加装；组头可折叠；core/host_page 页不进导航。 |
| `petcore/ui/settings/page_mods.py` | 435 | Core 内置归基础且禁用启停/卸载；`.trusted` 与导入归加装。 |
| `petcore/mods/feature.py` | 254 | `CORE_FEATURE_IDS`、`GROUP_CORE/BASE/ADDON`、`host_page` 透传、`embedded_pages()`。 |
| `petcore/contracts/contributions.py` | — | `SettingsPageSpec.host_page`。 |
| `petcore/builtin/features/*/host/factory.py` | 7 个 | settings_page 贡献补 `host_page`。 |

### 测试

| 文件 | 行数 | 覆盖 |
|---|---|---|
| `tests/test_petcore_pet_push.py` | 213（新） | 推动站立宠、双向漫游不切 thrown、探头轻碰不取消、高速撞探头、子宠单独退出。 |
| `tests/test_petcore_bubble.py` | 145（新） | 跟随、no-op、图片缩放/标题、缩放后重排。 |
| `tests/test_petcore_easter_egg.py` | +84 | 气泡/窗口两种显示模式、空目录提示。 |
| `tests/test_petcore_menu.py` | +174 | builder、彩蛋行、quit 文案。 |
| `tests/test_petcore_menu_layout.py` | +6 条 | 内置常量=JSON、模板缺失回退、旧布局合并、写回落盘。 |
| `tests/test_petcore_installer.py` | + | 目录页/旧路径预选/打包数据断言。 |
| `tests/test_petcore_cli.py` | + | `--check` 新字段。 |
| `tests/test_petcore_settings.py` | 改 | 互动 8 分页、内嵌页保存/取消、显示方式。 |
| `tests/test_petcore_extensions_nav.py` | 改 | 折叠、分组、ModsPage 分类与禁用。 |
| `tests/test_petcore_builtin_mods.py` | 改 | `host_page` 映射与 core 分组。 |
| `tests/test_petcore_p5.py` | +3 | 旧用例“零速度也算撞上”改为真实接近速度，符合本轮口径。 |

### 文档

`docs/PETCORE-MAIN-PARITY-BACKLOG.md`（新）、`PETCORE-SPEC.md`（规则 17/26 + 27–32 + §12）、
`PETCORE-ROADMAP.md`（§18）、`PETCORE-ARCHITECTURE.md`（§18）、`PETCORE-MOD-FORMAT.md`（§8/§9）、
`docs/INDEX.md`、`petcore/AGENTS.md`、`petcore/README.md`、`README.md`、`PETCORE-LOG.md` L023、
`PETCORE-LOG-INDEX.md`。

## 三、实现要点

1. **碰撞状态机**：`impact_speed` 来自 `engine/collision.py` 的相对法向速度。只有
   `>= HIT_FEEDBACK_MIN_SPEED` 才写 `motion.set_velocity()`（它会切 `thrown`）；
   轻碰只 `move()`，随后把双方 `_move_plan` 的 `start/target` 平移同样的位移。
   这样走路动画的帧驱动位置与碰撞结果不互相覆盖。
2. **探头优先**：轻碰时用 `dataclasses.replace(body, static=True)` 给探头无限质量，
   分离只落在对方；对方若在漫游则 `abort_move_plan()` 回待机。真撞击保留原有
   `arm_throw_egg()` → `cancel("collision")` → 强制分离。
3. **气泡跟随**：`moveEvent` 只置一个 pending 标志 + `QTimer.singleShot(0)`，同一帧
   多次移动只重排一次；`reposition()` 用 `(anchor, size)` 缓存跳过无变化的调用。
4. **菜单模板兜底**：JSON 是权威，Python 常量是兜底；测试比对两者相等。`--check`
   报告来源，打包后可直接取证。
5. **设置内嵌**：`SettingsPage.tab()` 通过切换 `_section_layout` 让现有 `section()`
   代码零改动落入分页；`embed_page()` 复用内嵌页自己的滚动体与生命周期方法。
6. **Core 特性**：`CORE_FEATURE_IDS` 决定 group；`host_page` 决定设置归属。
   扩展管理在调用 factory 前就跳过 core/host_page，避免造第二份页面实例。
7. **安装向导**：`DefaultDirName={code:GetDefaultDir}` 比在 `InitializeSetup` 里改
   `WizardDirValue` 可靠（后者是只读属性）。

## 四、性能分析

**方法**：`PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/Scripts/python .scratch/perf_p8.py`
（best of 3，Windows 11 / Python 3.12.10 / offscreen；脚本在 `.scratch/`，不入库）

| 指标 | 实测 | 归属 |
|---|---|---|
| `load_default()+resolve()`（完整默认模板） | **282.8 µs/次** | 既有路径；只在右键/启动时调用，非逐帧 |
| `collide()` 一对三圆链 | **6.9 µs/次** | 既有热路径；16ms tick 下即使 16 只（120 对）也只占 ~0.83ms |
| `SpeechBubble.reposition()` 无变化 | **1.4 µs/次** | 新增；每帧最多一次（去抖后） |
| `QMenu` 构建（12 项） | **271.4 µs/次** | 既有路径；仅右键时 |

**结论**：

1. 稳态开销没有变化：碰撞 tick 未引入新分配（`dataclasses.replace` 只在探头轻碰分支
   发生，且该分支本来就每 tick 最多一次）。
2. 新增气泡跟随路径在“位置没变”时 1.4µs，且 `singleShot(0)` 合并同帧多次移动；
   拖拽/抛掷每 16ms 一次的调用量级可忽略。
3. 没有新增系统调用、网络、磁盘或线程；`load_default()` 仍读一次 JSON（283µs）。
4. 内存：`speech_bubble` 只多一个图片 pixmap（≤320×320）与两个 QLabel；
   彩蛋图片按需读取，不常驻。

## 五、实机运行记录

**环境**：Windows 11 10.0.26200，Python 3.12.10，`.venv`；Qt offscreen 仅用于自动化，
下面同时给出真实文件/真实配置的取证。

### 5.1 打包前（源码树）

```text
$ .venv/Scripts/python -m petcore --check
{"menu_template": "json", "menu_layout_diagnostics": [], ...}  # exit 0
```

- 用你本机真实 `%APPDATA%\dsh-pet-core\config.json`（旧 `menu_layout` 缺
  `animations_hub`/`easter_egg`）跑 `resolve()`，合并后顶层包含
  `character → animations_hub → playback_speed → pet_controls → tools_help →
  modern_settings → quit`，`tools_help` 内含 `easter_egg`。
- 模板缺失模拟（monkeypatch `importlib.resources.files` 抛错）：`menu_template=builtin`，
  菜单仍是完整默认布局，warning 只输出一次。

### 5.2 测试与静态检查

```text
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
  tests/test_petcore_*.py tests/test_architecture.py \
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
823 passed, 5 skipped in 27.32s

.venv/Scripts/ruff check pet/ tests/ petcore/
All checks passed!
```

### 5.3 打包与安装器

```text
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 -Clean -Installer
Successful compile (72.890 sec). Resulting Setup program filename is:
E:\Work\dsh-pet-0\dist\dsh-pet-core-setup.exe
installer: E:\Work\dsh-pet-0/dist/dsh-pet-core-setup.exe
```

产物取证（真实文件）：

| 项 | 结果 |
|---|---|
| setup 大小 | **178,532,356 字节** |
| 主 exe Subsystem | **2**（Windows GUI，无终端窗口） |
| `_internal/petcore/menu_templates/petcore-default-v1.json` | **存在**（本轮新增数据） |
| `_internal/petcore/builtin/{feature_demo,features}` | 存在（Core 内置特性随包） |
| `_internal/assets/big_blue_fat_fish` | 24 张图 |
| `_internal/assets/sounds/duck` | `Ya1/Ya2` 的 mp3 + wav |
| 冻结包 `mod_dirs` | `%APPDATA%\dsh-pet-core\mods`、`dist\dsh-pet-core\mods`、`dist\dsh-pet-core\_internal\mods` |
| 打包后 `--check` | exit 0，`menu_template=json`，`menu_layout_diagnostics=[]` |
| setup / app 图标 | `ExtractAssociatedIcon` 提取 32×32，目视为鲸鱼娘 |

- `petcore.iss` 编译成功；`[Code]` 的 `GetDefaultDir`/`InstallLocation` 通过编译。

### 5.4 未实机验证（需你在桌面确认）

- 多宠互推手感、探头被轻碰不倒下、子宠「退出这只」、气泡跟随拖拽/漫游。
- 设置页 8 个分页在 720×500 最小窗口下的翻页箭头。
- 安装向导每次显示路径页、重装时预选旧路径（会真装机，未自动执行）。
- 真实声卡上的音效与彩蛋图片显示效果（自动化只验证了 QPixmap/窗口对象）。
