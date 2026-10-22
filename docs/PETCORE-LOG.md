# petcore 变更日志

> **读取方式**：先看 [`PETCORE-LOG-INDEX.md`](PETCORE-LOG-INDEX.md)，只打开命中的
> `LNNN` 条目；不要把整份 log 一次读进上下文。
>
> **写入方式**：每次代码/测试/文档改动追加一条 `## LNNN`，编号单调递增，不覆盖
> 历史。`tests/test_petcore_docs.py` 校验每条 `LNNN` 在索引里有对应行。

---

## L001 · 2026-10-20 · M0–M6 最小 core 与 mod 宿主

**范围**：从 `main`（`147170f`）新建 `feat/petcore-vpet-architecture`，建立可独立
运行的 `petcore` 最小 core。

**改动**

- 新增 `petcore/`：`engine/`（枚举、几何、动画链、行为、位移、状态）、
  `contracts/`（content/host/events/feature/contributions/capabilities/worker）、
  `media/`（Clip 注册、库、fallback、音效、WebM/GIF/帧序列适配）、
  `content/`（旧素材只读、mod 内容、收集、打包）、`mods/`（manifest、发现、启停、
  安装、feature、CLI）、`platform/`（Windows 输入、屏幕、会话、自启）、`ui/`
  （窗口、渲染、气泡、托盘、菜单、设置）。
- 新增 `petcore/menu_templates/petcore-default-v1.json`、内置 demo feature、
  `petcore/cli.py`、`--check`、`pack-legacy`。
- 新增 `tests/test_petcore_*.py` 与结构守卫 `tests/test_petcore_architecture.py`。
- CI ruff 行改为 `ruff check pet/ tests/ petcore/`；`.gitignore` 增加 `.venv/`、
  `/data/`、`/mods/`。

**验证**

- `tests/test_petcore_*.py`：222 passed（M6 基线）。
- `python -m petcore --check`：shenshen 106 段全部 webm，`body_box`/`head_box`
  正确；`pack-legacy` 生成的 content 包可被 `--check --mods-dir` 识别。
- 实机窗口截图 692×389（0.72 缩放 × 1.5 DPR）。
- 首帧中位：WebM 190.3 ms；WebP 帧序列 13.7 ms。idle CPU：WebM 16.01%，
  帧序列 21.85%。

**遗留**：真实双屏未验（本机 1 块物理屏）；拖拽/点击/穿透只有无头测试；
macOS/Linux 菜单外观未验；热卸载/沙箱不支持。

详细证据：[`PR-REPORT-PETCORE-M0-M6-2026-10-20.md`](PR-REPORT-PETCORE-M0-M6-2026-10-20.md)。

---

## L002 · 2026-10-20 · P1-A 菜单/设置风格对齐

**范围**：把右键/托盘菜单与设置页的视觉/骨架对齐主分支。

**改动**

- `petcore/ui/menu_style.py`：浅/深两套 QSS，26px 行高、图标列、勾选/子菜单
  箭头、分隔符、跟随系统深浅。
- `petcore/ui/icons.py`：菜单与设置侧栏图标绘制。
- `petcore/ui/settings/style.py`：设置页侧栏 34px 行高、3px 选中强调条、页面标题
  22px、卡片/行度量、搜索状态行。
- `petcore/ui/menu_model.py` 改为布局驱动；保留 `register/unregister/
  apply_preferences` 兼容层。
- 设置 →「菜单」`MenuEditor`：树形拖拽、显隐、子菜单、分割线、别名、内置/本地
  图片图标、重置默认、预览；保存写 `config.menu_layout` 并重建菜单。
- 旧 `menu_hidden/menu_order` 迁移到新布局；mod 动作自动落入「扩展」子菜单。

**验证**

- `tests/test_petcore_*.py`：222 passed。
- 浅/深菜单与设置截图：`.scratch/petcore-evidence/{menu,settings-menu}-*.png`。
- `resolve()` 中位 0.481 ms（默认，n=5000）、0.506 ms（用户布局）；
  `MenuModel.build()` 0.315 ms（n=200）。

**遗留**：图片图标未做真实图片手工验证；菜单预览/图标选择未走完整 QInputDialog
路径；旧配置重复迁移逻辑幂等但未专测。

---

## L003 · 2026-10-20 · P1-C 窗口可移动、10–300% 大小、设置实时预览、菜单/设置一致性、文档体系

**范围**：设置/关于不再阻塞桌宠；大小滑条与手输百分比；设置实时预览 + 取消回滚；
大小默认移出右键菜单；Core 菜单项与设置入口一一对应；新增 spec/log/log-index/
README/AGENTS 文档。

**改动**

- `petcore/ui/settings/dialog.py`：`NonModal`、`show()` 复用、页面 key 跳转、
  16 ms 实时应用、打开时配置快照、取消回滚、`place_beside_pet()`。
- 新增 `petcore/ui/about.py`：非模态关于窗口；`petcore/ui/placement.py`：窗口放到
  桌宠旁边并夹在可用屏幕内。
- `petcore/ui/app.py`：`CoreHost` 持有设置/关于单例；新增 `apply_live_settings()`
  按差异应用角色/缩放/置顶/穿透。
- `petcore/ui/settings/pages_core.py`：新增「大小」卡片（10–300% 滑条 + 数字框 +
  四档预设 + 恢复默认）、「显示桌宠」、 「回到右下角」、「退出桌宠」；角色/外观
  控件变化写内存配置并发出 `changed`。
- `petcore/ui/settings/base.py`：`SettingsPage.changed`、`make_slider()`、
  `make_spin()`、`add_row(expand=)`。
- `petcore/ui/settings/style.py`：补 `QSpinBox` 与 `QSlider` 的浅/深样式。
- `petcore/engine/geometry.py`、`pet_state.py`、`config.py`：`SCALE_MIN=0.10`、
  `SCALE_MAX=3.00`、`clamp_scale()`、`Config.restore()`。
- `petcore/ui/pet_window.py`：`set_scale/set_character/set_always_on_top/
  set_click_through` 支持 `persist=False`；`set_visible()`；`_remember_geometry`
  可跳过落盘。
- `petcore/menu_templates/petcore-default-v1.json`：`size` 默认 `visible:false`；
  `petcore/ui/menu_actions.py` 增加「自定义大小…」；`petcore/ui/menu_layout.py`
  新增只迁移「未改过的旧默认布局」的 `migrate_default_size_visibility()`。
- 新增 `petcore/ui/settings/coverage.py` 与 `tests/test_petcore_settings_coverage.py`。
- 新增 `tests/test_petcore_live_settings.py`、`tests/test_petcore_about.py`；
  更新 `tests/test_petcore_settings.py`、`tests/test_petcore_menu_layout.py`。
- 新增 `docs/PETCORE-SPEC.md`、`docs/PETCORE-LOG.md`、
  `docs/PETCORE-LOG-INDEX.md`、`petcore/README.md`、`petcore/AGENTS.md`、
  `docs/PR-REPORT-PETCORE-P1C-2026-10-20.md`；更新 `docs/INDEX.md`、
  `docs/PETCORE-ARCHITECTURE.md`、`docs/PETCORE-ROADMAP.md`、根 `AGENTS.md`、
  根 `README.md`。

**验证**

- `tests/test_petcore_*.py`：**243 passed**；连同 `test_architecture.py`、
  `test_pr_report_discipline.py`、`test_ci_workflows.py`：**520 passed, 5 skipped**。
- `ruff check pet/ tests/ petcore/`：All checks passed。
- `.venv/Scripts/python -m petcore --check`：shenshen 106 段全部 webm，无诊断。
- 实机（KimiCU 真实鼠标）：设置打开时桌宠从 `left=480` 拖到 `380`；滑条设
  150% 后窗口变 `1440×810`（150% × 1.5 DPR）；取消回到 `692×389`；数字框
  237% 保存后 `config.json scale=2.37`；默认菜单无「大小」，菜单编辑器里
  `checked=off`；关于窗口打开时桌宠从 `left=0` 拖到 `99`。
- 性能：`set_scale(persist=False)` 中位 0.010 ms / P95 0.014 ms；
  `persist=True` 中位 1.415 ms / P95 2.676 ms；100 次实时缩放后 config mtime
  不变；`apply_live_settings` 空 diff/单差异中位 0.000/0.001 ms；640×360→
  1920×1080 单帧缩放中位 3.437 ms。
- 证据截图：`.scratch/petcore-evidence/p1c-{settings-size,pet-150,menu-no-size,about,desktop}.png`。

**遗留/边界**

- 本机 1 块物理屏，非模态窗口跨屏摆放未实机验证。
- macOS/Linux 焦点/窗口层级未实机验证。
- 旧用户自定义 `menu_layout`（改过顺序/显隐）不会被强行隐藏 size；只迁移
  「去掉 mod 动作后 Core 结构与旧默认完全一致」的布局。
- 237%/300% 会超出 1080p/1200p 屏幕；这是允许 300% 的直接结果。
- 设置/关于不置顶，桌宠拖动时可能盖住它们。
- 热卸载、mod 沙箱仍不支持。

---

## L004 · 2026-10-20 · P1-E 贴边按角色身体框

**范围**：修复「动画画布边框与屏幕边界碰撞」——贴边、落位、恢复、比例、跨屏迁移
全部改用 manifest `body_box × scale` 的稳定身体框，不再用整窗 640×360 画布。

**改动**

- `petcore/engine/geometry.py`：新增 `body_local_rect()`、`body_at()`、
  `clamp_body()`、`clamp_body_to_screens()`、`body_position_ratio()`；多屏用
  「身体逐点落在各屏并集」判定，屏间空洞才推到最近屏；保留旧
  `clamp_position()` / `band_bounds()` / `position_ratio()`。
- `petcore/engine/motion.py`：`clamp_to_screens(..., body_local=)` 透传；新增
  `clamp_to_screen()`。
- `petcore/platform/screens.py`：`restore_position/migrate_layout/adopt_position`
  支持 `body_local`；优先 `body_rx/body_ry`，旧 `rx/ry` 回退；默认右下角改为
  身体右缘留 `CORNER_MARGIN`、身体底贴屏底。
- `petcore/config.py`：新增顶层与 positions 的 `body_rx/body_ry`。
- `petcore/ui/pet_window.py`：缓存 `_body_local`（`_activate`/`set_scale` 更新）；
  `body_local_rect()` / `body_rect()`；`_clamp_position`、`_restore_geometry`、
  `_remember_geometry`、`handle_screens_changed`、`move_to_primary`、
  `return_corner` 全部改用身体框。
- 测试：新增 `tests/test_petcore_geometry.py`；扩展
  `tests/test_petcore_screens.py` 与 `tests/test_petcore_window_smoke.py`。

**验证**

- `tests/test_petcore_*.py`：**257 passed**（加入 body 测试后）。
- 实机（KimiCU 真实鼠标，shenshen，scale 0.72，150% DPI，逻辑屏 1280×752）：
  - 拖到左缘：窗口 x=-153 逻辑、身体左缘=0；截图 `p1d-left-edge.png`。
  - 拖到右缘：窗口 x=971 逻辑（物理 1457）、身体右缘=1280；截图
    `p1d-right-edge.png`。
  - 重启：`body_rx=1.0` 还原到同一位置（物理 left=1457），不跳位。
- 性能：`clamp_body` n=20000 中位 0.0006ms / P95 0.0009ms；
  `clamp_body_to_screens` 中位 0.002ms / P95 0.0035ms；`_body_local` 缓存后无
  每帧文件读取。

**遗留/边界**

- 本机单屏，多屏跨缝/空洞只有伪造几何单测；真实双屏未验。
- 无 `body_box` 的角色仍回退整窗（与改造前一致），需要补 manifest 才能贴边。
- 旧配置首次运行可能仍停在旧窗口位置（不会自动吸到身体边缘）；拖动一次后写入
  `body_rx/body_ry`。
- 边缘探头（P1-F）本次只写设计与路线图，代码未实现；见
  `PETCORE-ROADMAP.md` §8。

---

## L005 · 2026-10-20 · P1-F 边缘探头

**范围**：贴左/右缘后 45° 只露头/脸；点击拉直、5s 回探头；拖拽/关闭开关取消。

**改动**

- 新增 `petcore/engine/edge.py`：贴边判定、旋转投影、目标窗口 x、探头放宽域；
  `engine/` 仍零 Qt。
- 新增 `petcore/ui/edge_probe.py`：`OFF/ENTERING/PEEKING/STRAIGHTENING/
  STRAIGHTENED/RETURNING`，16ms timer + 可注入时钟。
- `petcore/ui/pet_window.py`：`set_probe_pose()`/`move_probe_to()`/`probe_bounds()`/
  `stop_for_probe()`；`paintEvent` 绕帧中心旋转；`is_transparent_at()` 反向旋转；
  拖拽/点击/自动移动/隐藏/换角色/换缩放/屏幕变化接线。
- `petcore/config.py` 新增 `edge_probe_enabled`；设置「外观与交互」复选框；
  右键「桌宠控制」勾选项；`coverage.py` 登记；默认菜单模板加节点。
- 测试：`tests/test_petcore_edge.py`、`tests/test_petcore_edge_probe.py`；
  settings/menu coverage 更新。

**验证**

- `tests/test_petcore_edge*.py`：9 passed。
- 实机（shenshen，0.72，150% DPI，单屏）：贴右缘自动 45° 探头，窗口部分出屏，
  只露头/上半身；点击后拉直，5s 后回到探头。截图
  `.scratch/petcore-evidence/p1f-right-probe.png`、`p1f-return.png`。
- 未验证：macOS/Linux 窗口出屏；非 shenshen 大身体框的旋转裁切；真实左缘
  仅由单测覆盖（本轮实机主要看右缘）。

---

## L006 · 2026-10-20 · P1-B 快捷键/自启/多实例/打包入口/首跑供给

**改动**

- `petcore/platform/hotkey_spec.py`（移植纯文本解析）、`hotkeys.py`
  （Windows `RegisterHotKey` + `WM_HOTKEY`，只绑定 `toggle_pet`）。
- `petcore/config.py` 新增 `hotkey_toggle_pet`；设置「显示/隐藏快捷键」实时重注册。
- `petcore/platform/autostart.py` 新增 `command_text()`（`sys.frozen` 区分）；
  CLI `petcore autostart on/off/status`。
- `petcore/paths.py` 支持 `instance` 数据根；CLI `--instance NAME`；`run()` 应用名带实例。
- 新增 `packaging/petcore_entry.py`、`scripts/build_petcore.ps1`（未实际构建）。
- 新增 `petcore/media/provision.py`：包装 `pet.frameseq_provision.provision_once`
  （首跑供给 + 世代退役/GC）；`run()` 启动后 daemon 线程跑一轮；CLI
  `petcore provision <character>`。
- 测试：`tests/test_petcore_platform.py`；CLI/设置测试补充。

**验证**

- `petcore autostart status` → `off`。
- `--instance test --check` → 数据根 `...\dsh-pet-core-test`，与默认隔离。
- 实机启动 petcore 后后台供给把 shenshen 的 idle/move 两段转成 frameseq；
  `--check` 显示 `{'webm': 104, 'frameseq': 2}`，无诊断。
- 未验证：真实全局按键（只测了 fake user32 的注册/失败路径）；PyInstaller
  实际构建；macOS/Linux 自启。

---

## L007 · 2026-10-20 · P1-D 角色资源包导入

**改动**

- 新增 `petcore/content/character_pack.py`：`validate_character_source()` +
  `build_character_pack()`；生成 `character.<id>` content mod，写
  `body_box/head_box/canvas/feet_y` 与可选 `move_strides/text_clips/phrases`。
- `petcore/content/pack.py` 的 `pack_legacy()` 改为复用同一构建器。
- CLI `petcore pack-character <source> --out <dir> [--id] [--name] [--version] [--copy]`。
- 测试：`tests/test_petcore_character_pack.py`、`tests/test_petcore_cli.py`。

**验证**

- 合成 source（空 `idle.webm` + manifest）→ `pack-character` 生成
  `character.clipet`，`body_box` 正确；`mods` 收集能识别该角色。
- 缺媒体、非法 body_box、非法 id、非空输出目录均返回失败。
- 未验证：真实大素材（shenshen 全量）导入；只用了合成包。

---

## L008 · 2026-10-20 · P2-A 交互、多宠、关于与打包

**改动**

- 关于：删除 `petcore/ui/about.py` / `AboutDialog` / 右键 `about`；`AboutPage` 增加桌宠数、复制诊断、项目主页；设置页仍是唯一关于入口。
- 交互：新增 `engine/physics.py`、`engine/squash.py`、`engine/spin.py`、`engine/collision.py`、`engine/feeding.py`；新增 `ui/effects.py`、`ui/motion.py`、`ui/slingshot.py`、`ui/feeding.py`；`PetWindow` 接入 Q 弹、拖动物理、弹弓、黄金回旋、探头击飞、拖文件投喂、碰撞与统一旋转/命中逆变换。
- 多宠：新增 `ui/pet_manager.py`；slot 0 主宠 + slot 1–15 子宠；`config-pet-N.json` 独立配置；生成/收回/恢复/碰撞；新增「多宠」设置页与「生小肥鱼/退出子肥鱼」菜单。
- 菜单/设置：默认模板按主分支顺序重排；新增「互动与物理」页；`coverage.py` 登记新 Core 动作；`animations_hub`、`playback_speed`、`animation_gap_seconds` 生效。
- 打包：`scripts/setup_packaging.ps1` 安装 PyInstaller 6.22.3 与 Inno Setup 6.7.3（`tools/InnoSetup`）；`scripts/build_petcore.ps1` 支持 `-Clean/-Installer/-Console` 与 `--check --out`；`packaging/petcore.iss` 使用本地中文语言文件。
- 测试：新增/更新 `tests/test_petcore_interaction.py`、`test_petcore_multipet.py`、`test_petcore_about_page.py`；更新菜单/设置/coverage/CLI 测试。

**验证**

- `pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q` → **579 passed, 5 skipped**。
- `ruff check pet/ tests/ petcore/` → All checks passed。
- `python -m petcore --check --out .scratch/petcore-evidence/p2-check.json` → 无诊断，active_pets=[0]。
- PyInstaller onedir 构建成功；`dist/dsh-pet-core/dsh-pet-core.exe --check --out dist/check.json` 通过；Inno Setup 编译成功，产物 `dist/dsh-pet-core-setup.exe`（约 153 MB）。
- offscreen 实机脚本生成主宠+2 子宠截图 `.scratch/petcore-evidence/p2-pet-{0,1,2}.png`；多宠槽位为 `[0,1,2]`。

**未验证**

- Q 弹：`tests/test_petcore_interaction.py` 覆盖几何/状态；实机截图 `.scratch/petcore-evidence/p2-click-squash-80ms.png`（点击后 80ms，progress≈0.64）。
- 安装包只验证构建，未做静默安装/卸载端到端。
- macOS/Linux 的窗口出屏、旋转命中与多宠碰撞未实机验证。
- 真实全局快捷键按键仍未自动按下验证。

---

## L009 · 2026-10-20 · P2-B1 内置离线 mod 与端口

**改动**

- `FeatureManager.load_builtin_features()` 扫描 `petcore/builtin/features`；内置 feature 受信任，不受 `allow_feature_mods` 限制；第三方 feature 仍受控。
- `contracts/host.py` 新增 `PetHandle/PetRegistryPort/InteractionPort/QuietPort` 与 `HostPorts.pets/interaction/quiet`；`contracts/feature.py` 的 `FeatureContext` 增加 `host`。
- 新增 `ui/ports.py`：QtScheduler、AudioAdapter、StorageAdapter、PetRegistry、InteractionAdapter、QuietMode；`CoreHost` 用 `build_ports` 注入。
- 新增内置 mod：`fun.self-talk`、`fun.click-talk`、`fun.divination`、`fun.festival`、`reminder.todo`、`voice.chime`、`media.music`、`tool.quick-launch`、`tool.quiet-mode`、`tool.links`、`tool.memory-trim`、`tool.network-info`；每个有菜单的 mod 都有设置页。
- 默认菜单模板加入 `tool.quick-launch:open_menu`、`tools_help`（links/network/memory）、`tool.quiet-mode:quiet_30`、`fun.divination:draw`。
- 测试：`tests/test_petcore_builtin_mods.py` 校验加载、菜单唯一、菜单 owner 有设置页。

**验证**

- 内置加载诊断为空；`CoreHost` 共 13 个 feature（含 demo）、16 个官方菜单贡献 + 1 个 demo 贡献；12 个内置 mod 设置页。
- 全量门禁同上：579 passed, 5 skipped；ruff 绿。

**未验证**

- `media.music` 只提供 Windows 系统媒体键，歌词/歌名/SMTC 未接入；`fun.festival` 只含公历固定日期，农历节日待数据包。
- `tool.memory-trim` 只在 Windows 代码路径可用；未实机回收验证。
- `tool.quick-launch` 未实机启动外部程序；`tool.links` 未在浏览器打开验证。

---

## L010 · 2026-10-20 · P3 设置聚合与可导入 mod 样板

**改动**

- 新增 `petcore/ui/settings/tabs.py`（`SettingsTabContainer`）与 `page_extensions.py`（`ExtensionsPage`）：侧边栏固定 7 页，「扩展管理」页内用标签承载原 `ModsPage` + 所有 mod `settings_page`。
- `SettingsPage` 增加 `prepare_embedded()`；`ModsPage` 增加「允许功能扩展」复选框与「重新加载扩展」按钮。
- `SettingsDialog` 不再把 contributed page 追加成侧边栏项；`ExtensionsPage` 统一委托 `dirty/draft/confirm_save/discard_changes/dispose`。
- 把 `fun.divination`、`fun.festival`、`reminder.todo`、`voice.chime`、`media.music` 从 `petcore/builtin/features/` 移到 `examples/petcore-mods/`；新增 README 与 `scripts/install_example_mods.ps1`。内置只留 7 个。
- 默认菜单删除这 5 个示例 mod 的显式节点；`tool.quick-launch:open_menu` 移入「工具与帮助」。
- 新增 `tests/test_petcore_example_mods.py`；更新内置 mod/设置页测试。

**验证**

- `pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q` → **586 passed, 5 skipped**。
- `ruff check pet/ tests/ petcore/` → All checks passed。
- `petcore mods validate examples/petcore-mods/<id>` 5/5 通过。
- 实机/无头检查：设置侧边栏 7 项；「扩展管理」标签 = 扩展管理 + 7 个内置设置页。
- 直接调用 `install()` 安装 `fun.divination` 到临时数据根成功，`load_mods(allow_feature_mods=True)` 识别为启用的 feature。

**未验证**

- 安装 5 个示例后的完整 UI 点击/卸载恢复未逐项实机操作。
- `petcore --root X mods ...` 的全局选项顺序不支持（需 `petcore mods --root X ...`），未在本轮修。

---

## L011 · 2026-10-20 · 移动朝向与位移曲线同步

**改动**

- `CharacterSpec` 新增 `move_curves`；`content/legacy.py` 的 `_move_data` 同时解析 `stride`/`curve`，`content/modcontent.py` 合并 manifest 声明路径的 curve。
- `engine/motion.py` 新增 `body_reach`、`choose_move_direction`、`quantize_move`、`move_position_at_frame`、`wander_target_y`。
- `PetWindow._begin_move`：按屏幕可达空间选方向，先设置 `state.facing` 再重建首帧；用 `quantize_move` 算整圈位移，plan 保存 curve/frames_per_loop。
- `PetWindow._on_frame`：按 clip 帧号调用 `move_position_at_frame` 写窗口位置；`_on_finished` 处理多圈重播与末拍提交；`_tick_move` 退化为守卫。
- 点击/拖拽/探头/缩放/换角色打断时统一 `_cancel_move_plan()`。

**验证**

- `tests/test_petcore_motion.py` 新增朝向/量化/curve 单测；`tests/test_petcore_move_sync.py` 用 shenshen 断言 facing 与 target 方向一致、curve 长度=帧数。
- 实机（offscreen，shenshen，0.72）：左移 plan `start_x=467 → target_x=294`，curve 241 帧；前 ~2s 静态段窗口不动，约 11s 到 target，facing 始终 left。
- 全量门禁同上：586 passed, 5 skipped；ruff 绿。

**未验证**

- 真实桌面逐帧录屏未做；曲线手感以 offscreen 位置采样与单测为准。
- 多屏/混合 DPI 下的移动空间未实机验证。

---

## L012 · 2026-10-20 · P3 收口补齐（CLI 序、扩展页兜底、重打包）

**改动**

- `petcore/cli.py`：新增 `_value_options` / `_subcommand_index` / `_resolve_root`。`main()` 先定位
  `mods` 子命令（跳过选项值，`--character mods` 不会被误判），再把前置 `--root` / `--portable` /
  `--instance` / `--mods-dir` 解析出的根目录下发给 `mods.cli`。根 `_parser()` 增加全局 `--root`，
  GUI 与 `--check` 路径同样走 `_resolve_root`。
- `petcore/ui/settings/page_extensions.py`：非 `SettingsPage` 的第三方控件不再被静默跳过，改为包进
  `_HostedWidgetPage` 并显示“不参与保存”的提示；`_pages` 类型保持 `SettingsPage`，保存/释放语义不变。
- `tests/test_petcore_cli.py::test_mods_subcommand_accepts_global_root`；
  `tests/test_petcore_settings.py::test_plain_widget_contribution_is_hosted_with_hint`；
  `tests/test_petcore_example_mods.py::test_all_example_mods_install_into_fresh_root`（5 个示例包全部
  装机到临时数据根后 `load_mods` 全部启用、无诊断）。
- 文档：`docs/PETCORE-MOD-FORMAT.md` 记录 `--root` 前置写法；`docs/PR-REPORT-PETCORE-P3-2026-10-20.md`
  同步门禁数字与新测试。

**行为变化**

- `petcore --root D:/pets mods list|doctor|install ...` 现在等价于 `petcore mods --root D:/pets ...`，
  不再落到 GUI 启动。`petcore --portable mods doctor` / `--instance foo mods doctor` 同样可用。
- 扩展作者如果只贡献了裸 `QWidget`，用户能在「扩展管理」看到它，也能看到“改动不会随设置保存”的原因。

**验证**

- `pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **591 passed, 5 skipped**。
- `ruff check pet/ tests/ petcore/` → All checks passed；`git diff --check` 干净。
- `python -m petcore --check` 退出码 0，`data_root` 跟随 `--root`。
- 手工：`python -m petcore --root .scratch/cli-order mods doctor` 打印 `root: .scratch\cli-order`；
  `--portable mods doctor` 退出码 0；`--instance testinst mods doctor` 落在对应数据根。
- 打包：`scripts/build_petcore.ps1 -Clean -Console` 成功（内置 `--check` 通过），
  `tools/InnoSetup/ISCC.exe` 重新出包，`dist/dsh-pet-core-setup.exe` 180,473,181 字节 / 19:49:48。
  打包后的 `dist/dsh-pet-core/dsh-pet-core.exe --root .scratch/pkg-root mods doctor` 输出正确根目录，
  说明 CLI 修复已进二进制。

**未验证**

- 嵌套滚动（`SettingsPage` 自带滚动区放进设置对话框的滚动区）没有和主分支逐项并排比对；截图看着可用。
- `media.music` 仍只有 Windows 系统媒体键，无歌词/SMTC；`voice.chime` 只验证了加载，未验证真实发声。
- 多屏/混合 DPI 的移动空间、真实桌面逐帧录屏仍未实机验证。

---

## L013 · 2026-10-20 · P4 交互缺陷修复与安装器收口

**改动**

- 朝向：`engine/pet_state.py` 默认 `facing="left"`；`ui/pet_window.py::_mirrored()`
  改成 `facing == "right"` 才镜像（素材原生朝左，同主分支）。修复「位移方向和面
  朝向相反」。
- 回旋：`ui/effects.py::_begin_spin()` 补 `_ensure_timer()` + `update()`。此前点击
  动画结束后角度冻结在 0°，看起来像没触发。
- 碰边：`ui/motion.py` 用四向接触沿触发 `_on_motion_bounce()`，新增
  `BOUNCE_TRIGGER_SPEED`；删掉整个抛掷只响一次的 `_throw_bounced`。
- 探头：`engine/edge.py` 加 `EDGE_ENGAGE_TOLERANCE_PX=28` 与 `edge_snap_x()`；
  `ui/edge_probe.py` 进入前先 `stop_for_probe()` 再吸附压边。
- 多宠：`ui/pet_manager.py` 分离结果走 `_clamp_position()`；碰撞取消双方移动计划；
  拖拽中不参与碰撞结算。新增 `engine/spawn.py` 做落座候选，`_place_spawned` 改用它。
- 设置：`settings/base.py` 行控件返回 + `sub` 缩进 + `page_label_texts/reveal_text`；
  `dialog.py` 搜索纳入行文案并跳转滚动；`tabs.py` 标签条进滚动区 + 翻页箭头；
  `page_interaction.py` 子选项联动显隐；`page_mods.py` 显示「随安装包」与授权详情。
- 授信：新增 `mods/trust.py`（`.trusted` 标记）；`mods/loader.py` 支持逐包授信；
  `ui/app.py` 只认 `mod.enabled`。
- 打包：`packaging/petcore.iss` 5 个扩展改成 `[Tasks]` 可勾选、装到
  `%APPDATA%\dsh-pet-core\mods\<id>` 并投放 `.trusted`，排除 `__pycache__`；默认
  窗口化构建；`cli.py::_ensure_streams()` 兜底 `sys.stdout is None`。
- 预热：`media/sound.py` 缓存 `QSoundEffect`；`pet_window._warm_interaction_assets()`
  预热全部点击 clip 与点击音效。

**验证**

- 全量门禁：`607 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 绿；
  `petcore --check` 退出码 0；`git diff --check` 干净。
- 探针（offscreen）：`left→不镜像 / right→镜像`；点击后 10.0s 起转；
  一次抛掷触发 2 次落地反馈；开拖动物理贴边松手后吸附并 PEEKING；
  两只重叠 100ms 分开且都在屏内，拖拽时另一只不动；贴右缘生成子宠落到空位。
- 打包：`-Clean` windowed 构建 + ISCC 成功；exe `Subsystem=2`（无终端窗口）；
  `dist/dsh-pet-core-setup.exe` 180,500,361 字节，含 5 个可勾选扩展。

**未验证**

- 安装向导勾选流程未真机跑安装（避免污染本机 `%APPDATA%`）。
- 真实桌面录屏、多屏/混合 DPI、首次点击的帧时间测量都没做。
- 点击动画本身是 241 帧 / 10.04s（VPet 素材原长），所以「点击→回旋」等待偏长。

---

## L014 · 2026-10-20 · P5 气泡/设置易用性与扩展反馈、碰撞圆链

**改动**

- 气泡锚点：`PetWindow.bubble_anchor_rect()` 优先 `head_box`（回退 `body_box`/整窗）；
  `SpeechBubble._place()` 改为「上居中 → 上偏左右 → 两侧 → 下方」候选，`gap=6`，
  且不与角色相交。此前用整窗 `frameGeometry()`，气泡飘在画布顶端上方 100+px。
- 台词候选：新增 `ui/settings/text_lines.py`（`parse_lines` 兼容旧 `a | b` 单行）；
  `fun.self-talk` / `fun.click-talk` 的 `QLineEdit` 换成 `QPlainTextEdit`（一行一条），
  250ms 防抖写入；`discard_changes` 同时恢复数字与文本控件。
- Enter：`SettingsDialog.keyPressEvent` —— `Return/Enter` 直接 `accept()`（保存退出），
  焦点在多行文本框时放行换行；`Esc` 仍是取消。
- 免打扰：`QuietPage` 重写为「默认时长下拉（`quiet_minutes_default`）+ 当前状态 +
  恢复提醒 + 立即静默四档按钮」并补说明文案；`QuietMode.remaining_seconds()`；
  菜单项加 `checked`（静默中打勾）。
- **依赖缺口**：`psutil` 在 `requirements.txt` 有声明但 `.venv` 没装，打包产物里也没有
  （内置 mod 以数据分发，PyInstaller 看不到它们函数内的 `import psutil`）——所以
  「网络信息」只会回一句「缺少 psutil」，「回收内存」直接 0/0 无反馈。已装 `psutil 7.2.2`
  并在 `scripts/build_petcore.ps1` 加 `--hidden-import psutil`、`--hidden-import
  PySide6.QtTextToSpeech`（示例 mod voice.chime 同理）。
- 扩展反馈：`PresentationPort.say/notify` 增加 `force`；`_PresentationAdapter` 只在
  `force=False` 时受免打扰抑制。免打扰/回收内存/网络信息的命令反馈全部 `force=True`；
  网络信息文案重排为「流量 / 网卡 / 本机信息不联网」，设置页加「现在查看一次」。
- 菜单对勾：QSS 菜单项由样式表引擎绘制，`PE_IndicatorMenuCheckMark` 不会回调样式，
  所以改为 `menu_style.check_image_path()` 运行时生成 14px 对勾 PNG，并注入
  `QMenu::indicator:checked { image: url(...) }`；勾选项不再设置 icon（QSS 菜单里
  图标与勾选共用左边槽位，有图标就看不见勾）。`_register_feature_menus` 支持
  contribution 的 `checked` 可调用对象。
- 碰撞：`engine/collision.py` 重写为**内切三圆链** + 主分支分离规则（0.5px slop、
  每次最多 60% 重叠、1..12px、连续 3 tick 强制完整分离且上限 4×12px、稳定哈希方向）；
  `PetManager` 维护 `_overlap_streak`，每 tick 最多两轮分离；反馈阈值提到 300px/s。

**验证**

- 全量门禁：`636 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 绿；
  `petcore --check` 退出码 0。
- 探针（offscreen）：气泡底边距头部锚点 6px；贴屏幕上沿时改到侧/下方且不压角色；
  免打扰页三段式布局与「静默中，剩余约 15 分钟」状态；菜单勾选行可见 ✓；
  两只 shenshen 重叠后 30 tick 内三圆链不再相交。

**未验证**

- 真实桌面观感（菜单勾选在 Windows 11 主题下的清晰度、气泡与毛发边缘的相对位置）
  需要实机确认。
- 圆链碰撞的「贴合距离」与旧椭圆不同（中间更早碰、四角更晚碰），手感待实机确认。

---

## L015 · 2026-10-20 · 多宠碰撞瞬移与被撞斜修复

**症状**：多宠碰撞时被撞的桌宠偶尔「闪现到屏幕另一端」，有时还会保持 45° 探头姿态。

**根因**

1. **瞬移**：`MotionController.set_velocity()` 把模式切到 `thrown` 时没有把内部坐标
   `_x/_y` 锚到窗口当前位置。`_x/_y` 只在拖拽/抛掷里维护，`normal` 期间是构造时的
   (0,0) 或上一次抛掷的旧值；下一个 tick `_tick_throw()` 从旧坐标出发并 `window.move()`，
   整只宠物就瞬移到那个旧位置（通常是出生点/屏幕另一角）。
2. **被撞斜**：`PetManager._collide_pair()` 对探头姿态（`probe_active`，身体按设计探出
   屏幕且整帧旋转 45°）的宠物照常做位置分离。分离把窗口推回屏内，而 `_probe_angle`
   仍停在 45°、`_probe_exposure` 仍是 0.55 —— 看起来就是「被撞斜成探头的样子」。

**改动**

- `petcore/ui/motion.py::set_velocity()`：切 `thrown` 前 `_x/_y = window.x()/y()`，
  并重置 `_last_tick`；注释写明不允许省这一步。
- `petcore/ui/pet_manager.py::_collide_pair()`：先按圆链判是否真的重叠；确认撞上后，
  对探头中的一方 `_edge_probe.cancel("collision", restore=True)`（回到探头前的屏内 x、
  姿态复位直立），然后用新姿态重算一次分离。只是「靠近」不触发退出。
- 测试：`tests/test_petcore_p5.py` 新增 3 条——`set_velocity` 重锚、真实窗口 6 个事件循环
  不跳变、探头被撞后 `probe_active=False`/角度归零/身体贴回屏内；另一条 30 tick 逐帧
  位移 <120px 的跳变护栏。

**验证**

- 探针（offscreen，shenshen 0.5）：窗口在 (400,400) 收到 `set_velocity(-300,0)` 后内部
  坐标即 400,400（修复前是 0,0，下一 tick 直接跳到左上）；探头中的桌宠在
  `(-146,300)/45°` 被撞后变成 `(-106,235)/0°`、exposure 1.0、body.x=0。
- 全量门禁：`640 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 绿。

**未验证**

- 真实桌面下的手感（碰撞把宠物推开的速度、探头退出时机）需要实机确认。

---

## L016 · 2026-10-20 · petcore/net 传输层单测

**改动**

- 新增 `tests/test_petcore_net.py`（243 行，新增文件）：覆盖 `urlopen` 的「代理失败→直连」兜底与进程级固化、直连固化后只试一次、`reset_transport()` 复位、`HTTPError` 不重试、双路失败抛最后一次异常、自定义 `opener=` 不固化结论；`classify_http_status` / `http_error`（含 `Retry-After`）/ `classify_exception` / `describe` 的分类矩阵。33 条测试，纯标准库、不联网；autouse fixture 前后 `reset_transport()`。
- 未改 `petcore/net/*.py` 语义。

**行为说明**

- 需求里的「假 opener 工厂 + 断言 `force_direct()` 变 True」与产品口径冲突：只有 `opener is None`（走默认 `_opener`）才固化。因此兜底相关用例改为 `monkeypatch.setattr(petcore.net.http, "_opener", factory)` 走默认路径；自定义 `opener=` 不固化单独成一条。

**验证**

- `.venv/Scripts/python -m pytest tests/test_petcore_net.py -q` → `33 passed`。
- `.venv/Scripts/ruff check tests/test_petcore_net.py` → 绿。

**未验证 / 风险**

- `tests/test_petcore_architecture.py::test_no_network_stack_in_core` 仍红：守卫禁止全包 import `urllib`/`http`，而新增的 `petcore/net/` 正是唯一允许的联网出口，守卫未给 `net/` 豁免。与本次测试无关，属既有分支问题。

---

## L017 · 2026-10-20 · 待机掷骰、可调概率与手动播放菜单

**症状**：桌宠几乎一直待机，随机动作（random/ 89 个）从不触发，偶尔才见到转向或漫游。

**根因（真实素材探针）**：`PetWindow._on_finished()` 每次都先 `player.advance()`；
IDEL 素材是 `B_LOOP + loop=True`，`AnimationPlayer.advance()` 原样返回同一个 idle spec，
`_play_spec()` 又播一遍待机 ⇒ 永远到不了 `director.choose()`。主分支是「待机播完一圈
→ `_roll_next()` 掷骰」，掷骰链只在点击/拖拽/手动播动画结束后才会被走到。

**改动**

- `ui/pet_window.py`：`_on_finished()` 对 IDEL B_LOOP 不再走 `advance()`，圈末
  `_roll_next()`；新增 `_is_idle_dwell/_finish_action/_roll_next/_behavior_weights/_gap_active`。
  `animation_gap_seconds` 从「QTimer 停住等 gap」改为「gap 期间继续播待机、到点掷骰」，
  删掉 `_gap_timer/_gap_action/_gap_token`。同一 clip 重播只 `clip.start()` re-arm，不
  `stop()`。`play_animation()` 按 GraphType 映射动作类型（idle/turn/move/click/act），
  并先取消 gap。
- `engine/behavior.py`：新增 `DEFAULT_WEIGHTS=(0.30,0.10,0.40,0.20)`、`normalize_weights()`；
  `BehaviorDirector` 支持 `weights`/`weights_provider`，每次 `choose()` 读权重。
- `config.py`：新增 `anim_weight_idle/turn/act/move`（30/10/40/20，0–100）。
- `ui/settings/page_interaction.py`：「动画」卡片新增「自主行为概率」四个百分比；
  改控件即写 config，下一次掷骰生效。
- `ui/menu_actions.py`：「播放动画」按待机/转向/移动/点击回应/随机动作/事件分组，
  叶子播一次，播完回掷骰链。
- 测试：新增 `tests/test_petcore_playback.py`（10 条）；`tests/test_petcore_behavior.py`
  追加权重/归一化 5 条；`tests/test_petcore_settings.py` 的页数与搜索索引跟随 8 页。

**验证**

- `tests/test_petcore_*.py`：`442 passed`；全量门禁 `733 passed, 5 skipped`；ruff 绿。
- 真实素材 60s offscreen 探针（`playback_speed=2.0`）：9 次状态切换
  `idle 3 / act 3 / move 1 / turn 2`，随机动作「原地小跳」等实际播放（修复前只会 idle）。
- 掷骰分布（shenshen，2000 次）：idle 622 / turn 211 / act 774 / move 393 ≈ 30/10/40/20。

**未验证**

- 真实桌面下 WebMClip 的圈末软停/re-arm 是否完全不换代（探针为 offscreen）；
  gap 时长的手感需实机确认。

---

## L018 · 2026-10-20 · 事件动画与 play_event

**改动**

- `engine/enums.py`：新增 `GraphType.EVENT = "Event"`。
- `contracts/content.py`：`AnimationSpec.event_group: str = ""`。
- `content/legacy.py`：`events/` 映射为 EVENT/SINGLE，`events/balance/x.webm` 取
  `event_group="balance"`（此前整棵 events 树落进 DEFAULT，被当随机动作播）。
- `engine/catalog.py`：`specs_for_event()/event_groups()/event_names()`。
- `ui/pet_window.py`：`play_event(group, variant)`：名字（可带目录前缀）或排序索引，
  留空随机；按 act 播放，播完回掷骰链。
- 端口：`PresentationPort.play_event`、`PetHandle.play_event`；`_PresentationAdapter`
  与 `PetHandleImpl` 转发。

**验证**

- 真实角色包：`Default 89 / Event 6 / Touch_Body 5 / Move 4 / Idel 1 / Raised_Static 1`
  （修复前 Event 不存在，6 个余额动画混在 Default）。
- `event_groups() == ("balance",)`，`play_event("balance", 名字/0)` 均命中；
  `act()` 不再返回余额动画。测试随 `test_petcore_playback.py` 与 catalog/contracts 用例。

**未验证**

- 余额档位到动画名的映射仍由后续 account/余额 mod 决定；本批只提供语义入口。

---

## L019 · 2026-10-20 · core 联网 allowlist、API 能力与设置页、keyring 打包

**改动**

- 结构守卫（`tests/test_petcore_architecture.py`）：`test_no_network_stack_in_core`
  改为 allowlist（`net/`、`api/`、`account/` 之外仍禁网络库）；新增
  `test_mods_do_not_import_core_network_or_api`（builtin + examples 不得 import
  `petcore.net/api/account`）。L016 里记录的既有红灯由此收口。
- `petcore/net/`：`http.py`（移植主分支 `pet/http_util.py`：代理先试、传输失败改直连并
  固化、`HTTPError` 不重试）、`errors.py`（auth/rate_limit/network/timeout/protocol 五类）。
- `petcore/contracts/api.py`：`ApiMetadata/ApiRequest(repr 不含 key)/ApiPort`；
  `contracts/host.py` 的 `HostPorts` 新增 `api`。
- `petcore/api/`：`spec.py`（endpoint/服务校验）、`store.py`（`api.json` 原子写、
  坏文件备份、订阅、版本号）、`credentials.py`（keyring 惰性导入 + 内存兜底 +
  `persisted()` 回读）、`probe.py`（文本探测，不读响应体）。
- 设置页 `ui/settings/page_api.py`（「API 与账户」）：服务列表/表单/密钥/测试连接
  （QThreadPool + 信号回主线程）；`settings/dialog.py` 侧边栏 7→8 页；菜单
  「工具与帮助 → API 与账户」+ `coverage.py` 登记。
- `ui/ports.py`：`CoreApiPort`（metadata/resolve/subscribe/open_settings），
  `build_ports()` 注入 `api` 与 `credentials`；`CoreHost` 持有共享的 `ApiStore`/
  `KeyringCredentials`。
- `ui/settings/dialog.py`：`_save_pages()` 改为返回布尔——任一页面 `confirm_save()`
  显式返回 `False`（API 表单校验失败）时弹提示并**不关闭**设置窗口，不再静默丢弃输入。
- 依赖与打包：`.venv` 安装 `keyring 25.7.0`（`requirements.txt` 已声明）；构建脚本补
  `--hidden-import keyring.backends.Windows`、`--collect-submodules keyring/win32ctypes`。
- 文档：SPEC §3/§4（规则 18–21）/§10、AGENTS 红线、ROADMAP §16、ANIMATION-BACKLOG、
  ARCHITECTURE 分层、README；`petcore/AGENTS.md` 侧边栏页数同步。

**验证**

- `tests/test_petcore_net.py` 34 条、`tests/test_petcore_api.py` 41 条全绿；全量
  `733 passed, 5 skipped`；ruff 绿；`petcore --check` 退出码 0。
- 真实 Windows 钥匙串回读：`available=True`、`set→get→persisted=True→delete→None`。
- `api.json` 探针：只含 base_url/model/timeout 等服务字段；`ApiRequest.resolve` 能取到
  9 位密钥但 `repr` 不含密钥。
- offscreen 播放探针见 L017（不是本条的 API 证据，单独列出）。

**未验证 / 风险**

- 打包已重出：`dist/dsh-pet-core-setup.exe` 185,100,188 字节，主 exe Subsystem=2；
  `--check` 退出码 0；冻结包 PYZ 内已核对 `keyring.backends.Windows` 与
  `win32ctypes.pywin32.win32cred`。
- 仍未验证：打包版在真实桌面里实际读写钥匙串；真实 HTTPS 端点与自签握手。
- 真实 HTTPS 端点（如 DeepSeek）与 `verify_ssl=False` 的自签握手未端到端验证；
  设置页嵌入设置对话框后的搜索/Enter/取消回滚只有页面级与对话框级测试。

---

## L020 · 2026-10-21 · 探头击飞旋转与飞行接管态

**症状**：探头状态下被撞飞没有整帧旋转；击飞到稳定前会切到别的动画；稳定前点击桌宠会出现两个位置的桌宠在闪。

**根因（对照主分支）**

1. `arm_throw_egg()` 只在 `MotionController.begin_throw()` 且 `probe_active` 时调用；探头一被拖拽
   `edge_probe.on_drag_started()` 先 `cancel("drag_away")`，松手时 `probe_active` 已 False。
   主分支的授权口是碰撞 `edge_probe.cancel("collision_throw")`（`pet/edge_probe.py:283-287`），
   petcore 的 `_collide_pair()` 只 cancel、没有 arm。
2. 主分支把拖拽/飞行当接管态：不掷骰、点击返回 False、`_effects_filter_switch` 只允许
   idle/turn。petcore 的 `_on_finished()` 不看 `motion.thrown`、`_on_click()` 不看飞行态、
   `_play_spec()` 没有素材闸门。

**改动**

- `ui/pet_manager.py`：碰撞确认圆链重叠后，先对探头窗口 `effects.arm_throw_egg()`，再
  `edge_probe.cancel("collision", restore=True)`；低速碰撞没进入抛掷时立即 `end_throw_egg()`。
- `ui/motion.py`：删掉 `_throw_egg_armed` 单一来源；`_tick_throw()` 只在
  `effects.throw_egg_active` 时更新角度；`stop()` 无条件回正；进入 `thrown` 时回调
  `window._on_thrown()`（碰撞抛掷也绑飞行/拖拽素材）。
- `ui/edge_probe.py` / `ui/pet_window.py`：`on_drag_started()` 返回「拖拽前确实在探头」，
  松手抛掷时据此授权击飞旋转（拖出去甩飞也能触发；不只碰撞）。
- `ui/pet_window.py`：
  - `_play_spec()` 加 `_effects_lock_active()` 闸门：探头/彩蛋激活时非 idle/turn 一律降级待机，
    且不翻朝向；
  - `_on_finished()` 在 `motion.thrown` 时只 re-arm 当前素材、不掷骰；
  - `_on_click()` 在 `motion.thrown` / 彩蛋激活时直接返回；
  - `_play_throw_animation()` 回退顺序 RAISED_DYNAMIC → RAISED_STATIC → idle；
  - 新增 `_on_thrown()`（停 gap/移动计划、绑飞行素材）。

**验证**

- 新增 5 条用例（`tests/test_petcore_playback.py`）：探头只播 idle/turn 且不翻朝向、
  彩蛋激活时 act 降级、thrown 圈末不掷骰且 re-arm、飞行中点击不改素材、碰撞后
  `throw_egg_active=True` 且角度 90°、`stop()` 后归零。
- 全量：`775 passed, 5 skipped`；ruff 绿；`petcore --check` 退出码 0。

**打包/图标**

- `-Clean -Installer` 重出：`dist/dsh-pet-core-setup.exe` 185,740,254 字节；
  `ExtractAssociatedIcon` 取 setup 与主 exe 图标均为鲸鱼娘；主 exe `--check` 退出码 0，
  `mod_dirs` 含 `<安装目录>/mods`。

**未验证**

- 真实桌面手感：碰撞撞飞的速度阈值、旋转跟随的观感；offscreen 只到状态与角度。

---

## L021 · 2026-10-21 · 安装器图标/扩展安装位置与扩展管理重排

**改动**

- `packaging/petcore.iss`：新增 `SetupIconFile=..\assets\icon.ico`、
  `UninstallDisplayIcon={app}\dsh-pet-core.exe`；5 个随附扩展的 `DestDir` 由
  `{userappdata}\dsh-pet-core\mods\<id>` 改为 `{app}\mods\<id>`（`.trusted` 同目录）。
- `scripts/build_petcore.ps1`：PyInstaller 加 `--icon assets/icon.ico`。
- `petcore/paths.py`：新增 `is_frozen/install_root/install_mods_dir/user_mods_dirs`；
  `mods_dirs()` 在冻结包中纳入 `{app}/mods`。
- `petcore/mods/loader.py`：feature 的「用户 mod 根」= 数据目录 + 安装目录；
  `.trusted` 逐包授权不变。
- `petcore/ui/app.py`：加载 feature 的 allowed roots 同步为 `paths.user_mods_dirs()`。
- `petcore/ui/settings/page_mods.py`：加「全部/基础/加装」过滤；列表与详情优先中文名；
  `.trusted` 包禁用卸载并提示「随安装程序卸载」。
- `petcore/ui/settings/page_extensions.py`：横向页内标签改为**左侧竖向导航**
  （`#extensionsNav`，基础/加装分组，独立滚动）+ 右侧 `QStackedWidget`；`tabs` 保留为
  兼容门面（`labels/currentKey/setCurrentKey`）。
- `petcore/mods/manifest.py` + `contracts/contributions.py` + `mods/feature.py`：
  `name_zh` 字段与 `SettingsPageSpec.owner/label/group`；13 个内置/示例 `mod.json` 补中文名。

**验证**

- 新增 `tests/test_petcore_installer.py`（4 条）：setup 含鲸鱼娘图标、模组路径不含
  `{userappdata}` 且都在 `{app}\mods`、frozen 模拟下 `install_mods_dir()` 生效、
  安装目录 `.trusted` feature 在全局开关关闭时仍加载。
- 新增 `tests/test_petcore_extensions_nav.py`（14 条）：分组/中文名/过滤/兼容门面/卸载禁用。
- 全量：`775 passed, 5 skipped`；ruff 绿；`petcore --check` 退出码 0。

**未验证**

- 真实安装到自定义目录（含 Program Files 权限）与卸载清理未跑；仅做路径/加载逻辑测试。

---

## L022 · 2026-10-21 · 彩蛋图片与点击音效包

**改动**

- `petcore/ui/easter_egg.py`：`EasterEggController` + 无边框置顶弹窗；目录默认
  `assets/big_blue_fat_fish`（24 张），点击/Esc 关闭，连续打开按 24px 错位。
- `petcore/ui/pet_window.py`：`show_easter_egg()`；初始化 `EasterEggController`，
  `shutdown()` 统一关闭。
- 菜单「工具与帮助 → 彩蛋图片」`easter_egg` + `coverage.py` 登记；设置 →「互动与物理」
  新增「彩蛋」卡片（开关/标题/目录/清空/预览）。
- `petcore/media/click_sound.py`：`click_sound_pack` 解析（builtin default/duck、
  自定义文件/文件夹）与随机选择；duck 的 `Ya1/Ya2.mp3` 用 imageio-ffmpeg 转为
  44.1kHz/16-bit 单声道 wav（0.238s / 0.108s）。
- `petcore/media/sound.py`：wav 继续 `QSoundEffect`；非 wav 增加 `QMediaPlayer +
  QAudioOutput` 缓存兜底。
- `petcore/ui/pet_window.py`：点击/碰边/碰撞音效统一走 `click_sound_pack` 随机候选；
  `_warm_interaction_assets()` 预热全部候选。
- 设置页「点击反馈」加「音效音源」下拉 + 路径 + 选择文件/文件夹 + 试听。

**验证**

- 新增 `tests/test_petcore_click_sound.py`（10 条）与 `tests/test_petcore_easter_egg.py`（6 条）。
- 真实资产探针：`duck` 候选 `Ya1.wav/Ya2.wav`；`EasterEggController` 在真实
  `assets/big_blue_fat_fish` 上找到 24 张图并成功弹窗。
- 全量：`775 passed, 5 skipped`；ruff 绿。

**未验证**

- 真实声卡试听 duck/自定义 mp3（测试与 conftest 静音）；弹窗在多屏/真实主题下的层级。

## L023 · 2026-10-21 · P8 多宠推动、气泡跟随、设置重组与打包回归

**改动**

- **多宠碰撞/移动**：`pet_manager.py` 轻碰不再 `_cancel_move_plan()`、不再写速度；
  只有 `impact_speed >= HIT_FEEDBACK_MIN_SPEED` 才 `motion.set_velocity()`（切 thrown）。
  分离后按实际位移 `shift_move_plan(dx,dy)` 继续漫游；探头宠物轻碰时按
  `static=True`（无限质量）处理，只推开对方，真撞击才 `arm_throw_egg()` +
  `cancel("collision")`。`pet_window.py` 新增 `shift_move_plan/abort_move_plan`。
- **子宠退出**：`quit_from_menu()`：主宠退应用，子宠只 `PetManager.close_slot()`；
  菜单文案子宠为「退出这只」。
- **气泡**：`bubble.py` 重写，新增 `reposition()` 与 `show_image()`；`PetWindow.moveEvent`
  同帧合并后跟随，`set_scale()` 后重排。彩蛋 `show_easter_egg()` 默认进气泡，
  `easter_egg_display=window` 才用独立弹窗。`config.py` 新增该键。
- **彩蛋菜单行**：`easter_egg_entry.py` 27px 头像 + 标题 + 「请点击」；`MenuItem.builder`
  支持 `QWidgetAction`。
- **菜单模板打包回归**：`menu_layout.py` 新增 `BUILTIN_DEFAULT_LAYOUT` /
  `load_default_with_source()` / `merge_user_layout()`；`app.py` 把合并结果落盘；
  `cli.py --check` 输出 `menu_template`；`build_petcore.ps1` 补
  `--add-data petcore/menu_templates`。根因是旧产物 `_internal/petcore/` 只有
  `builtin/`，旧 `menu_layout` 无模板可合并，右键缺「播放动画/彩蛋图片」。
- **安装向导路径**：`petcore.iss` 加 `DisableDirPage=no`、`UsePreviousAppDir=yes`、
  `DefaultDirName={code:GetDefaultDir}`，`[Code]` 读卸载键 `InstallLocation`
  预选旧路径。
- **设置 IA**：`SettingsPage.tab()/embed_page()` 页内分页基础设施；
  「互动与物理」拆 8 页（点击/点击台词/自言自语/拖拽/碰撞/动画/彩蛋/免打扰），
  「菜单」拆菜单编排/快捷启动，「关于与诊断」拆版本诊断/链接/网络/回收内存。
- **Core 内置特性**：`CORE_FEATURE_IDS` + `SettingsPageSpec.host_page`；7 个内置
  feature 归 core，设置页内嵌到对应 Core 页，不再进扩展导航。
- **扩展管理**：导航顺序 扩展管理 → 基础扩展 → 加装扩展，组头可折叠；
  setup 的 `.trusted` 与用户导入都归加装；Core 内置项标「已并入 Core」并禁用启停/卸载。
- **文档**：新增 `docs/PETCORE-MAIN-PARITY-BACKLOG.md`；更新 SPEC/ROADMAP/
  ARCHITECTURE/MOD-FORMAT/INDEX/README/petcore README/AGENTS。

**验证**

- `QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **823 passed, 5 skipped**。
- `ruff check pet/ tests/ petcore/` → 全绿。
- `.venv/Scripts/python -m petcore --check` → exit 0，`menu_template=json`，
  `menu_layout_diagnostics=[]`。
- 真实旧 `menu_layout` 合并探针：补回 `animations_hub`、`playback_speed`、
  `drag_physics`、`spawn_pet`、`golden_spin`、`tools_help`（含 `easter_egg`）。
- 模板缺失模拟：`menu_template=builtin`，菜单仍完整；warning 只输出一次。
- 性能探针（offscreen）：`collide()` 6.9µs/对、`bubble.reposition` no-op 1.4µs、
  `load_default+resolve` 282.8µs、QMenu(12 项) 271.4µs（见 P8 PR 报告）。
- Inno `ISCC.exe` 编译成功（72.890s）；`build_petcore.ps1 -Clean -Installer` 产物：
  setup **178,532,356 字节**，主 exe `Subsystem=2`，
  `_internal/petcore/menu_templates/petcore-default-v1.json` 存在，打包后 `--check`
  exit 0 且 `menu_template=json`。图标提取为鲸鱼娘（32×32 目视）。

**未验证**

- 真实桌面手感：多宠互推、探头被轻碰、气泡跟随拖拽/漫游、子宠单独退出。
- 安装向导每次显示路径页与重装预选旧路径（会真装机，未自动执行）。
- 真实声卡音效与多屏彩蛋层级。

**后续**

- P9 从账户/额度开始（`petcore/account/`），再进 worker/AI；差距清单见
  [`PETCORE-MAIN-PARITY-BACKLOG.md`](PETCORE-MAIN-PARITY-BACKLOG.md)。

## L024 · 2026-10-21 · P8.1 字号/彩蛋图片、菜单结构、弹弓与直播兼容

**改动**

- **字号/图片大小**：`ui_font_size`(10–18)、`bubble_text_scale`(50–300)、
  `easter_egg_image_scale`(50–300)、`self_talk_image_scale`(50–300)；
  `bubble.set_text_scale()/show_image(image_scale=)`；菜单/设置/彩蛋菜单行跟随字号。
- **自言自语配图**：`self_talk_image_chance`(默认 30)、`self_talk_image_dir`；
  `PresentationPort.show_image()`；设置页新增配图三行；出图失败回退文字。
  点击台词改 `say(force=True)`。
- **菜单结构**：`easter_egg` 第一项；`playback_speed` 默认隐藏；尾部固定
  `modern_settings → separator → quit`；新增幂等 `migrate_p8_menu()` 并在
  `CoreHost.reload_menu()` 写盘。
- **播放动画预览**：分类子菜单 `aboutToShow` 懒加载；新增
  `petcore/media/thumbnails.py`（帧序列/GIF/WebM 代表帧、LRU 128、磁盘缓存、2 线程）；
  随机动作按前缀分组；`menu_animation_icons` 可关。
- **弹弓右键**：`SlingshotController.suppress_until` + `PetWindow._suppress_context_menu`；
  瞄准/发射后 0.35s 内不构建右键菜单。
- **点击监听**：`InteractionAdapter.attach_window()/detach_window()`；`PetManager`
  在 spawn/restore 后补挂，子宠点击台词立即生效。
- **设置 X 保存**：`dialog._commit()`；`closeEvent` 保存关闭；取消/Esc 仍恢复快照。
- **直播捕获兼容**：`stream_capture_mode`；宠物窗口与气泡从 Tool 切普通顶层
  `Window`，`apply_stream_window()` 清 Win32 Tool/NoActivate 位；设置「外观与交互」
  新增开关；多宠每窗可捕获。
- **文档**：SPEC 规则 33–40 + §13、ROADMAP §19、AGENTS 新红线、
  parity backlog、PR 报告 P8.1。

**验证**

- `QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **875 passed, 5 skipped**。
- `ruff check pet/ tests/ petcore/` → 全绿；`petcore --check` exit 0，`menu_template=json`。
- 真实旧 config 副本迁移后：顶层第一项 `easter_egg`，播放速率隐藏，尾部
  `modern_settings/separator/quit`；动画分类展开前 0 项，展开后 1 项且图标非空。
- 缩略图实测：帧序列 18.2ms/张，WebM 668ms/张（后台 2 线程）。
- 打包：`-Clean -Installer` 见 PR 报告 §5.3。

**未验证**

- 真机目视：字号 10/18、气泡 300%、彩蛋图片 300% 与 DPI。
- OBS/直播姬真实捕获（需选 Windows 10 1903+）。
- 真实 WebM 角色首展开缩略图等待手感。
- 安装向导旧路径预选与卸载清理（会真装机）。

**后续**

- P9：账户/额度 → worker/AI；其余差距见 parity backlog。

## L025 · 2026-10-21 · P8.2 隐藏态气泡、配图合并、托盘菜单

**改动**

- **隐藏态不再冒泡**：`PetWindow.say()` / `show_image()` 先判 `isVisible()`；
  `set_visible(False)` 收起气泡。`_PresentationAdapter._window()` 优先选可见桌宠，
  避免自言自语/提醒打到隐藏窗口上。
- **配图设置合并**：「互动与物理 → 彩蛋与配图」同时收纳彩蛋图片（目录/大小/标题/
  显示方式）与自言自语配图（目录/大小/出图概率）；`fun.self-talk` 设置页只保留
  节奏与候选台词，避免两个入口互相覆盖。
- **托盘菜单**：新增 `CoreHost.build_tray_menu()`：显示/隐藏桌宠、显示全部/隐藏全部
  （多宠时）、桌宠设置、打开数据目录、重新加载扩展、逐宠「显示/隐藏、回到右下角、
  退出这只」、退出。`TrayIcon` 左键/双击切换显示；菜单替换延迟到下一事件循环，
  旧菜单延后释放，避免在菜单动作执行中销毁菜单。
- 文档：SPEC §13、AGENTS 隐藏态/托盘/配图规则、本 log、P8.1 PR 第二轮改进。

**验证**

- `pytest tests/test_petcore_*.py tests/test_architecture.py -q` → **598 passed**。
- 新增 `tests/test_petcore_tray.py`（3 条：隐藏后菜单显示「显示桌宠」并能唤回、
  可见时「隐藏桌宠」、逐宠子菜单与退出）与隐藏态气泡测试。
- `ruff check` 相关文件全绿；最终门禁 `879 passed, 5 skipped`。
- 重打包：`dist/dsh-pet-core-setup.exe` **185,805,307 字节**（ISCC 99.860s），
  主 exe `Subsystem=2`，打包后 `--check` exit 0、`menu_template=json`。

**未验证**

- 真实 Windows 托盘单击/右键与菜单替换的实机手感（offscreen 只验证对象与动作）。
- 隐藏态下各 mod 的自定义气泡是否都走 presentation 端口（第三方导入包需自查）。

**后续**

- 重打包安装包并做一次托盘/隐藏态实机验收。

## L026 · 2026-10-21 · P8.3 托盘菜单、自语/点击出图

**改动**

- **托盘右键菜单**：`TrayIcon` 收到 `Context` 不再 `refresh()`（原先会在 Qt 正要
  弹出时替换菜单，导致什么都不显示）；托盘菜单改为**原地重建动作**
  （`QMenu.aboutToShow` → `CoreHost.populate_tray_menu()`），不再替换 context menu；
  QSystemTrayIcon 父对象改为 None，避免桌宠窗口隐藏/销毁影响托盘。
- **自语/点击出图**：新增 `petcore/media/talk_images.py`（目录解析、可读图过滤、
  `pick_choice()` 先决定出图/出文字、概率/大小读取）。`fun.self-talk` 与
  `fun.click-talk` 共用；出图失败回退文字；`_speak()` 用 try/finally 保证任何异常
  后仍排下一次；日志记录 `kind/dir/images/shown`。
- **诊断**：`--check` 新增 `self_talk_images`（目录、文件数、可读图数、内置目录），
  可在安装后的 exe 上直接验证素材与 Qt 图片插件是否正常；feature 加载诊断写入
  `petcore.log`。
- **设置**：「彩蛋与配图」新增「当前目录」只读信息与「预览配图」按钮；`PetWindow`
  在 `show_image()` 返回 True 后再检查气泡可见性，不可见则回退文字。
- 文档：SPEC/AGENTS 规则、P8.1 PR「第三轮改进」。

**验证**

- `pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **887 passed, 5 skipped**；ruff 全绿。
- 新增/更新测试：自语 100% 出图、坏目录回退内置、异常后仍排下一次、点击台词出图、
  托盘 Context 不替换菜单、`--check` 图片字段。
- 源码探针（真实 config 副本）：chance=100 出 160×160 图片；坏目录回退内置仍出图；
  点击出图；托盘隐藏后 `aboutToShow` 首项变「显示桌宠」且能唤回。
- 打包后 `dist/dsh-pet-core/dsh-pet-core.exe --check`：`self_talk_images.readable=24`
  （内置目录 24 张全部可读），说明安装包素材路径与 Qt 图片插件正常；
  setup **185,797,398 字节**（ISCC 100.859s），主 exe `Subsystem=2`。

**未验证**

- 真实 Windows 托盘右键弹出与菜单动作（offscreen 只验证对象/信号）。
- 安装后 `--check` 的 `self_talk_images.readable` 是否仍为 24（本轮构建后实测）。

**后续**

- 若安装包 `readable=0`，说明是 Qt 图片插件/打包路径问题，按 `--check` 输出继续定位。

## L027 · 2026-10-21 · P8.4 鼠标穿透归位托盘、彩蛋/配图高清

**改动**

- **右键菜单摘掉「点击穿透」**：`menu_templates/petcore-default-v1.json` 与
  `menu_layout.BUILTIN_DEFAULT_LAYOUT` 删除 `click_through`；`menu_actions.core_items`
  与 `settings/coverage.py` 同步移除；新增 `migrate_p9_menu()`（任意层级摘除该项 +
  清理子菜单多余分割线，幂等），`CoreHost.reload_menu()` 串行跑 p8 → p9 迁移。
- **托盘菜单接管**：`populate_tray_menu()` 新增可勾选「鼠标穿透」（紧跟显示/隐藏），
  `CoreHost.all_click_through()` / `set_all_click_through()` 一次作用到所有桌宠；
  开启后主宠气泡提示「已开启鼠标穿透，可从托盘菜单关闭」；不在托盘动作里
  `refresh()`（菜单弹出期间 `clear()` 会删掉正在发信号的 QAction），勾选态由下一次
  `aboutToShow` 重建刷新。设置页「外观与交互 → 点击穿透」保留为第二入口。
  注意 `PetWindow.say()` 只接受 `(text, duration_ms)`，没有 `force`（提示别照抄
  feature 端口的 `say(force=True)`）。
- **图片装载新模块** `petcore/media/images.py`：`sanitize_dpr` / `screen_dpr` /
  `physical_side` / `scale_pixmap` / `load_pixmap` / `logical_size`。规则＝逻辑上限 ×
  屏幕 DPR = 物理解码尺寸，pixmap 写回 DPR；小图按 DPR 预放大以保持逻辑尺寸。
- **彩蛋弹窗**：`load_scaled_pixmap(path, max_side, dpr)` 改走新模块；
  `EasterEggPopup(..., dpr=)` 记录 `device_pixel_ratio`，图片 label 与窗口尺寸改用
  逻辑尺寸；`EasterEggController.show()` 传宠物所在屏的 DPR。
- **气泡配图**：`_scaled_pixmap(image, max_side, dpr)`、`show_image(..., dpr=)`；
  `image_label` 尺寸用 `logical_size()`；`PetWindow.show_image()` 传
  `screen_dpr(self)`。
- **菜单头像**：`easter_egg_entry._round_pixmap(pixmap, dpr)` 物理边长 27×DPR，
  `avatar_pixmap()` 按 DPR 预缩放后裁圆。
- **气泡同图层**：`SpeechBubble` 新增 `_window_flags()` / `_apply_window_flags()` /
  `set_host_on_top()`（默认置顶），并补 `WindowDoesNotAcceptFocus`；
  `PetWindow._apply_flags()` 调 `bubble.set_host_on_top(self.always_on_top)`；
  `EasterEggPopup(..., on_top=)` 跟随宿主置顶开关。修「图片气泡和桌宠不在一个图层」
  —— 桌宠默认置顶而气泡不是，图片气泡比文字气泡大、会压到桌宠身上就露馅。
  同主分支 `pet/speech_bubble.set_host_on_top`。
- 测试：新增 `tests/test_petcore_images.py`（7 条：DPR 兜底、物理上限、大图/小图、
  已有 pixmap、弹窗逻辑尺寸、气泡逻辑尺寸）；`test_petcore_tray.py` 增加托盘穿透
  一次作用全部桌宠；`test_petcore_menu_layout.py` 增加 p9 迁移幂等与模板不含该项。

**行为变化与理由**

- 主分支 README 一直写「鼠标穿透从托盘菜单关闭」：穿透开启后右键菜单本身点不到，
  唯一稳定的恢复入口只有托盘。放进右键菜单 = 用户开了就回不来。
- 「彩蛋图发虚」的根因不是源图不够大，而是旧路径把图缩到 520/320 **逻辑**像素、
  pixmap DPR=1，再交给 QLabel；1.5 倍缩放的屏幕上 QLabel 又要放大到 780/480 物理
  像素 = 两次重采样。新路径直接解码到物理像素，QLabel 1:1 贴图。
- 弹窗逻辑边长仍由 `clamp_popup_side()` 决定（520 × 用户百分比，280–1200），
  不改变用户已经调好的显示大小；本次只改清晰度。

**验证**

- `QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py tests/test_architecture.py
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **897 passed, 5 skipped in 39.09s**；`ruff check pet/ tests/ petcore/` 全绿。
- 锐度实测（offscreen + `QT_SCALE_FACTOR=1.5`，`assets/big_blue_fat_fish/big_blue_fat_fish.jpg`，
  弹窗整体 grab 816×900）：旧路径（dpr=1）梯度能量 **10.99**，新路径（dpr=1.5）
  **16.37**，+49%。
- 真实机器屏幕探针：`TM140VDXP02 geom 1280×800 dpr 1.5 logicalDpi 96`——本机就是
  1.5 倍缩放，旧路径必然发虚。
- 源码探针（真实 config 副本 + `QT_SCALE_FACTOR=1.5`，模拟本机 1.5 倍缩放）：
  - 旧布局里带 `click_through` → 启动迁移后配置与注册表都不再含该项；
  - 托盘菜单可勾选「鼠标穿透」：触发后 `all_click_through=True`，桌宠气泡
    「已开启鼠标穿透，可从托盘菜单关闭」；重开菜单为勾选态；再触发关闭并提示；
  - 气泡配图：物理 `480×480`、DPR 1.5、label 逻辑 `336×336`（320 + 2×8）；
  - 彩蛋弹窗：窗口 `544×600`、图片 label 逻辑 `520×520`、pixmap 物理 `780×780`、
    DPR 1.5、`popup.device_pixel_ratio=1.5`；
  - 图层：桌宠 `always_on_top=True` 时气泡与彩蛋窗都带 `WindowStaysOnTopHint`，
    关掉置顶后两者同步失去（`test_bubble_keeps_the_pet_layer` /
    `test_popup_follows_the_host_topmost_flag`），源码探针输出
    `pet top True bubble top True` → `after off: pet False bubble False` →
    `after on : pet True bubble True`。

- 打包（增量，ISCC 56.234s）：`dist/dsh-pet-core-setup.exe` **185,809,452 字节**；
  主 exe `Subsystem=2`；`--check` exit 0、`menu_template=json`、
  `self_talk_images.readable=24`；包内模板已无 `click_through`；直接读 PYZ 确认
  `petcore.media.images`、`migrate_p9_menu`、`set_host_on_top`、
  `set_all_click_through` 与新提示文案都进包。
- 全量门禁：**900 passed, 5 skipped**；ruff 全绿。

**未验证**

- 真实桌面（非 offscreen）弹窗/气泡的肉眼观感，以及真实系统托盘勾选状态。
- 跨屏 DPR 不同时，已经显示中的气泡/弹窗不会立刻按新屏重解码（下次出图才生效）。

**后续**

- 需要时监听 `QWindow.screenChanged`，在跨屏后按新 DPR 重新装载当前图片。
## L028 · 2026-10-22 · P0 主分支对齐审查与迁移契约冻结

**改动**

- 新增 `docs/PETCORE-FUNCTION-MATRIX-2026-10-22.md`，逐项对照主分支 v4.3.4 的用户功能域，
  标记已对齐、部分、未做、有意差异和目标阶段。
- 新增 `docs/PETCORE-HANDOFF-PLAN-2026-10-22.md`，把 P0–P6 拆成可交接阶段，固定依赖、
  禁止事项、验收和本地提交标题。
- 新增本审查报告，记录当前 petcore/架构/报告/CI 门禁结果和真实环境限制。
- 更新 SPEC、ROADMAP、MAIN-PARITY-BACKLOG、ARCHITECTURE，冻结每宠配置作用域、WorkerHost、
  迁移/回滚、Core/mod 边界、默认扩展和发布切换门。

**验证**

- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest <test_petcore 文件列表> -q`
  → `603 passed`。
- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest <petcore + guards> -q`
  → `900 passed, 5 skipped`。
- `.venv/Scripts/ruff check pet/ tests/ petcore/` → `All checks passed`。
- `.venv/Scripts/python -m petcore --check` → exit 0。

**未验证**

- 本阶段只改文档，没有改变运行时行为；真实双屏、安装器 E2E、非 Windows 窗口和完整大素材
  导入继续留给 P1–P6 的实机阶段。
---

## L029 · 2026-10-22 · P1 每宠配置作用域与基础迁移

**改动**

- `ScopedConfig` 路由全局键与当前宠物键；设置窗口绑定当前窗口并保存到正确配置文件。
- `CoreHost._apply_live_to()` 不再把主宠的角色、缩放、动画、物理和台词覆盖到所有子宠；
  `PetManager` 只同步真正全局键。
- 点击台词、自言自语按具体宠物读取配置；新增宠物生命周期钩子收口 timer。
- 旧 standalone 配置和 slot 档案迁移到新目录，先写 `migration-backup/`，不修改旧源。
- 新增配置作用域、设置窗口和迁移回归测试。

**验证**

- petcore：`608 passed`；petcore + 架构/报告/CI 守卫：`907 passed, 5 skipped`。
- ruff：通过；`python -m petcore --check`：exit 0。
- 作用域性能：get 0.14 µs/op（n=50,000），set 12.75 µs/op（n=5,000），snapshot 34.08 µs/op（n=500）。

**未完成**

- 会话、待办独立文件和 API/凭据引用需要对应业务消费者，留到 P3/P4；真实双屏和安装器
  E2E 留到 P5/P6。
---

## L030 · 2026-10-22 · P2 WorkerHost/离线扩展/角色导入

**改动**

- 新增 `petcore/platform/worker.py`，提供真实子进程 WorkerHost/WorkerSession、JSONL READY、
  配置推送、取消、错误回调、owner 替换、心跳超时和有界关闭。
- `CoreHost` 持有 WorkerHost，`HostPorts.worker` 注入；退出时统一收口 worker。
- 设置常规页增加角色目录导入；旧素材 Graph 映射补齐 Touch_Head/Say/Sleep/StartUP/Work/Raised。
- 安装器 5 个官方离线 feature 默认选中，README 与安装器测试同步。
  （**L034 起已回退为默认不勾选**：该默认值与「不勾选就真不装」的用户口径冲突。）

**验证**

- Worker/角色/安装器/架构：`21 passed in 1.54s`。
- petcore + 架构/报告/CI：`915 passed, 5 skipped in 27.15s`。
- ruff：通过。

**未完成**

- 业务 worker、旧 `pet` 媒体后端解耦、真实安装升级卸载和声卡/双屏人工验收留给后续阶段。
---

## L031 · 2026-10-22 · P3 Core 账户/余额基础

**改动**

- 新增 `petcore/account/AccountService` 与 `BalanceResult`：服务协议校验、钥匙串读取、
  DeepSeek 余额解析、多币种选择、30 秒内存缓存和稳定错误分类。
- `ApiPort` 增加 `fetch_balance()`，CoreApiPort 转发到账户服务；CoreHost 持有进程级服务。
- 新增账户/API/net/架构回归测试，响应体和密钥不进入日志。

**验证**

- `pytest test_petcore_account.py test_petcore_api.py test_petcore_net.py test_petcore_architecture.py -q`
  → `84 passed in 1.89s`。
- `ruff check petcore tests/test_petcore_account.py` → 通过。

**未完成**

- 余额菜单、自动刷新、档位动画、灵动岛展示和真实远程账户请求留给后续 P3 UI/worker 阶段。

---

## L032 · 2026-10-22 · P3 每宠会话存储接缝

**改动**

- 新增 `petcore/chat/SessionStore` 和 `ChatSession`，按 slot/角色隔离目录，限制消息数量和
  单条长度，原子写入，拒绝路径逃逸。
- 扩展 worker 协议的 request/delta/result/done 常量，并为 WorkerSession 增加 request 接缝。

**验证**

- `pytest tests/test_petcore_sessions.py` → `3 passed in 0.83s`。
- `ruff check pet/ tests/ petcore/` → 通过。

**未完成**

- 会话尚未接入 AI worker 或聊天 UI；业务接入继续属于 P3 后续。

---

## L033 · 2026-10-22 · 插件市场 v1（索引/下载/安装/回滚/UI/CLI）

**改动**

- 新增 `petcore/market/`：索引模型与状态、ETag + 磁盘缓存的多源读取、大小/SHA-256 校验、
  `.part` 续传编排、staging → 备份 → 原子安装、`market-lock.json`、回滚与 CLI。
- 新增 `petcore/net/market.py`：索引 GET（含 GitHub Contents API base64）与 Range 下载，
  复用 `net/http.urlopen` 的「系统代理优先、失败改直连」。
- `petcore/mods/install.py` 暴露 `open_pack()` 供市场复用解包；`petcore/cli.py` 接入
  `petcore market list/show/install/update/rollback/doctor`。
- 新增设置页 `page_market.py`，注册到「扩展管理」左导航（顺序：扩展管理 → 插件市场）；
  新增全局键 `market_index_url`（默认空 = 官方索引），feature 安装仍受 `allow_feature_mods`。
- 文档：新增 `PETCORE-MARKET.md` 与 `market-index.schema.json`，更新 INDEX / ROADMAP /
  MOD-FORMAT §6.2 / Phase 4 设计文档指针。

**文件（`git diff --numstat` + 新增行数）**

| 文件 | 变化 |
|---|---|
| `petcore/market/{__init__,errors,verify,download,source,model,install,cli}.py` | 新增 1730 行 |
| `petcore/net/market.py` | 新增 178 行 |
| `petcore/ui/settings/page_market.py` | 新增 536 行 |
| `petcore/ui/settings/page_extensions.py` | +5 |
| `petcore/cli.py` | +18 |
| `petcore/config.py` | +2 |
| `petcore/mods/install.py` | +7 |
| `docs/{PETCORE-MARKET.md,market-index.schema.json}` | 新增 283 行 |
| `docs/INDEX.md` / `PETCORE-MOD-FORMAT.md` / `PETCORE-ROADMAP.md` / Phase 4 文档 | +28 / −1 |
| `petcore/AGENTS.md` | +5 / −2（导航顺序与市场边界） |
| `tests/test_petcore_market_{model,source,net,install,cli,ui}.py` | 新增 1266 行 |
| `tests/test_petcore_extensions_nav.py` | +26 / −16（导航新增「插件市场」契约） |
| `docs/PETCORE-LOG.md` / `PETCORE-LOG-INDEX.md` | +50 / +1（L033） |

**验证**

- `pytest tests/test_petcore_market*.py -q` → `53 passed in 24.90s`。
- `pytest tests/test_petcore_*.py tests/test_architecture.py -q` → `689 passed in 56.23s`。
- `ruff check pet/ tests/ petcore/` → 通过；`python -m petcore --check` → `diagnostics: []`。
- 实测（`.scratch/market-bench.py`，本机 Win11 / Py3.12.10）：500 包索引解析中位
  **12.4 ms**、峰值 **1.9 MB**；索引冷读 18.8 ms、内存命中 <0.1 ms；1 MB artifact
  下载 31.8 ms、SHA-256 1.15 ms、安装 31.2 ms；50 包列表首次刷新 8.6 ms、重建 0.49 ms。
- 真实 `windows` 平台截图（`.scratch/market-page-real.png`）：状态标签、可更新/阻止、
  feature 与索引源设置均正常渲染；本地 HTTP 端到端覆盖安装/更新/回滚/离线缓存。
- 全量 pytest：`9092 passed / 18 skipped / 2 failed`（21m32s）；两条失败均为测试顺序/
  负载问题（见报告 §五.4），修复 palette 泄漏后相关两族 `178 passed / 1 skipped`。

**未完成**

- `MerZlin/dsh-pet-extensions` 索引仓库尚未创建，未对真实 GitHub raw 做端到端；
- 数字签名、CDN/OSS 镜像、npm 通道（只保留 URL 层接口）均按计划留到后续。

---

## L034 · 2026-10-22 · 官方扩展恢复「默认不勾选」

**改动**

- `packaging/petcore.iss`：5 个 `mod_*` 任务加 `Flags: unchecked`，注释改为
  「默认不勾选；勾选才写入安装目录，不勾选完全不落盘」。
- `tests/test_petcore_installer.py`：`test_official_feature_tasks_are_default_selected`
  → `test_official_feature_tasks_are_opt_in`，断言由「不得出现 `Flags: unchecked`」
  改为「每个任务都必须有」。
- `examples/petcore-mods/README.md`：措辞回到「可勾选项（默认不勾选）」；顺带修正
  安装位置（`%APPDATA%\dsh-pet-core\mods\<id>` → `{app}\mods\<id>`，与 iss 一致）。
- 口径同步：`PETCORE-FUNCTION-MATRIX`、`PETCORE-HANDOFF-PLAN`、`PETCORE-SPEC` §14、
  `PETCORE-ROADMAP` §20、`PETCORE-MAIN-PARITY-BACKLOG`、`petcore/AGENTS.md` 全部改成
  「可选安装（默认不勾）」。
- `docs/PR-REPORT-PETCORE-P2-WORKER-OFFLINE-2026-10-22.md` 追加修正章节。

**理由**

用户最初口径是「setup 里可勾选，不勾选就真不会安装到本地」；P2 把默认值改成了勾选，
功能上仍可选、但默认行为反了。恢复默认不勾选，勾选后才写 `{app}\mods\<id>` 与 `.trusted`。

**验证**

- `pytest tests/test_petcore_installer.py -q` → 7 passed。
- `pytest tests/test_petcore_*.py tests/test_architecture.py
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q` → **985 passed**。
- `ruff check pet/ tests/ petcore/` → 全绿。
- `python -m petcore --check` → 退出 0。
- 重新出包（增量 `-Installer`，ISCC 完成后）：`dist/dsh-pet-core-setup.exe`
  **192,675,082 字节**；主 exe `Subsystem=2`；打包后 `--check` exit 0、
  `menu_template=json`、`diagnostics=[]`、`self_talk_images.readable=24`；
  冻结包内 `market --offline list` / `market doctor` 均可运行（doctor 对未创建的
  索引仓库返回 HTTP 404 诊断，属预期）。

**未验证**

- 安装向导里 5 个勾选框的**实际初始状态**尚未用截图确认（iss `Flags: unchecked`
  是 Inno 文档语义，测试只断言源码文本）。下次安装时人工看一眼。

---

## L035 · 2026-10-22 · 阶段编号统一：历史批次 H1–H8.4 vs 交付阶段 P0–P6

**改动**

- `docs/PETCORE-ROADMAP.md`：新增 §0「编号约定」与换算表；§3、§6–§19 的标题与 §2
  批次表由 `P1-A…P8.4` 改名为 `H1-A…H8.4`；§20 的 `P0–P6` 保持不变。
- `docs/PETCORE-SPEC.md`：§10–§14 标题改 `H6/H7/H8/H8.1/H8.4`，并在 §10 前加一行
  说明「历史批次 vs 当前交付阶段」。
- `docs/PETCORE-LOG-INDEX.md`：读取规则后补编号约定（历史行里的 P = H）。
- `docs/INDEX.md`：ROADMAP 条目改写，强调 §0 编号约定。
- 历史文档（`PETCORE-LOG.md` 既有条目、`docs/PR-REPORT-PETCORE-P1…P8…` 文件名）
  保持原样，不做回填重命名。

**理由**

GPT 的 P0–P6 计划与历史 P1-A…P8.4 重名不同义（新 P1=配置作用域，旧 P1=UI 风格），
两份文档已经并存。用 H 系列承接历史、P0–P6 只表示未来阶段，避免继续误读。

**验证**

- `pytest tests/test_petcore_docs.py tests/test_pr_report_discipline.py -q` → 237 passed。
- 全量 petcore 门禁 985 passed、ruff 全绿（同 L034 那一轮）。
- `grep "^## " docs/PETCORE-ROADMAP.md`：§3/§6–§19 均为 H 前缀，§20/§21 未受影响的
  P0–P6 与市场章节保持原样。

**未验证 / 风险**

- `docs/PR-REPORT-PETCORE-P1-SCOPE-2026-10-22.md` 等**新**报告仍叫 P1/P2/P3（指新轴），
  与历史 `P1C/P1F/P2/P3` 文件名并存；文件名不改，正文已在 ROADMAP §0 有换算口径。
