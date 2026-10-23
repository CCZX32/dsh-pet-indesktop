# PR 报告：P4-b2 扩展分组、可卸载 mod、气泡分页与音乐识别（2026-10-23）

> **基线**：`8695f172`（P4-b：SpeechPort / 报时 / 音乐歌词）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-23
> **范围**：38 个文件（实现 30、测试 5、文档 3；无新增/删除文件）
> **关联**：`docs/PETCORE-ROADMAP.md` §25、`docs/PETCORE-MOD-FORMAT.md` §13、`docs/PETCORE-SPEC.md` §25

## 一、核心特性

本批把「扩展」从平铺列表变成按 mod 分组的两级结构，补上 mod 卸载闭环，并把气泡与音乐
识别对齐主分支的可读性口径。用户可见变化：

| # | 能力 | 说明 |
|---|---|---|
| 1 | 右键「扩展」按 mod 分组 | 每个 mod 一个二级子菜单（中文名来自 `name_zh`），项按 `order` 排；Core 内置特性不再混入 |
| 2 | mod 设置页 H2 + H3 | 一个 mod 一个二级标题，功能组用三级标题；音乐页固定五组 |
| 3 | 随安装包的扩展可卸载 | `.trusted` 包也能在设置里卸载；按 `install.json` 清单删文件，未知文件保留，个人数据不动；删除前处理未保存的设置 |
| 4 | 气泡最大宽度与长文本 | 列宽 248→360 自适应；长文本分页（短 3 行/长 6 行）+ 页码点 + 滚轮翻页 |
| 5 | 气泡副标题 | 音乐歌词气泡带「我在唱《…》」小字，纯音乐「正在听《…》」 |
| 6 | 音乐识别范围 | 可只识别已配置路径的播放器；额外识别名兜住 AUMID 不等于 exe 名的情况 |
| 7 | 音乐设置页切歌 | 播放/暂停、上一首、下一首、停止四个按钮，与右键菜单同一实现 |
| 8 | 工具与帮助三个入口核验 | DeepSeek / GitHub / 夸克已在模板与 `tool.links` 中；补回归测试 |

**红线 / 不变量**：卸载只删受管包目录，个人数据与配置键保留；点击气泡仍然只打开快速对话
（滚轮翻页不得吃掉点击）；气泡与桌宠同层；`CORE_FEATURE_IDS` 不进扩展菜单；安装器
卸载仍能清理 `{app}\mods`。

## 二、修改文件说明

### 设置层级与分组

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `petcore/ui/settings/base.py` | +15 / −3 | 新增 `group_heading()`（H2）与 `section(..., level=3)`（H3），H3 卡片左缩进 12px |
| `petcore/ui/settings/style.py` | +13 / −0 | `QLabel#groupTitle` / `QLabel#subsectionTitle` 两级标题样式 |
| `petcore/ui/menu_model.py` | +32 / −6 | `_populate_extensions()` 按 owner 分组；新增 owner 显示名与跳过集合 |
| `petcore/ui/app.py` | +63 / −3 | 从 manifest 取 `name_zh` 填 owner_labels；卸载闭环 `uninstall_mod()` / `_drop_modules_under()`；`say()` 透传副标题（空串走旧签名） |
| `examples/petcore-mods/ai.chat/host/settings_page.py` | +6 / −5 | H2「AI 对话」+ 原分组降 H3 |
| `examples/petcore-mods/fun.divination/host/factory.py` | +2 / −1 | H2「抽签」+ H3 |
| `examples/petcore-mods/fun.festival/host/factory.py` | +2 / −1 | H2「节日提醒」+ H3 |
| `examples/petcore-mods/reminder.todo/host/factory.py` | +2 / −1 | H2「待办提醒」+ H3 |
| `examples/petcore-mods/tool.file-reader/host/settings_page.py` | +2 / −1 | H2「文件解读」+ H3 |
| `examples/petcore-mods/tool.weather/host/settings_page.py` | +2 / −1 | H2「天气」+ H3 |
| `examples/petcore-mods/voice.chime/host/settings_page.py` | +5 / −4 | H2「语音报时」+ 4 个 H3 |

### 卸载闭环

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `petcore/mods/install.py` | +112 / −9 | `read_install_files()` / `_remove_listed()` / `remove_at()`：清单删除、生成物清理、未知文件保留、trusted 包整目录删除、边界校验 |
| `petcore/mods/state.py` | +8 / −0 | `clear()`：卸载后清停用记录 |
| `petcore/mods/feature.py` | +10 / −0 | `stop_owner()`：只停被卸载扩展的 runtime |
| `petcore/ui/settings/page_mods.py` | +24 / −9 | trusted 包可卸载；确认文案说明保留个人数据；卸载交给 ExtensionsPage |
| `petcore/ui/settings/page_extensions.py` | +63 / −0 | `uninstall_mod()` / `_drop_page()`：草稿三选一、删页面、刷新导航 |
| `packaging/petcore.iss` | +3 / −0 | `[UninstallDelete] {app}\mods` 清 `__pycache__` 等残留 |

### 气泡与音乐

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `petcore/ui/bubble.py` | +249 / −17 | `column_for_text()`、`paginate_text()`、页码点、滚轮翻页、`bubblePanel` + 副标题、屏幕高度夹取 |
| `petcore/contracts/host.py` | +9 / −2 | `PresentationPort.say` / `PetHandle.say` 增 `subtitle` |
| `petcore/ui/pet_window.py` | +4 / −2 | `say(..., subtitle=)` 透传到 `bubble.show_text()` |
| `petcore/ui/ports.py` | +2 / −2 | `PetHandleImpl.say` 透传副标题（空串走旧签名） |
| `examples/petcore-mods/media.music/host/now_playing.py` | +81 / −13 | `allowed_app_ids()`；选择器与传输控制接受 `allowed_ids`；被挡下时点名播放器 |
| `examples/petcore-mods/media.music/host/runtime.py` | +68 / −17 | 过滤集合每秒重算；`_say_sung()` 副标题（旧端口回退纯文本）；纯音乐「正在听」 |
| `examples/petcore-mods/media.music/host/settings_page.py` | +129 / −6 | H2/H3 重排；识别范围（开关 + 额外识别名）；切歌四按钮；检测结果显示识别名 |
| `petcore/config.py` | +10 / −0 | `music_filter_enabled` / `music_filter_extra_ids` 进 GLOBAL/DEFAULTS/归一化 |

### 测试与文档

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_petcore_bubble.py` | +54 / −3 | 列宽、分页/页码、滚轮翻页、副标题、缩放重排 |
| `tests/test_petcore_install.py` | +41 / −1 | 清单删除保留未知文件、trusted 删除、停用记录清理 |
| `tests/test_petcore_menu.py` | +27 / −0 | 扩展菜单按 owner 分组、Core 内置跳过 |
| `tests/test_petcore_music_mod.py` | +66 / −0 | 识别名推导、白名单选择、过滤只在开启时下传、副标题 |
| `tests/test_petcore_extensions_nav.py` | +4 / −4 | trusted 包可卸载的新口径 |
| `docs/*`、`petcore/AGENTS.md` | +80 / −8 | SPEC §25、ROADMAP §25、MOD-FORMAT §13、parity §12、LOG L047、红线 |

### 故意未改动

- `petcore/ui/menu_layout.py` 与 `menu_templates/*.json`：分组发生在 `extensions_hub` 的运行时填充，模板 schema 不变。
- `petcore/builtin/features/*`：7 个 Core 内置特性的设置页仍是 H2 分组（它们不是独立 mod）。
- `petcore/market/*`：市场安装/回滚与卸载是两条链，本轮只改 `mods` 卸载。

## 三、实现要点

1. **卸载顺序**：`FeatureManager.stop_owner()` → `menu_model.unregister_owner()` →
   清包目录下的 `sys.modules` → `install.remove_at()` → `reload_mods()`。先撤贡献再删，
   避免 Windows 上 `.pyd/.dll` 占用导致半删。
2. **清单删除**：`install.json` 的 `files` 是安装时逐文件摘要（原本只写不读）。删除时按
   深度倒序，`__pycache__`/`*.pyc` 视为生成物，未登记文件保留并报数量；无清单的
   `.trusted` 包整目录删除，仍校验 `mods_root/<id>` 与 `mod.json`。
3. **草稿保护**：`ExtensionsPage.uninstall_mod()` 找到该 owner 的设置页，`dirty()` 时
   询问「保存 / 放弃 / 取消」；取消即不删。
4. **菜单分组**：`MenuItem.owner` 聚合，组内按 `(order, label)`；单菜单项的 mod 也建
   子菜单，保证结构可预期。
5. **气泡分页**：`column_for_text()` 按字数放宽列宽并乘字号、再按屏宽收敛；
   `paginate_text()` 逐字测量折行；长文本每页 6 行、短文本 3 行；页码点 + 滚轮；
   点击仍发 `clicked`。副标题与正文放在同一个 `bubblePanel`，避免两个背景层。
6. **音乐过滤**：识别名 = 已配置 exe 文件名（去 `.exe`、小写）+ 额外识别名；
   否决表仍是第二道闸；过滤同时作用于唱歌、歌词与传输控制；被挡下时
   `read_playback_with_reason()` 点名播放器，不静默为空。
7. **副标题兼容**：旧端口/测试替身不接受 `subtitle` 时回退纯文本，避免 mod 因端口升级崩溃。

### 参考评估（VPet / codex/phase3-worker）

- **VPet**：mod 是「目录即包」，启动扫描加载，没有安装数据库；卸载等价于删受管目录 +
  重启，个人数据不在包目录里。可借鉴的是**包目录与个人数据分离**与「卸载=删受管目录」
  的简单口径；它没有逐文件清单校验，这部分不能照抄。
- **codex/phase3-worker**（tip `11646bee`）：有完整事务状态机、版本租约与跨进程 IPC。
  本轮只复用三件：① 按清单删除、未知残留保留；② 「有未知残留不猜着删 / 等待释放 ≠
  已删除」两不变式；③ 卸载前对扩展设置页做 `dirty()` 三选一。不可复用事务状态机与
  租约（petcore 设置与主程序同进程、每实例独立数据根），也不把它当已验证参考——
  该分支的 ZIP→卸载闭环有已知未修缺陷。
- 落地取舍：不引入 journal/revision，进程内一次「撤贡献 → 删文件 → 重扫」即可；
  卸载后不热重载已导入的 Python 模块（需要重启彻底释放）。

## 四、性能分析

环境：Windows 11、Python 3.12、PySide6 6.x、`QT_QPA_PLATFORM=offscreen`。
命令：`PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/Scripts/python .scratch/p4b2_bench.py`
（脚本不入库，只在本机跑）。

| 路径 | n | 中位 | p95 | 触发频率 | 结论 |
|---|---|---|---|---|---|
| `column_for_text` | 20000 | 1.5 µs | 2.3 µs | 每次 `show_text()` | 可忽略 |
| `paginate_text`（1600 字，5 页） | 2000 | 241 µs | 521 µs | 每次 `show_text()` / 缩放 | 可接受；优化前 4.69 ms（逐字建候选串 O(n²)），改为逐字宽度缓存后降 19 倍 |
| `allowed_app_ids`（8 条路径） | 20000 | 7.7 µs | 14.3 µs | 音乐轮询 1 Hz | 可忽略（每秒 0.0008%） |
| 菜单构建（12 mod × 3 项） | 200 | 989 µs | 2.3 ms | 打开右键菜单时 | 一次性，与旧版同量级 |
| `read_install_files`（51 文件） | 5000 | 589 µs | 1.0 ms | 卸载时一次 | 可忽略 |
| `remove_at`（50 文件 + install.json） | 20 | 127 ms | 148 ms | 用户点卸载时一次 | 主要是 Windows 文件删除与杀软扫描；一次性动作，不进稳态 |

- **稳态开销**：气泡渲染新增一次分页计算（≤0.5 ms，只在冒泡时）；音乐过滤每秒 8 µs；
  菜单分组只在构建菜单时发生。
- **新增系统调用/线程/网络/磁盘**：无。卸载路径新增文件删除（用户主动触发）。
- **内存**：无模块级缓存；折行宽度表是每次调用的临时 dict，随文本长度有界。

## 五、实机运行记录

```
$ .venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods
All checks passed!
$ .venv/Scripts/python -m petcore --check
diagnostics: []
menu_template: json
mods: [('fun.divination', True), ('fun.festival', True), ('media.music', True), ('reminder.todo', True), ('voice.chime', True)]
exit 0
```

- 聚焦测试：`test_petcore_bubble.py`、`test_petcore_install.py`、`test_petcore_music_mod.py`、
  `test_petcore_menu.py`、`test_petcore_extensions_nav.py`、`test_petcore_settings.py` → 全绿；
  全量门禁：`pytest tests/test_petcore_*.py tests/test_architecture.py
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q` → **1297 passed**（109.57s）。
- 构建：`scripts/build_petcore.ps1 -Clean -Installer -SignThumbprint …` 成功，
  `dist/dsh-pet-core-setup.exe` 258,522,344 B，签名 `CN=DSH Pet Core Dev, O=DSH Pet, C=CN`。
- 安装：静默装到 `E:\dsh-pet-core`，`/TASKS` 勾选 9 个扩展；安装目录 `mods/` 下 9 个包
  齐全。用干净 `APPDATA` 跑安装版 `--check`：`diagnostics: []`、`menu_template: json`、
  9 个 mod 全部 enabled（`ai.chat 1.4.0`、`media.music 1.1.0`、`voice.chime 1.1.0`，
  其余 1.0.0）。
- 安装版卸载实测：对 `{app}\mods\tool.weather` 调 `remove_at()` → 返回
  `(True, 'removed tool.weather')`、目录消失、`--check` 列表少一项；从
  `examples/petcore-mods/tool.weather` 复制回去并补 `.trusted` 后，列表恢复、诊断仍为 `[]`。
  这条验证删除器本身；安装器 `[UninstallDelete]` 需整包卸载才触发。
- 真实 `%APPDATA%` 下 `--check` 出现 5 条 `duplicate mod id … overridden by
  E:\dsh-pet-core\mods\…`：这是旧轮次装在用户数据目录的同名包与安装版并存，loader
  以安装目录为准；不作为失败，也不删除用户数据。
- 7 个示例 mod 设置页用 `FeatureManager` 真实装载 + offscreen 实例化探针：每页恰好 1 个
  `groupTitle`、H3 顺序与预期一致（`.scratch/verify_mod_h2h3.py`，不入库）。
- 音乐设置页用真实 `MusicPage` 构造（offscreen）验证 H2/H3、识别范围开关、切歌按钮；
  未播放音乐，只验证静态构建与配置读写。另用 `stylesheet(dark, 13)` 渲染
  `.scratch/p4b2-music-settings.png`（980×1180）人工复核：H2「音乐」+ 5 个 H3 分组、
  识别范围输入框、四个切歌按钮、播放器路径行都在可视区内，无横向裁切
  （offscreen 环境缺 CJK 字体，字形显示为方框，布局判断不受影响）。

## 六、未验证项

1. **真实播放器下的识别范围**：本机无播放器在播，`allowed_app_ids` 与实际 SMTC
   `source_app_user_model_id` 的对应关系只按代码与注释口径实现；汽水音乐这类中文 AUMID
   需要用户在「额外识别名」里补。
2. **安装器整包卸载**：`{app}\mods\<id>` 的删除已用安装版目录实测；Inno
   `[UninstallDelete] {app}\mods` 只在整包卸载时触发，本轮没有卸载整个应用，
   所以这条仍未实测。
3. **设置页内的卸载按钮**：`ExtensionsPage.uninstall_mod()` 的 UI 路径（草稿询问、
   删页面、刷新导航）只跑了 offscreen/单元测试，没有在真实设置窗口里点过。
4. **滚轮翻页**：offscreen 下验证了 `next_page()/previous_page()` 与分页状态；真实滚轮事件
   与两页之间的计时未在桌面环境跑。
5. **300% 字号 + 1.5 倍屏**：只做 offscreen 尺寸断言，未做像素级截图复核。
6. **Python 模块热卸载**：卸载后 `reload_mods()` 不重载已导入的 C 扩展/第三方模块；
   彻底释放仍需重启进程。

## 七、第二轮修正（2026-10-23，P4-b2.1）

用户实测反馈三个问题：① 音乐设置「网易云音乐路径」的提示被压成一字一行；
② 右键「扩展」仍是平铺列表，DeepSeek/GitHub/夸克也在扩展里；③ 4 个汉字的气泡
被折成两行且显示不全。定位与修复如下。

### 7.1 根因

1. **菜单分组被 layout children 绕过**：`_append_mod_actions()` 把 mod action 追加进
   `extensions_hub.children`；`MenuModel._append_node()` 先把 children 平铺渲染并标记
   `placed`，`_populate_extensions()` 随后无项可分。旧 `menu_layout` 还把
   `tool.links:*` / 快捷启动 / 网络信息 / 回收内存 / 免打扰 留在 hub，所以「工具与帮助」
   一直是空的。与打包无关。
2. **设置宽行**：`add_row(expand=True)` 仍用水平布局，文字列没有最小宽度；路径行控件
   `QLineEdit(minWidth=260)+浏览` 把文字列挤到 1–2 字宽。
3. **气泡尺寸**：`wordWrap=True` + `setMaximumWidth()` + `adjustSize()`。QLabel 的
   `sizeForWidth()` 金比启发式会把宽度砍成 `w/2`、`w/4`，`sizeHint` 缓存又让气泡
   「慢一句」；高度来自另一个宽度，QLabel 按 contentsRect 裁剪。离线复现：
   `'今天天气'` 第二次调用 `label=26×13 / hfw=28`。

### 7.2 修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `petcore/ui/menu_model.py` | +31 / −10 | hub 不再平铺 children；`_populate_extensions()` 接受 `allowed` 并按首次出现顺序分组；空集合回退全部可见项 |
| `petcore/ui/menu_layout.py` | +88 / −0 | 新增 `migrate_p10_menu()` + `_template_slot()` / `_find_submenu()`，把模板放在 hub 之外的 Core action 搬回模板位置，幂等 |
| `petcore/ui/app.py` | +24 / −1 | `reload_menu()` 调用 p10 迁移并持久化；内置接缝包从 manifest 补 `name_zh` |
| `petcore/ui/settings/base.py` | +43 / −28 | `expand=True` 行改纵向布局；非 expand 行文字块包 `settingTextBlock`（最小宽 180） |
| `petcore/ui/bubble.py` | +93 / −34 | `wordWrap=False` + `QFontMetrics` 显式宽高 + `setFixedSize`；副标题同宽 / `heightForWidth`；图片说明固定宽；`show()` 后再量一次；末页孤行重平衡 |
| `tests/test_petcore_bubble.py` | +56 / −5 | 连续短句单行、每行放得进、`hfw == height`、长副标题不裁 |
| `tests/test_petcore_menu.py` | +24 / −0 | hub `allowed` 只渲染 layout 可见项 |
| `tests/test_petcore_menu_layout.py` | +62 / −0 | p10 迁移：links/quick-launch/network/memory → 工具与帮助，quiet-mode → 顶层，mod 项留在 hub，幂等 |
| `tests/test_petcore_settings.py` | +23 / −2 | expand 行纵向、控件占满行宽、非 expand 文字块最小宽 180 |
| `petcore/AGENTS.md`、`docs/PETCORE-LOG*.md` | +22 / −4 | 红线（hub children 不平铺 / expand 行纵向 / 气泡显式尺寸）+ L048 |

### 7.3 性能分析

命令：`PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/Scripts/python`（同机，`processEvents`
包含在计时内）。

| 路径 | n | 中位 | p95 | 说明 |
|---|---|---|---|---|
| `show_text` 短句（4 字） | 200 | 0.349 ms | 0.768 ms | 含折行、固定尺寸、布局激活、显示 |
| `show_text` 长句（40 段） | 100 | 0.939 ms | 1.642 ms | 8 页分页 + 固定尺寸 |
| `migrate_p10_menu`（已迁移的真实 config） | 2000 | 0.552 ms | 0.973 ms | 只在启动/菜单重载跑一次，幂等返回 False |

- 新增开销：气泡每次冒泡 <1 ms；菜单迁移只在启动时一次；无新增线程/网络/系统调用。
- 内存：固定尺寸的 label 不缓存文本布局；`allowed_order` 是每次建菜单的临时 dict。

### 7.4 实机运行记录

- 气泡复现探针（修复后，同一实例连续调用）：
  `'今天天气' 96×17 hfw=17 bubble=124×37`、`'好的没问题' 96×17 hfw=17`、
  `'一二三四五六七八九十' 134×17 hfw=17`；40 段长文 8 页、每行
  `horizontalAdvance <= label.width()` 0 条超宽、末页 3 行。
- 长副标题：正文 96、副标题 248×76（`hfw=76`），不再横向裁切。
- 真实 `%APPDATA%\dsh-pet-core\config.json` 的 `menu_layout` 迁移（只读副本）：
  `tools_help` 变为 `quick-launch / api_settings / deepseek / github / quark / network /
  memory`，`quiet-mode` 移到顶层，hub 只剩 `core.feature-demo` 与 mod 项；再次执行返回
  False（幂等）。
- 迁移后的 layout + `MenuModel` 离屏构建：hub 子菜单为
  `core.feature-demo / 抽签 / 节日提醒 / 音乐 / 语音报时 / 待办提醒 / 文件解读 / 天气`，
  音乐子菜单 9 项（歌词对齐、上下首、播放/暂停、停止、四个打开播放器）。
- 设置页在 620×1600 离屏渲染：路径行变成「标题+提示整行、输入框+浏览按钮下一行」，
  提示跨两行而非一字一行（`.scratch/p4b1-layout-620.png`）。
- 门禁：`ruff` 全绿；聚焦 348 passed（含 docs）；全量
  `pytest tests/test_petcore_*.py tests/test_architecture.py
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q` →
  **1302 passed**（136.75s）；`python -m petcore --check` exit 0、`diagnostics: []`。
- 构建并签名：`dist/dsh-pet-core-setup.exe` 258,538,152 B，`CN=DSH Pet Core Dev`；
  静默安装到 `E:\dsh-pet-core`，安装版 `--check` 在干净 `APPDATA` 下
  `diagnostics: []`、9 个 mod 全部加载。
- 真实迁移：启动安装版 12 秒让 `reload_menu()` 写回真实 `%APPDATA%` 的
  `config.json`，随后读取：`tools_help = [quick-launch, api_settings, deepseek,
  github, quark, network, memory]`、`quiet-mode` 在顶层、hub 只剩 `core.feature-demo`
  与 mod 项。

### 7.5 本轮未验证

1. 真实桌面右键菜单截图（离屏菜单结构 + 真实 config 迁移已验证；菜单视觉与点击
   仍建议在桌面环境人工确认一次）。
2. 迁移会改写用户 layout 中 Core 项的位置；只搬模板明确放在 hub 之外的项，幂等。
3. 用户在菜单编辑器里隐藏全部 mod 项的极端情况：`allowed` 为空时回退全部可见项，
   会重新显示（换取「旧 layout 不把扩展菜单变空」）。

## 八、第三轮修正：设置窗口最小化/最大化（2026-10-23）

### 8.1 修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `petcore/ui/settings/dialog.py` | +4 / −0 | `SettingsDialog` 在原生旗标上补 `WindowMinMaxButtonsHint`，标题栏出现最小化/最大化 |
| `tests/test_petcore_settings.py` | +25 / −0 | 断言 MinMax/Close 旗标、非模态，并真实切换最小化/最大化/还原状态 |
| `petcore/AGENTS.md`、`docs/PETCORE-LOG*.md` | +10 / −0 | 红线「保留原生标题栏 + MinMax，不改成 frameless 假最大化」+ L049 |

### 8.2 性能分析

- 只改窗口旗标，无新增线程/定时器/网络/磁盘；最小化/最大化由 Windows 与 Qt 处理。
- 不影响首次放置：`place_beside_pet()` 仍在首次 `showEvent` 执行，`_placed` 只放行一次。

### 8.3 实机运行记录

- offscreen：`showMinimized()` → `isMinimized() is True`；`showMaximized()` →
  `isMaximized() is True`；`showNormal()` 回到 neither。
- 旗标同时保留 `WindowCloseButtonHint`，`isModal()` 仍为 False。
- 全量门禁：`ruff` 全绿；1303 passed（103.28s）；`python -m petcore --check` 仍 exit 0。

### 8.4 实机验证与环境限制

- 真实桌面标题栏按钮已用截图确认：`SettingsDialog` 在 Windows 桌面显示
  「— / □ / ×」三个原生按钮（`.scratch/settings-minmax.png`，1350×975 桌面抓取），
  `flags` 含 `WindowMinMaxButtonsHint`、`isModal()` False。
- **安装器在本机被 Smart App Control 拦截**：新构建的 `dsh-pet-core-setup.exe`
  签名有效（`CN=DSH Pet Core Dev`），但启动时被 Device Guard/SAC 拦截
  （CodeIntegrity 事件 3077/3118，Policy `{0283ac0f-…}`）。本轮改用
  `dist/dsh-pet-core` 覆盖安装目录完成部署，安装版 `--check` 9 个 mod、
  `diagnostics: []`。setup 文件本身已构建并签名，换到未启用 SAC 的机器或
  允许该发布者后可正常安装；这是环境策略限制，不是安装包损坏。
