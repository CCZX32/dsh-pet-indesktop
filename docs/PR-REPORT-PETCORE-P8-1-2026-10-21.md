# petcore P8.1：字号/彩蛋图片、菜单结构、弹弓与直播兼容

> **基线**：`feat/petcore-vpet-architecture`（P8 收口，未提交 git）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-21
> **范围**：配置/气泡/菜单/设置/窗口/平台 12 个实现文件 + 7 个新测试 + 文档
> **关联**：[`PETCORE-LOG.md`](PETCORE-LOG.md) L024、[`PETCORE-MAIN-PARITY-BACKLOG.md`](PETCORE-MAIN-PARITY-BACKLOG.md)

## 一、核心特性

本轮把主分支的「可调观感」补齐：界面字号、气泡字号、彩蛋图片大小、自言自语配图
概率都可配；右键菜单固定为「彩蛋在最顶、设置项在分界线上、分界线下方只有退出」，
播放速率默认隐藏；「播放动画」分类改为懒加载并带代表帧缩略图；弹弓发射后不再误弹
右键菜单；设置标题栏 X 也保存；点击台词对启动后的所有桌宠（含子宠）立即生效；
新增直播捕获兼容模式（Tool → 普通顶层 Window，含气泡）。

**红线 / 不变量**：彩蛋永远是菜单第一项；`modern_settings` 必须紧邻最后一条分界线
之上；缩略图解码不得在 GUI 线程；直播模式不得禁用多宠；X 保存与「取消」恢复必须
保持区分。

## 二、修改文件说明

> `petcore/` 在本分支为未跟踪文件，`git diff --numstat` 不适用；行数用当前 `wc -l`。

### 配置与观感

| 文件 | 改动意图 |
|---|---|
| `petcore/config.py` | 新增 `ui_font_size`(10–18)、`bubble_text_scale`(50–300)、`easter_egg_image_scale`(50–300)、`self_talk_image_dir/scale/chance`、`menu_animation_icons`、`stream_capture_mode`，全部进 `_normalize()`。 |
| `petcore/ui/bubble.py` | `set_text_scale()` / `text_scale()`；文本 QSS 字号/内边距按系数生成；`show_image(..., image_scale=)`；`set_stream_mode()` 切普通 Window。 |
| `petcore/ui/pet_window.py` | 应用 `bubble_text_scale`；新增 `show_image()` / `set_text_scale()`；彩蛋气泡按 `easter_egg_image_scale`；新增 `stream_capture_mode`、`set_stream_capture_mode()`、`_apply_flags()` 分支、`apply_stream_window` 调用；`_suppress_context_menu` 抑制弹弓右键菜单。 |
| `petcore/ui/easter_egg.py` | 弹窗边长 640→520，按 `easter_egg_image_scale` 钳 280–1200；`EasterEggPopup(..., image_scale=)`。 |
| `petcore/ui/easter_egg_entry.py` | 标题/提示字号从 `menu.font()` 派生，跟随 `ui_font_size`。 |
| `petcore/contracts/host.py` | `PresentationPort` 增加可选 `show_image()`。 |
| `petcore/ui/app.py` | `_PresentationAdapter.show_image()`；`migrate_p8_menu` 接线；菜单字号；`settings_dialog.refresh_style()`；stream live apply。 |

### 菜单与预览

| 文件 | 改动意图 |
|---|---|
| `petcore/menu_templates/petcore-default-v1.json` | 新顺序：彩蛋第一、播放速率隐藏、尾部 settings/separator/quit。 |
| `petcore/ui/menu_layout.py` | `BUILTIN_DEFAULT_LAYOUT` 同步；新增幂等 `migrate_p8_menu()`。 |
| `petcore/ui/menu_style.py` | `menu_stylesheet(dark, font_size=13)`，菜单字号与行高联动。 |
| `petcore/ui/menu_model.py` | `set_font_size()`，`_apply_style()` 传入菜单字号。 |
| `petcore/ui/menu_actions.py` | 播放动画分类懒加载 `aboutToShow`；随机动作按前缀分组；缩略图占位与回填；`menu_animation_icons` 开关。 |
| `petcore/media/thumbnails.py`（新） | 代表帧解码（帧序列/GIF/WebM）、内存 LRU 128、磁盘缓存、2 线程 QThreadPool。 |

### 交互与设置

| 文件 | 改动意图 |
|---|---|
| `petcore/ui/slingshot.py` | `suppress_until` + `suppresses_context_menu()`。 |
| `petcore/ui/settings/dialog.py` | `_commit()` 复用；`closeEvent` = 保存关闭；`reject()` 仍恢复快照；字号样式。 |
| `petcore/ui/settings/style.py` | `stylesheet(dark, font_size=13)`，标题/正文/提示按 base 派生。 |
| `petcore/ui/settings/pages_core.py` | 界面字号、气泡字号、播放动画预览开关、直播捕获兼容；保存/取消/搜索词同步。 |
| `petcore/ui/settings/page_interaction.py` | 彩蛋「图片大小」50–300%。 |
| `petcore/ui/ports.py` | `InteractionAdapter.attach_window()/detach_window()`，重复 attach 不重复触发。 |
| `petcore/ui/pet_manager.py` | spawn/restore 后补挂监听；`SHARED_KEYS` 加 `stream_capture_mode`。 |
| `petcore/platform/win.py` | `apply_stream_window(hwnd)` 清 Tool/NoActivate 位。 |
| `petcore/builtin/features/fun.self-talk/host/factory.py` | 出图概率/目录/大小；设置页三行。 |
| `petcore/builtin/features/fun.click-talk/host/factory.py` | `say(force=True)`。 |

### 测试

新增 `test_petcore_thumbnails.py`、`test_petcore_self_talk.py`、
`test_petcore_settings_close.py`、`test_petcore_stream_mode.py`、
`test_petcore_slingshot_menu.py`、`test_petcore_click_listeners.py`；
更新 `test_petcore_bubble.py`、`test_petcore_easter_egg.py`、`test_petcore_menu.py`、
`test_petcore_menu_layout.py`、`test_petcore_settings.py`。

## 三、实现要点

1. **缩略图**：worker 只产 `QImage`，queued signal 回 GUI 线程转 `QPixmap`；同一 key
   合并回调。内存 LRU 128（64px 级约 9–16KB/张），磁盘缓存按路径/mtime/size 哈希。
2. **懒加载**：根菜单只建分类；`aboutToShow` 才添加动作并请求缩略图。随机动作
   超过 20 项按前缀分组（≥4 项同前缀），避免一次 89 项。
3. **菜单迁移**：`migrate_p8_menu` 只改三项硬要求（彩蛋置顶、播放速率隐藏、
   尾部 settings/separator/quit），其余顺序保留；deepcopy 比较保证幂等。
4. **X 保存**：`_commit()` 统一保存页面、同步多宠、写盘、apply live；`closeEvent`
   失败时 `ignore()`，不会丢数据。
5. **直播模式**：Qt flags 与 Win32 样式同时切；气泡也切成普通窗口，避免只有桌宠
   被捕获、气泡缺失。
6. **点击监听**：`InteractionAdapter` 保存回调，窗口按 identity 去重；新子宠在
   spawn/restore 后补挂，避免「只有第一只宠能点」。
7. **弹弓**：右键进瞄准置抑制标志；`launch/cancel` 后 0.35s 冷却覆盖「右键晚松」。

## 四、性能分析

**方法**：`QT_QPA_PLATFORM=offscreen`，Windows 11 / Python 3.12.10；缩略图单帧实测来自
`petcore.media.thumbnails.decode_thumbnail`（64×36 输出）。

| 指标 | 实测 | 归属 |
|---|---|---|
| 帧序列缩略图（242 帧取 62%） | **18.2 ms/张** | 新增后台解码 |
| WebM 缩略图（真实素材） | **668 ms/张** | 新增后台解码，2 线程 |
| 根菜单构建 | 只建 6 个分类子菜单，**0 个动画动作** | 新增懒加载 |
| 首个分类展开 | **1 个动作 + 图标**（实测） | 新增 |
| 气泡 `reposition` 无变化 | 1.4 µs/次（P8 实测，本轮未改） | 既有 |

**结论**：

1. 稳态无逐帧开销：缩略图只在菜单展开时后台解码；`menu_animation_icons=False`
   时完全不发起。
2. 新增路径成本集中在「首次展开分类」：帧序列约 18ms/张，WebM 约 0.7s/张在后台；
   GUI 线程只转 pixmap。106 个动画不会在根菜单构建时阻塞。
3. 内存：LRU 128 张 64px 图约 1–2 MB；磁盘缓存可复用。
4. 没有新增网络/系统调用；`stream_capture_mode` 只在切换时改窗口 flags。

## 五、实机运行记录

**环境**：Windows 11 10.0.26200，Python 3.12.10；offscreen 用于自动化，真实文件/配置
用于菜单取证。

### 5.1 真实配置迁移与菜单顺序

用你本机 `%APPDATA%\dsh-pet-core\config.json` 的副本（临时根）跑完整
`CoreHost + PetManager + create_primary + attach_window + restore + reload_menu`：

```text
top: ['彩蛋图片', '切换角色', '', '播放动画', '桌宠控制', '', '工具与帮助', '',
      '扩展', '', '桌宠设置', '', '退出']
stored first id: easter_egg
anim groups: 待机/转向/移动/点击回应/随机动作/事件·余额，展开前均为 0 项
group actions after aboutToShow: 1, icons: [True]
```

### 5.2 测试与静态检查

```text
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
  tests/test_petcore_*.py tests/test_architecture.py \
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
879 passed, 5 skipped in 56.53s

.venv/Scripts/ruff check pet/ tests/ petcore/
All checks passed!

.venv/Scripts/python -m petcore --check
exit 0, menu_template=json
```

### 5.3 打包与安装器

```text
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 -Clean -Installer
Successful compile (104.250 sec). Resulting Setup program filename is:
E:\Work\dsh-pet-0\dist\dsh-pet-core-setup.exe
```

真实产物取证：

| 项 | 结果 |
|---|---|
| setup 大小 | **185,796,682 字节** |
| 主 exe Subsystem | **2**（无终端窗口） |
| `_internal/petcore/menu_templates/petcore-default-v1.json` | 存在 |
| 打包后 `--check` | exit 0，`menu_template=json`，`menu_layout_diagnostics=[]` |
| 冻结 exe 内的模块 TOC | 含 `petcore.media.thumbnails`、`petcore.ui.easter_egg_entry` |
| setup 图标 | `ExtractAssociatedIcon` 32×32，目视为鲸鱼娘 |

### 5.4 未实机验证（需你在桌面确认）

- 设置页字号 10/18、气泡 50%/300%、彩蛋图片 300% 的实际观感与 DPI。
- OBS/直播姬真实捕获（捕获方式选 Windows 10 1903+；BitBlt 黑屏）。
- 弹弓发射后右键不再弹菜单的真实时序（自动化已覆盖）。
- 缩略图在真实 WebM 角色上的首展开等待与清晰度。
- 安装向导每次显示路径页与旧路径预选（会真装机）。

---

## 第二轮改进（P8.2，2026-10-21）

**修改文件说明**

- `petcore/ui/pet_window.py`：`say()`/`show_image()` 在 `isVisible()` 为假时直接返回；
  `set_visible(False)` 收起气泡；`quit_from_menu()` 的托盘刷新延后到下一事件循环。
- `petcore/ui/app.py`：`_PresentationAdapter._window()` 优先选可见桌宠；
  新增 `set_all_visible()/toggle_all_visible()/build_tray_menu()/_toggle_one()`；
  托盘刷新统一 `QTimer.singleShot(0, ...)`。
- `petcore/ui/tray.py`：支持 `toggle_visibility` 回调（左键/双击切换显示）；
  菜单替换时保留旧菜单到下一轮再释放。
- `petcore/ui/settings/page_interaction.py`：彩蛋页改名「彩蛋与配图」，加入自言自语
  配图目录/大小/出图概率；快照/保存/取消同步这三个键。
- `petcore/builtin/features/fun.self-talk/host/factory.py`：移除重复的配图设置行，
  只保留节奏与台词；运行时仍读同一批配置键。
- 测试：新增 `tests/test_petcore_tray.py`；`tests/test_petcore_bubble.py` 增加隐藏态
  气泡断言；`tests/test_petcore_self_talk.py` 改为断言配图设置已归位。

**性能分析**：隐藏态判断是每气泡一次 `isVisible()`（O(1)）；托盘菜单只在托盘刷新时
重建（最多每次点击一次），延迟释放旧 QMenu 不新增常驻开销。无逐帧路径变化。

**实机运行记录**

```text
QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py tests/test_architecture.py   tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
879 passed, 5 skipped
```

重打包（P8.2）：

```text
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/build_petcore.ps1 -Clean -Installer
Successful compile (99.860 sec). Resulting Setup program filename is:
E:\Work\dsh-pet-0\dist\dsh-pet-core-setup.exe
```

- setup 大小 **185,805,307 字节**；主 exe `Subsystem=2`；
  `_internal/petcore/menu_templates/petcore-default-v1.json` 存在；打包后 `--check`
  exit 0、`menu_template=json`。

真实托盘单击/右键与隐藏态联动的桌面验收仍需你确认（offscreen 无法模拟系统托盘）。

---

## 第三轮改进（P8.3，2026-10-21）

**修改文件说明**

- `petcore/ui/tray.py`：`Context` 激活不再 refresh；`refresh()` 优先调用菜单的
  `_petcore_refresh`（原地重建动作），只在没有该钩子时替换菜单。
- `petcore/ui/app.py`：`build_tray_menu()` 拆出 `populate_tray_menu()` 并接
  `QMenu.aboutToShow`；托盘父对象改为 None；feature/mod 诊断写入日志。
- `petcore/media/talk_images.py`（新）：配图目录解析、可读图过滤、
  `pick_choice()`（先决定出图/出文字）、概率/大小读取。
- `petcore/builtin/features/fun.self-talk/host/factory.py`：用 `pick_choice()`；
  `try/finally` 保证异常后继续排队；图片目录回退内置；记录 kind/dir/images/shown。
- `petcore/builtin/features/fun.click-talk/host/factory.py`：点击台词也按同一概率出图，
  失败回退 `say(force=True)`。
- `petcore/ui/pet_window.py`：`show_image()` 检查气泡是否真的可见。
- `petcore/ui/settings/page_interaction.py`：「当前目录」信息 + 「预览配图」按钮。
- `petcore/cli.py`：`--check` 增加 `self_talk_images`（count/readable/builtin）。
- 测试：`test_petcore_self_talk.py`（100% 出图、坏目录回退、异常后继续排、
  点击出图）、`test_petcore_tray.py`（Context 不替换、aboutToShow 原地重建）、
  `test_petcore_cli.py`（新字段）。

**性能分析**：配图选择是一次 `iterdir` + 每个文件一次 `QImageReader.canRead`（仅
chance 命中时；目录 24 张、单次 <10ms）。托盘菜单只在 `aboutToShow` 重建动作，无
新增长驻对象；`--check` 新增 24 次 `canRead`（一次性诊断）。

**实机运行记录**

```text
QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py tests/test_architecture.py \
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
887 passed, 5 skipped
ruff check pet/ tests/ petcore/  → All checks passed
```

源码探针（真实 config 副本）：chance=100 出 160×160 图片；坏目录回退内置仍出图；
点击出图；托盘隐藏后 `aboutToShow` 首项变「显示桌宠」并能唤回。

安装包取证：`dist/dsh-pet-core/dsh-pet-core.exe --check` 返回

```json
"self_talk_images": {"count": 24, "readable": 24, "builtin_count": 24, "builtin_readable": 24}
```

说明安装包的素材路径与 Qt 图片插件都能读到 24 张内置图。
setup 大小 **185,797,398 字节**（ISCC 100.859s），主 exe `Subsystem=2`。
真实托盘右键仍需桌面确认。

---

## 第四轮改进（P8.4，2026-10-21）

### 修改文件说明

| 文件 | 改动 | 原因 |
|---|---|---|
| `petcore/menu_templates/petcore-default-v1.json` | 删除 `pet_controls` 下的 `click_through`（-1 行） | 鼠标穿透移到托盘菜单 |
| `petcore/ui/menu_layout.py` | `BUILTIN_DEFAULT_LAYOUT` 同步删除；新增 `migrate_p9_menu()` + `_clean_submenu_children()`（+38 行） | 旧用户布局里的该项要幂等摘除 |
| `petcore/ui/menu_actions.py` | 删除 `click_through` MenuItem（-8 行） | 菜单模型不再注册该项 |
| `petcore/ui/settings/coverage.py` | 删除 `click_through` 映射（-1 行） | 菜单项与设置项的对应表同步 |
| `petcore/ui/app.py` | `reload_menu()` 串行 p8→p9 迁移；托盘菜单加可勾选「鼠标穿透」；新增 `_windows()/all_click_through()/set_all_click_through()`（+55 行） | 托盘是穿透状态下唯一稳定的恢复入口 |
| `petcore/media/images.py`（新） | `sanitize_dpr/screen_dpr/physical_side/scale_pixmap/load_pixmap/logical_size`（118 行） | 统一「逻辑上限 × DPR」的装载口径 |
| `petcore/ui/easter_egg.py` | `load_scaled_pixmap(..., dpr)` 走新模块；`EasterEggPopup(..., dpr=)`；label/窗口用逻辑尺寸；控制器传宠物屏 DPR（±20 行） | 修 1.5 倍屏上彩蛋图发虚 |
| `petcore/ui/bubble.py` | `_scaled_pixmap(..., dpr)`、`show_image(..., dpr=)`、label 用逻辑尺寸；去掉不再使用的 `QImageReader/QSize` 导入 | 气泡配图同样二次放大 |
| `petcore/ui/pet_window.py` | `show_image()` 传 `screen_dpr(self)`（+2 行） | 气泡按桌宠所在屏取 DPR |
| `petcore/ui/easter_egg_entry.py` | `_round_pixmap(pixmap, dpr)` 物理边长 27×DPR；`avatar_pixmap()` 按 DPR 预缩放（+18 行） | 菜单头像同一问题 |
| `tests/test_petcore_images.py`（新） | 7 条：DPR 兜底、物理上限换算、大图/小图、已有 pixmap、弹窗/气泡逻辑尺寸 | 把口径钉死 |
| `tests/test_petcore_tray.py` | FakeWindow 支持 `click_through/say`；新增托盘穿透一次作用全部桌宠 | 覆盖新入口 |
| `tests/test_petcore_menu_layout.py` | 默认顺序断言去掉该项；新增 p9 迁移幂等 + 模板不含该项 | 规格变更 |

### 性能分析

- **装载成本**：仍是一次 `QImageReader.read()` + 一次平滑缩放，只是目标尺寸从
  520/320 变成 780/480（1.5×DPR），像素量 2.25 倍。同一张
  `assets/big_blue_fat_fish/big_blue_fat_fish.jpg`（850²）实测（offscreen，各 10 次
  均值）：彩蛋装载 dpr=1 **6.4 ms** / dpr=1.5 **6.8 ms**；气泡装载 320 逻辑
  **5.9 → 6.4 ms**；作为对照，旧路径（`QImageReader.setScaledSize` 到逻辑尺寸）
  **4.4 ms**——新路径多出约 2.0–2.4 ms。彩蛋/配图都是点击或定时触发（自语默认
  30% 概率），不在每帧路径上。
- **内存**：单张弹窗 pixmap 由 520²×4 ≈ 1.08 MB 变为 780²×4 ≈ 2.43 MB；气泡配图
  320→480，0.41 MB → 0.92 MB。弹窗/气泡都随内容销毁，没有新增常驻缓存。
- **托盘**：新增 1 个 QAction 与一次 `all_click_through()`（N 只宠的布尔读取），
  只在菜单弹出时执行；`set_all_click_through()` 是 O(N) 配置写盘，与已有
  「显示/隐藏全部」同量级。无新线程、无网络、无新增系统调用。
- **迁移**：`migrate_p9_menu()` 只遍历一次布局树，命中才写盘；未命中不产生 IO。

### 实机运行记录

```text
QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py tests/test_architecture.py \
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
897 passed, 5 skipped in 39.09s
ruff check pet/ tests/ petcore/  → All checks passed!
```

屏幕探针（真实平台，非 offscreen）：

```text
TM140VDXP02 geom 1280 800 dpr 1.5 logicalDpi 96.0 avail 752
```

锐度 A/B（`QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5`，同一张
`big_blue_fat_fish.jpg`，弹窗整体 grab 816×900，梯度能量＝平均 |Laplacian|）：

```text
dpr 1.0  label (520, 520)  grab 816 900  sharpness 10.99   ← 旧路径
dpr 1.5  label (520, 520)  grab 816 900  sharpness 16.37   ← 新路径（+49%）
```

源码探针（真实 config 副本 + `QT_SCALE_FACTOR=1.5` 模拟本机 1280×800 桌面，
offscreen 渲染；`.scratch/p84_probe.py`）：

```text
screen dpr 1.5
layout after migrate has click_through: False
registered has click_through:          False
tray labels: [隐藏桌宠, 鼠标穿透, <separator>, 桌宠设置, 打开数据目录]
tray checkable: True checked: False
pet click_through after tray toggle: True  bubble: 已开启鼠标穿透，可从托盘菜单关闭
windows all click-through: True
re-open checked: True
after off: False  bubble: 已关闭鼠标穿透
bubble image phys (480, 480) dpr 1.5 label logical (336, 336)
popup (544, 600) image label (520, 520) pixmap phys (780, 780) dpr 1.5 constructed dpr 1.5
```

气泡/弹窗手写的 `force=` 曾在真实 `PetWindow.say()` 上抛 `TypeError`（被
`except` 吞掉，表现是「点了没提示」）；本轮改成 `say(message, 5000)`，测试替身也
换成真实签名，避免再次被 `**kwargs` 掩盖。

打包取证（`pwsh -File scripts/build_petcore.ps1 -Installer`，增量构建）：

```text
Successful compile (56.234 sec). Resulting Setup program filename is:
E:\Work\dsh-pet-0\dist\dsh-pet-core-setup.exe
```

- `dist/dsh-pet-core-setup.exe` = **185,809,452 字节**（2026-10-21 22:19:09）
- 主 exe **Subsystem=2**（无终端窗口）
- 打包后 `dsh-pet-core.exe --check` exit 0，`menu_template=json`，
  `self_talk_images.readable=24`
- 包内 `_internal/petcore/menu_templates/petcore-default-v1.json` 已无 `click_through`
- 直接读包内 PYZ 验证新代码进包：`petcore.media.images(load_pixmap/scale_pixmap/
  logical_size)`、`menu_layout.migrate_p9_menu`、`bubble.set_host_on_top`、
  `app.set_all_click_through` 全部存在；`pages_core` 的提示文案是新版
  「…可从托盘菜单关闭」。

### 追加修复（P8.4b，2026-10-21）：图片气泡与桌宠不同图层

**修改文件说明**

- `petcore/ui/bubble.py`：新增 `_window_flags()` / `_apply_window_flags()` /
  `set_host_on_top()` / `host_on_top()`；`SpeechBubble` 构造时应用旗标，补
  `WindowDoesNotAcceptFocus`；`set_stream_mode()` 复用同一个旗标入口（±40 行）。
- `petcore/ui/pet_window.py`：`_apply_flags()` 末尾
  `self.bubble.set_host_on_top(self.always_on_top)`（+2 行）。
- `petcore/ui/easter_egg.py`：`EasterEggPopup(..., on_top=True)`；
  `EasterEggController.show()` 传宿主的 `always_on_top`（+8 行）。
- 测试：`test_petcore_bubble.py` 增加 `test_bubble_keeps_the_pet_layer`、
  `test_text_and_image_bubbles_share_the_same_window`；
  `test_petcore_easter_egg.py` 增加 `test_popup_follows_the_host_topmost_flag`。

**根因**：桌宠默认 `always_on_top=True`，窗口带 `WindowStaysOnTopHint`；而
`SpeechBubble` 只有 `Qt.Tool | FramelessWindowHint`，永远排在 topmost 窗之下。
文字气泡贴在头顶、面积小，看不出被压；图片气泡（320 逻辑像素见方 + 卡片）会压到
角色身上，于是表现为「图片气泡掉到桌宠下面」。主分支
`pet/speech_bubble.set_host_on_top()` 早就做了这件事，petcore 漏了。

**性能分析**：只在 `always_on_top` 变化时重建一次旗标（`setWindowFlags` 是
重建原生窗的操作，属于低频设置变更）；气泡显示路径没有新增调用。无新线程/IO。
`set_stream_mode` 现在走同一函数，行为等价（少一次重复实现）。

**实机运行记录**

```text
QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_easter_egg.py tests/test_petcore_bubble.py -q
27 passed
```

覆盖：置顶开 → 气泡/弹窗都带 `WindowStaysOnTopHint`；置顶关 → 两者同步失去；
文字气泡与图片气泡是同一个窗口、旗标完全相同。
