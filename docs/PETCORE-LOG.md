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

## L036 · 2026-10-22 · P3 流式对话、聊天宿主、截图与热键

**改动**

- `petcore/api/chat.py`（新，194 行）：`stream_chat()` —— SSE 逐段解析、一次性 JSON
  回退、`cancel` 轮询、超时、`net/http` 代理兜底；错误统一成 `net/errors` 的稳定
  reason；日志不记正文与密钥。
- `petcore/contracts/api.py`：`ApiPort.stream_chat(...)`；`petcore/ui/ports.py::CoreApiPort`
  转发并注入 keyring 解析出的 `ApiRequest`。
- `petcore/contracts/chat.py`（新）+ `petcore/ui/chat/`（新，window 289 / controller 296 行）：
  `ChatPort` 实现、Markdown 流式合帧（50ms）、停止/清空/历史下拉、按 `(owner, slot)`
  隔离；跨线程只用 Qt 信号，worker 线程不碰控件。
- `petcore/contracts/screen.py`（新）+ `petcore/platform/screenshot.py`（新，75 行）：
  `ScreenPort.capture()` 用 `QScreen.grabWindow(0)` 抓整屏到内存 PNG；不写盘。
  `contracts/screen.py` 只留数据类（`contracts` 必须 stdlib-only）。
- `petcore/platform/hotkeys.py`：单条 → 多条命名注册（每条独立 Win32 id），保留
  `apply(text, cb)` 旧签名；`active_texts()`、`clear(name)`。
- `petcore/ui/ports.py`：`WorkerNoticePort` —— worker 出错/异常退出转成用户可见提示
  （补齐 P3 验收「Worker 取消/超时/崩溃有用户反馈」）。
- `petcore/ui/app.py`：`HOTKEY_CONFIGS`/`HOTKEY_COMMANDS` 四条映射；
  `set_hotkey(text, kind=...)`；`run_feature_command()` 统一分发与「扩展未安装」提示。
- `petcore/config.py`：新增 `hotkey_open_chat` / `hotkey_look_screen` /
  `hotkey_screen_capture` / `ai_service` / `ai_model` / `ai_system_prompt`（全局键）。
- `petcore/ui/menu_actions.py` + 模板 + `menu_layout` + `coverage.py`：右键新增
  「AI 对话 / 看看屏幕 / 截图提问」；`icons.py` 增加 chat 图标。
- `petcore/ui/settings/pages_core.py`：常规页新增「AI 快捷键」三条 + 截图隐私说明。
- `tests/`：新增 `test_petcore_api_chat.py`(6)、`test_petcore_chat_ui.py`(6)、
  `test_petcore_screenshot.py`(4)、`test_petcore_hotkeys.py`(5)；
  `test_petcore_architecture.py` 增加 3 条守卫（chat Qt-free、mod 不 import 传输、
  engine 不 import ui）；`test_petcore_worker.py` 增加 worker 失败反馈；
  `test_petcore_menu_layout.py` 顺序断言更新。

**行为**

- AI 对话窗口归 core：mod 通过 `ChatPort` 发事件；流式逐字显示、停止即时生效、
  历史按宠/角色落盘。`petcore/chat/` 仍零网络、零 Qt。
- 截图提问：整屏抓取 → 内存 PNG → 多模态 `image_url`，全程不落盘。
- 热键：四条并存，失败可见。

**验证**

- `pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py
  tests/test_ci_workflows.py -q` → **1019 passed**。
- `ruff check pet/ tests/ petcore/` → 全绿。
- 性能探针（`.scratch/p3_probe.py`，本机）：本地 SSE 100 段首段 **38.3ms**、总
  **45.8ms**；窗口 300 段/50 次合帧 **21.8ms（0.4ms/次）**；真实屏幕 1920×1200@1.5
  抓屏 **204.7ms**、PNG **367KB**。

**打包受阻（环境）**

- `-Installer` 的 PyInstaller 成功，但 `--check` 冒烟启动被系统拦截：
  `WinError 4551 = "An Application Control policy has blocked this file."`，
  `HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState = 1`
  → 本机 **Smart App Control** 强制开启，拦截未签名的新构建 exe。
- 对照：复制到仓库目录的 notepad 可启动；PyInstaller 构建的空 hello 程序同样被拦；
  旧 setup 同样被拦。与 petcore 代码无关。
- 结论：本轮**没有产出 P3 安装包**；`dist/dsh-pet-core-setup.exe` 仍是 14:59 的旧产物。
  解除需用户关闭 Smart App Control 或给产物签名。**（L038 已用本机开发证书签名解决。）**

**未验证**

- 真实 DeepSeek 端到端的首 token 延迟（本机无可用密钥，探针只测传输开销）。
- 抓屏在 GUI 线程同步执行（约 205ms），用户按热键会有一次可感知停顿。

---

## L037 · 2026-10-22 · ai.chat 参考扩展与安装口径

**改动**

- `examples/petcore-mods/ai.chat/`（新）：`mod.json`（host-only、capabilities
  network.request/screenshot.capture/speech.present/settings.read/write）+
  `host/factory.py`（399 行）：`open`/`look_screen`/`screen_capture` 三条命令、
  `chat.on_submit/on_stop`、系统提示词 + 历史组装、截图内联、错误回退、设置页
  （服务/模型/提示词/视觉开关）。
- `packaging/petcore.iss`：新增 `mod_aichat` 任务（`Flags: unchecked`）+ 文件与
  `.trusted` 投放，和其余 5 个官方扩展同口径。
- `examples/petcore-mods/README.md`：从 5 个改 6 个，补 ai.chat 安装命令。
- 测试：`test_petcore_ai_mod.py`(7)；`test_petcore_installer.py` 两个清单补 ai.chat。

**验证**

- 全量 petcore 门禁 1019 passed（含新增 7 条 + worker 反馈 1 条）；ruff 全绿。
- 打包后验证见 PR 报告「实机运行记录」。

**未验证**

- 真实模型下的多轮对话质量；视觉模型对 367KB 截图的接受度（不同服务上限不同）。

## L038 · 2026-10-22 · 构建产物签名与 P3 打包收尾

**改动**

- `scripts/make_dev_signing_cert.ps1`（新）：创建本机开发用代码签名证书
  （`CN=DSH Pet Core Dev`，RSA 3072 / SHA256，3 年），公钥导入
  `CurrentUser\Root` + `CurrentUser\TrustedPublisher`；`-Remove` 可撤销信任。
- `scripts/build_petcore.ps1`：新增 `-SignThumbprint` 与 `-TimestampServer`；
  exe 在 `--check` 冒烟前签名，setup 在 ISCC 之后签名；时间戳失败退回无时间戳，
  签名状态非 Valid 直接报错。
- `petcore/README.md`：补「签名后构建」两条命令。
- `petcore/AGENTS.md`：新增红线（未签名产物会被 Smart App Control 拦截；签名在
  `--check` 之前）。
- `docs/PETCORE-SPEC.md` §16：补打包签名口径。
- `docs/PR-REPORT-PETCORE-P3-AI-2026-10-22.md`：「打包验证（受阻）」改写为
  「打包与签名（已完成）」，附签名状态与安装路径验证。

**验证**

- 签名状态：`dsh-pet-core.exe` / `dsh-pet-core-setup.exe` 均 `Valid`，
  `CN=DSH Pet Core Dev`。
- 打包：ISCC 112.953s，setup **194,139,120 字节**；打包后 `--check` exit 0、
  `menu_template=json`、`diagnostics=[]`。
- 扩展安装路径：`--root <临时目录> mods install examples/petcore-mods/ai.chat`
  → `installed ai.chat 1.0.0`；`--check` 输出 `mods=['ai.chat']`、`diagnostics=[]`。
- 源码门禁：1019 passed（未改代码，签名只动构建脚本/文档）。

**未验证 / 边界**

- 开发证书只在本机可信；正式分发必须换成 CA 证书。
- 完整安装向导 E2E（安装/升级/卸载）未在本机跑，避免影响现有 `E:\dsh-pet-core` 安装。
- 真实 DeepSeek / 视觉模型端到端仍未跑（无可用密钥）。

## L039 · 2026-10-22 · P3 收口：对话窗 / 看看屏幕 / 截图提问

**范围**：把主分支已经验证过的对话窗与识屏交互搬进 Core，`ai.chat` 继续只负责
prompt/路由；新增 `ScreenAskPort`，并让扩展命令按发起桌宠派发。

**改动**

- `petcore/ui/chat/`（新增 `themes.py` 244、`markdown_view.py` 85、`styles.py` 162、
  `icons.py` 129、`widgets.py` 905；重写 `window.py` 926+/197−、`controller.py`
  138+/40−）：移植主分支现代双栏对话窗（侧栏会话、Markdown 气泡、附件、浮动输入框、
  置顶/最小化、无边框拖拽/缩放、紧凑抽屉），新增 `record()` 静默写历史与
  `take_attachments()`。
- `petcore/ui/screen/`（新增 6 个文件、1603 行）：框选覆盖层、DPR 裁剪、
  `ScreenAskWindow`（多轮、图片仅内存、DS 鲸鱼标题、10% 鲸蛙加载彩蛋）与
  `ScreenAskController`；保持 Qt 在 Core、网络在 mod。
- `petcore/contracts/screen.py`：`ScreenCapture.app_info`、`ScreenError`、
  `ScreenSelectionCancelled`、`ScreenPort.capture_region/foreground_app`、`ScreenAskPort`。
- `petcore/contracts/host.py` / `petcore/ui/ports.py` / `petcore/ui/app.py`：
  `HostPorts.screen_ask`、`QtScreenPort` 框选与前台应用；`CoreHost` 持有
  `ScreenAskController`；`run_feature_command(slot=)` 对声明 `slot` 的扩展命令按宠派发。
- `petcore/platform/foreground.py`（新 92 行）+ `petcore/platform/screenshot.py`：
  抓屏附带「进程名 | 窗口标题」，框选裁切复用同一编码路径。
- `examples/petcore-mods/ai.chat/host/factory.py`（371+/81−，版本 1.1.0）：看看屏幕
  改为气泡答复 + `ChatPort.record()` 静默入历史（默认不打开对话窗，
  `ai_look_screen_auto_open` 才唤出）；4 秒冷却/忙碌提示；截图提问改走框选 +
  `ScreenAskPort.on_ask(question, png, history, slot) -> str`；对话提交去重当前问题并
  支持附件图片。
- `petcore/config.py`：持久化 `ai_vision_enabled` / `ai_temperature` /
  `ai_look_screen_auto_open` / `chat_always_on_top` / `chat_follow_pet` /
  `chat_background` / `chat_accent`（此前 `ai_vision_enabled` 会被 normalize 丢掉）。
- `petcore/AGENTS.md`：新增对话窗移植、看看屏幕静默入历史、`ScreenAskPort` 边界、
  截图彩蛋独立、命令按宠派发五条红线。
- `docs/PETCORE-SPEC.md` §16/§19、`docs/PETCORE-ROADMAP.md` §20/§22、
  `docs/PETCORE-MAIN-PARITY-BACKLOG.md` §3.1 同步。
- 测试：`tests/test_petcore_chat_ui.py` 重写（15 条）、`tests/test_petcore_screen_ask.py`
  新增 23 条、`tests/test_petcore_ai_mod.py` 扩到 13 条、
  `tests/test_petcore_feature_command_slot.py` 新增 1 条。

**验证**

- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py
  tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **1058 passed in 41.05s**。
- `.venv/Scripts/ruff check pet/ tests/ petcore/` → 全绿。
- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m petcore --check` → exit 0，
  `diagnostics=[]`、`menu_template=json`。
- 性能探针（offscreen，n=20/50/200）：首次打开对话窗 23.7ms；`record()` 中位 1.72ms
  / p95 2.78ms；追加一条气泡 1.18ms；`ScreenAskWindow.start` 中位 13.99ms / p95 15.31ms；
  `begin_waiting` 0.02ms；`pick_loading_icon` <0.01ms；`foreground_app_info` 0.02ms。
- 视觉：offscreen `grab()` 渲染对话窗（双栏、右对齐用户气泡、Markdown、底部输入区）与
  截图问答窗（鲸鱼标题、图片 chip、用户气泡、加载鲸鱼 + 状态、输入行）。

**未验证 / 边界**

- 真实 DeepSeek / 视觉模型端到端未跑（无可用密钥）；真实桌面框选只做了 offscreen
  事件循环验证，未在本机真实桌面拖选。
- 未移植主分支的思考/联网过程面板、会话批量管理/重命名/删除、跟随桌宠定位、
  OCR/翻译/复制动作条、主动识屏与每日预算；已记入 parity backlog。
- `chat_follow_pet` 已持久化但窗口暂不跟随桌宠移动；`chat_background` 只支持
  `builtin:<theme>` 或绝对路径，不含主分支的裁切/透明度/填充键。

## L040 · 2026-10-22 · AI 边界收口：mod 拆分 / 线程调度 / 配置端口 / 外观跟随

**范围**：把 L039 留下的 6 个边界缺口全部落成代码或明确契约。
行为目标不变，重点是「运行时无 Qt、配置访问分层、聊天窗外观可配且实时生效」。

**改动**

- `petcore/mods/feature.py`（+39/−7）：`import_entrypoint()` 公开；包入口
  `host/__init__.py:create_host` 以 `submodule_search_locations` 加载并注册
  `sys.modules`，支持相对 import；异常时清理模块；普通 `.py` 入口行为不变。
- `petcore/contracts/host.py`（+13/−5）：新增只读 `ConfigPort` 与
  `HostPorts.config`；删除未实现的 `SettingsPort` / `HostPorts.settings`；
  `SchedulerPort` 明确「任意线程可调、回调在 GUI 线程」。
- `petcore/ui/ports.py`（+66/−29）：`_SchedulerBridge` 用 queued signal 统一在
  GUI 线程创建/销毁 `QTimer`；`QtScheduler` 的 `call_later/call_every/cancel`
  可从 worker 线程调用；新增 `QtConfigPort`；`build_ports` 接 `config`。
  定时器不挂 Qt parent（避免 bridge 析构时悬空 DeferredDelete 导致进程 abort）。
- `examples/petcore-mods/ai.chat/host/`：删除 689 行的 `factory.py`，拆成
  `__init__.py`（create_host）、`constants.py`、`prompts.py`（消息组装纯函数）、
  `runtime.py`（430 行，无 PySide6 / 无 `petcore.net` / 无 `petcore.api`）、
  `settings_page.py`（313 行，受信 UI）。`mod.json` 入口改为包入口，版本 1.1.0→1.2.0。
- `runtime.py`：配置只经 `ports.config`；worker 回 GUI 只经
  `ports.scheduler.call_later()`；看看屏幕/对话/截图问答逻辑不变。
- `settings_page.py`：新增「对话窗外观」分区——背景（默认/9 个内置主题/自定义图片）、
  强调色（hex 校验 + 颜色选择 + 恢复默认）、跟随桌宠、对话窗置顶；改动即时调用
  `host.chat.apply_appearance()`。
- `petcore/ui/pet_window.py`（+6/−1）：新增 `pet_moved` 信号，`moveEvent` 末尾 emit。
- `petcore/ui/chat/window.py`（+128/−1）：新增 `pet_window/follow_pet` 构造参数、
  `set_pet_window()` / `set_follow_pet()` / `position_near_pet()`；40ms 合并定位，
  右侧优先、放不下切左侧、再放下方，最后钳在可用区；`showEvent` 首次定位。
  顺带修复 `set_accent()` 只改 `_base_accent` 而 `_style()` 读 `accent_color`
  导致实时换色无效的问题。
- `petcore/ui/chat/controller.py`（+83）：`apply_appearance()` 把背景/强调色/置顶/
  跟随实时推到已打开窗口（不建窗、不唤窗）；创建窗口时接当前宠与 follow 配置。
- `petcore/ui/app.py`（+7）：`apply_live_settings()` 末尾刷新聊天窗外观。
- `petcore/ui/screen/controller.py`（+4）：明确截图问答历史「每次采集独立、只存内存、
  不落盘」。
- `tests/`：`test_petcore_ai_mod.py` 改包入口 + prompt/静态守卫/设置页外观；
  `test_petcore_scheduler.py` 新增 6 条；`test_petcore_chat_ui.py` 增 follow/外观；
  `test_petcore_feature.py` 增包入口；`test_petcore_live_settings.py` 增 chat 刷新；
  `test_petcore_screen_ask.py` 锁定不写盘。
- 文档：`PETCORE-SPEC.md` §19、`PETCORE-ROADMAP.md` §22、`PETCORE-ARCHITECTURE.md`
  契约清单、`PETCORE-MOD-FORMAT.md` 包入口与参考实现、`PETCORE-MAIN-PARITY-BACKLOG.md`
  AI 行、`examples/petcore-mods/README.md` 端口/包入口说明、`petcore/AGENTS.md` 五条红线。

**验证**

- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py
  tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **1083 passed in 52.62s**。
- `.venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods/ai.chat`
  → 全绿。
- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m petcore --check` → exit 0。
- 端到端 mod 加载：`petcore --root .scratch/ai-boundary mods install
  examples/petcore-mods/ai.chat` → `installed ai.chat 1.2.0`；`--check` 列出
  `ai.chat 1.2.0 enabled=true`，`diagnostics=[]`。
- 性能探针（offscreen）：`call_later(0)` 端到端中位 **0.027ms** / p95 0.061ms
  （n=50）；`ConfigPort.get` <0.001ms（n=200）；首次打开对话窗 24.7ms；
  `apply_appearance()` 无变化时 0.003ms（n=50）；`position_near_pet()` <0.001ms
  （n=100）。
- 视觉：offscreen 渲染对话窗与截图问答窗仍正常；设置页外观控件为普通
  combo/line edit/checkbox。

**未验证 / 边界**

- 真实桌面拖选、真实双屏/混合 DPI 下的 follow 定位未实机跑（offscreen 仅验证几何
  与事件）。
- `chat_background` 仍只支持 `builtin:<theme>` 或绝对路径，不含主分支的取景裁切、
  透明度和 cover/contain 独立开关。
- `cancel()` 改为 queued：已到点的定时器可能在 stop 处理前再触发一次；GUI 调用方
  （自言自语、报时）不受影响。
- 截图问答历史明确不落盘；这不是待办，而是隐私与语义约束。

## L041 · 2026-10-22 · 截图蒙层灰屏修复 + 深度思考/联网搜索

**范围**：修「截图提问整屏发灰」的生产环境 bug，并把主分支的深度思考与联网搜索
按「传输在 core、编排在 mod」的口径接进 petcore。

**改动**

- `petcore/platform/screenshot.py`（+17/−4）：`grab_screen_image()` 接受 Qt6
  真实返回的 `QPixmap`，`toImage()` 后 `setDevicePixelRatio(1.0)`。根因：覆盖层
  `QPainter.drawImage(QRect, QPixmap)` 抛 TypeError，`paintEvent` 首行就中断，
  整层不画 → 默认灰底；裁切/编码走 `QPixmap.copy/save` 恰好可用，所以框出来的图正常。
- `petcore/ui/screen/overlay.py`（+9/−1）：构造函数 `_as_image()` 兜底非 QImage。
- `petcore/config.py`（+29）：`ai_thinking`/`ai_reasoning_effort`/`ai_web_search`/
  `ai_web_engine`/`ai_web_results`/`ai_web_fetch` 六个全局键 + 归一化。
- `petcore/contracts/api.py`（+17）：`WebSearchOptions`；`ApiPort` 增
  `on_reasoning/on_status/thinking/reasoning_effort/web_search` 与搜索 Key 读写。
- `petcore/contracts/chat.py`（+8）：`ChatPort.reasoning()/status()`。
- `petcore/api/chat.py`（+417/−10）：`thinking_payload()`；`_extract_delta()` 兼容
  `reasoning_content`/`reasoning`；`ChatResult.reasoning`；只出思维链且
  `finish_reason=length` 抛 `ChatTruncated`；`research()` / `inject_search_context()` /
  `_run_tool()` / `_post_json()`；`stream_chat(web_search=)` 先检索后回答。
- `petcore/net/websearch.py`（+407，新）：百度/DuckDuckGo（免 Key，互为兜底）、
  博查/Tavily（需 Key）、`fetch_page_text()`、`format_results()`、稳定错误分类；
  复用 `net.http.urlopen` 的代理兜底。
- `petcore/ui/ports.py`（+43/−1）：`CoreApiPort` 透传参数并从钥匙串取搜索 Key
  （owner `core.websearch`）；`web_search_key_status()` / `set_web_search_key()`。
- `petcore/ui/chat/controller.py`（+48/−1）：`reasoning_received`/`status_received`
  排队信号；窗口不存在时丢弃；done 时把 `reasoning`/`activity` 写入 assistant 记录。
- `petcore/ui/chat/window.py`（+38/−1）：`append_reasoning()`/`add_activity()`/
  `last_thinking()`；`load_messages()` 回显思考面板。
- `petcore/chat/session_store.py`（+12/−3）：`from_dict()` 保留可选
  `reasoning`/`activity`（旧会话无字段照常加载）。
- `examples/petcore-mods/ai.chat/host/runtime.py`（+42）：读 6 个配置键，把
  `thinking`/`reasoning_effort`/`on_reasoning`/`on_status`/`web_search` 传给端口。
- `examples/petcore-mods/ai.chat/host/settings_page.py`（+225）：「深度思考」
  （模式 + 强度，强度仅在开启时显示）与「联网搜索」（开关/引擎/Key/条数/读正文）；
  Key 走端口进钥匙串，取消时控件复位，搜索关键词补齐。
- `examples/petcore-mods/ai.chat/mod.json`：版本 1.2.0 → 1.3.0（新增思考/联网设置与运行时接线）。
- 测试：`test_petcore_screenshot.py`（+38/−2）、`test_petcore_screen_ask.py`
  （+14/−1）、`test_petcore_api_chat.py`（+212/−2）、`test_petcore_websearch.py`
  （+150，新）、`test_petcore_chat_ui.py`（+48）、`test_petcore_ai_mod.py`（+145）。
- 文档：`PETCORE-SPEC.md` §20、`PETCORE-MAIN-PARITY-BACKLOG.md` AI/截图两行、
  `petcore/AGENTS.md` 四条红线、`PR-REPORT-PETCORE-P7-THINKING-SEARCH-2026-10-22.md`。

**验证**

- 全量门禁：`pytest tests/test_petcore_*.py tests/test_architecture.py
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **1114 passed in 71.69s**。
- `ruff check pet/ tests/ petcore/ examples/petcore-mods/ai.chat` → 全绿。
- `python -m petcore --check --out .scratch/p7-check.json` → exit 0，
  `version 0.1.0`、`diagnostics []`、`self_talk_images` 24/24 可读。
- 真实桌面抓屏（非 offscreen）：`screen TM140VDXP02 1280×800 dpr1.5` →
  `QImage dpr1.0 1920×1200`；覆盖层 `paint ok, sample #1d1f26`（桌面深色，非灰底）。
- 真实联网：百度免 Key 搜索 0.83s / 3 条；DuckDuckGo 40.80s 后由百度兜底。
- 性能：抓屏中位 49.1ms（n=5）、覆盖层绘制 4.22ms（n=20）、
  `_extract_delta` 1.0µs（n=20000）、`build_payload` 0.6µs（n=5000）。

**未验证 / 边界**

- 真实 DeepSeek 思考模型与博查/Tavily 检索未跑（无 Key，未消耗用户额度）。
- 真实桌面拖选只验证了抓帧与绘制，拖拽交互由 offscreen 事件测试覆盖。
- HDR 屏冻结帧仍走 Qt `grabWindow`，未移植 DXGI FP16（可能发灰）。
- 思考/联网设置是全局键（同 `ai_model`/`ai_temperature`），不是主分支的 per-provider。

## L042 · 2026-10-22 · 截图动作条（OCR 归 mod）+ 快速对话气泡

**范围**：把截图提问补成主分支的四个动作，并按「业务在 mod、core 只留端口与窗口」
的口径加入快速对话气泡。

**改动**

- `petcore/contracts/screen.py`（+54/−2）：`ACTION_*`、`RegionPick`、
  `ScreenPort.capture_region(ai_available=)`、`ScreenAskPort.open_action/on_action
  (priority, actions)`。
- `petcore/contracts/chat.py`（+25）：`QuickChatPort`。
- `petcore/contracts/host.py`（+9/−1）：`ResourcesPort`、`HostPorts.resources/
  quick_chat`。
- `petcore/ui/screen/overlay.py`（+69/−14）：四动作条、capabilities/reasons、
  `accepted(action, rect)`、Enter 默认动作（ocr→ask→copy）。
- `petcore/ui/screen/selection.py`（+60/−11）：返回 `RegionPick`、`copy` 写剪贴板、
  兼容旧单参数 accepted。
- `petcore/ui/screen/controller.py`（+148/−1）：`on_action` 注册表、
  `supports_action`、`open_action` 后台调度与 generation 校验。
- `petcore/ui/screen/ask_window.py`（+6/−2）：`start(chip=)`、`status_text()`。
- `petcore/ui/chat/quick.py`（+286，新）：快速对话气泡（标题/状态/Markdown/输入/
  去聊天窗/贴桌宠定位与 40ms 跟随）。
- `petcore/ui/chat/quick_controller.py`（+238，新）：按 `(owner, slot)` 隔离、
  排队信号、共用会话。
- `petcore/ui/chat/controller.py`（+14/−6）：`append_to_session()`。
- `petcore/ui/bubble.py`（+12/−1）：`clicked` 信号 + 内部 QLabel 透传鼠标。
- `petcore/ui/pet_window.py`（+7）：气泡点击 → `host.open_quick_chat(slot)`。
- `petcore/ui/app.py`（+13/−1）：`QuickChatController` 与 `open_quick_chat()`。
- `petcore/ui/ports.py`（+42/−2）：`ResourcesAdapter`、能力表、`quick_chat`。
- `examples/petcore-mods/tool.ocr/`（+291，新）：本地 OCR（rapidocr、显式
  onnxruntime session、模型来自 `resources/rapidocr_models`、失败回退 AI）。
- `examples/petcore-mods/ai.chat/host/prompts.py`（+44）：OCR/翻译消息与目标语言。
- `examples/petcore-mods/ai.chat/host/runtime.py`（+149/−2）：`RegionPick` 分派、
  `_on_action`、快速对话提交与流式。
- `examples/petcore-mods/ai.chat/host/constants.py`（+3）：`QUICK_HISTORY`。
- `examples/petcore-mods/ai.chat/mod.json`（+1/−1）：1.3.0 → 1.4.0。
- `packaging/petcore.iss`（+3）：`mod_ocr` 任务与 `tool.ocr` 文件。
- `scripts/build_petcore.ps1`（+18）：rapidocr/模型进包。
- 测试：`test_petcore_screen_ask.py`（+83/−15）、`test_petcore_screen_actions.py`
  （+128，新）、`test_petcore_quick_chat.py`（+188，新）、`test_petcore_ocr_mod.py`
  （+163，新）、`test_petcore_ai_mod.py`（+131/−3）、`test_petcore_example_mods.py`
  与 `test_petcore_installer.py`（+11/−2）。
- 文档：`PETCORE-SPEC.md` §21、`PETCORE-MAIN-PARITY-BACKLOG.md` AI/截图两行、
  `petcore/AGENTS.md` 五条红线、P8 PR 报告。

**验证**

- 全量门禁：`pytest tests/test_petcore_*.py tests/test_architecture.py -q`
  → **1153 passed in 89.74s**；`ruff` 全绿；`python -m petcore --check` exit 0。
- 真实本地 OCR：`HELLO 123` 冷启动 **1954ms**、暖 **791ms**、进程 RSS **145MB**。
- 动作调度：priority 回退、原文传递、异常降级、迟到结果丢弃均有测试。
- 打包与静默安装：setup **257,472,704 字节**、签名 Valid；安装目录 733MB；
  静默安装 exit 0，`--check` 显示 `ai.chat 1.4.0` / `tool.ocr 1.0.0` 均 enabled、
  `diagnostics []`；`{app}\mods\tool.ocr\.trusted` 存在，应用已重启。

**未验证 / 边界**

- rapidocr/onnxruntime/cv2 随 exe 打包（体积显著增大）；不装 `tool.ocr` 时功能
  不启用，但依赖仍在包里。
- OCR 引擎常驻进程内（约 145MB），与主分支「一次一个子进程」不同。
- 真实桌面动作条点击的肉眼验收、混合 DPI 下的快速气泡定位未实机确认。
- 主动识屏未做。

## L043 · 2026-10-22 · 截图动作条文字对比度

**范围**：用户反馈四动作条里「提取文字/翻译/复制图像」文字发白，与浅色条混在一起。

**根因**：覆盖层是 Tool 窗口，按钮未显式指定 `color`，深色系统主题下继承白色
`ButtonText`；浅色条 + 白字 = 看不清。禁用态用的 `rgba(29,33,41,90)` 也偏淡。

**改动**

- `petcore/ui/screen/overlay.py`（+13/−9）：条内所有 `QPushButton` 显式
  `color: #1d2129`；禁用态 `#8a8f99`（不透明灰）；问问肥鱼禁用态提亮为
  `rgba(255,255,255,210)`；条背景提高到 250 不透明度、边框加深到 70。
- `tests/test_petcore_screen_ask.py`（+46）：新增 QSS 断言与「深色 palette 下
  按钮文字仍是深色」的像素级回归（对照组把颜色换成白色后深色像素显著减少）。

**验证**

- `pytest tests/test_petcore_screen_ask.py -q` → **29 passed**；`ruff` 通过。
- 像素回归：深色 palette 下「翻译」按钮矩形内深色像素 > 10；改回白字后 < 5。
- 重建签名 setup（257,472,704 字节）并静默升级 `E:\dsh-pet-core`（exit 0）；
  安装后 `--check`：`ai.chat 1.4.0` / `tool.ocr 1.0.0` enabled、`diagnostics []`；
  像素回归覆盖真实渲染路径，真实桌面目视由用户确认。

**未验证 / 边界**

- 仅覆盖浅色操作条 + 深色系统主题这一组合；如果以后做深色操作条，需要重新配文字色。

## L044 · 2026-10-22 · AI 对话模块分布与 core 占用盘点

**范围**：回答「AI 对话代码分布 / 对 core 有没有占用」，并把这批事实写进架构文档。

**改动**

- `docs/PETCORE-ARCHITECTURE.md`（+113）：新增 §23——core/mod 代码表（行数）、
  core 里明确没有的业务、实测内存/导入成本（启动 +7.1MB/63.5ms、传输层首次
  对话 +6.4MB/77.9ms、快速气泡 +1.8MB、对话窗 +4.9MB、OCR 引擎 +145MB）、
  四项已知耦合与结论。
- `docs/PETCORE-SPEC.md`（+15）：新增 §22 摘要并指向 §23。
- 无代码改动（纯文档批次）。

**验证**

- 行数：`wc -l` / `git diff --numstat` 口径。
- 占用：`QT_QPA_PLATFORM=offscreen` 单次采样（psutil RSS + `perf_counter`），
  数值与 P8 报告的 OCR 145MB 一致。
- `grep` 确认 core 无 `ocr_messages`/提示词实现，唯一用户向文案是
  `api/chat.py` 的 `ChatTruncated`。

**未验证 / 边界**

- 内存是单次采样，不是多次中位数；真实桌面与混合 DPI 下数值会有差异。
- 若以后把 `ChatController` 改成首次使用时惰性创建，启动的 7.1MB/63.5ms 还能再降。

## L045 · 2026-10-22 · P4-a 通用取数端口 + 天气 + 文件解读

**范围**：`PETCORE-HANDOFF-PLAN` §P4 的第一段。Core 只加一条 `HttpPort` 与四个
`weather_*`/`file_reader_*` 配置键；两个业务域都以 `examples/petcore-mods/` 的
host-only feature 落地，默认不装。

**改动**（`git diff --numstat` 口径）

- `petcore/contracts/http.py`（新，110）：`HttpRequest/HttpResponse/HttpError`、
  `HttpPort`。`params` 由 core 编码；`prefer_direct` / `retry_statuses` / `max_bytes`。
- `petcore/net/http.py`（+135）：`build_request`、`fetch_url`——单请求显式路由、
  两次尝试共享 deadline、只在传输失败或 500/502/504 换路由、按块读取带体积上限，
  **不改写**进程级「固定直连」结论；`net/__init__.py` 导出两者。
- `petcore/ui/ports.py`（+70）：`CoreHttpPort`（`request/get_json`），
  `build_ports` 装配 `HostPorts.http`；`contracts/host.py` 增字段；
  `ui/app.py` 保存 `self.ports` 供设置页取用。
- `petcore/config.py`（+40）：`weather_enabled/weather_city/weather_city_list/
  weather_city_codes`、`file_reader_enabled/file_reader_progress_seconds/
  file_reader_record`，全部全局键 + 归一化。
- `petcore/contracts/capabilities.py`（+1）：新增 `files.read`（读取用户拖入的文本文件）。
- `petcore/ui/icons.py`（+3）：菜单/设置页的 `weather` 图标。
- `examples/petcore-mods/tool.weather/`（新，971）：`logic.py`（城市名/地区码/两源解析/
  WMO 与 Beaufort 码表/失败文案）、`client.py`（CN 直连 → open-meteo 代理，6s/请求、
  15s 总预算）、`runtime.py`（后台线程 + 气泡）、`settings_page.py`（启用/城市列表/
  当前城市/立即查看）、`host/__init__.py`、`mod.json`。
- `examples/petcore-mods/tool.file-reader/`（新，502）：`reader.py`（后缀白名单、
  20000 文件/2s 扫描预算、200000 字符有界读取）、`runtime.py`（`interaction.on_drop`
  → 后台 `api.stream_chat` → 气泡 + `ChatPort.record`）、`settings_page.py`。
- `tests/test_petcore_http_port.py`（新，312）、`tests/test_petcore_weather_mod.py`
  （新，338）、`tests/test_petcore_file_reader_mod.py`（新，314）。
- `tests/test_petcore_example_mods.py`（+2）、`tests/test_petcore_installer.py`（+5/-1）：
  新包进可加载清单与安装器任务断言。
- `packaging/petcore.iss`（+6）：`mod_weather` / `mod_filereader`，`Flags: unchecked`，
  `{app}\mods\<id>` + `.trusted`。
- 文档：`PETCORE-SPEC.md` §23、`PETCORE-ROADMAP.md` §23、`PETCORE-MOD-FORMAT.md` §11、
  `PETCORE-ARCHITECTURE.md` §14/§16/§17、`PETCORE-MAIN-PARITY-BACKLOG.md` §3.2/§2/§11、
  `examples/petcore-mods/README.md`、`petcore/AGENTS.md` 四条红线。

**行为变化与理由**

- 天气：国内源直连（本机实测代理慢 7~11 倍，主分支 `docs/NETWORK-PROXY-AND-VPN-2026-09-22.md`
  的结论）、海外源跟随系统代理；失败点名两源，不静默。城市名存储不剥后缀
  （剥离不幂等），只在查询期做变体匹配。
- 文件解读：只读文本类文件，绝不改/移/删；扫描与字符都有硬预算；结果默认进会话，
  可关；菜单提供「解读刚才拖入的文件」，对应主分支没有菜单入口的缺口。
- `files.read` 是新增能力声明；能力仍只是声明 + 用户授权，不是沙箱。

**验证**

- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py -q`
  → **881 passed**。本段新增测试 **50 条**（`test_petcore_http_port.py` 17、
  `test_petcore_weather_mod.py` 18、`test_petcore_file_reader_mod.py` 15）。
- `.venv/Scripts/ruff check petcore/... examples/petcore-mods/tool.* tests/test_petcore_*`
  → All checks passed。
- 真实取数（本机，`CoreHttpPort`）：鹿城 0.26s、北京 0.24s、open-meteo 上海 4.51s、
  不存在城市 1.86s 且两源原因都出现。
- `python -m pytest tests/test_petcore_example_mods.py tests/test_petcore_installer.py
  tests/test_petcore_architecture.py tests/test_petcore_settings_coverage.py -q` → 通过。

**未验证 / 边界**

- 天气「明天」与逐城市子菜单未做：主分支右键也只有「显示天气」，逐城市需要 mod 动态
  子菜单端口，留 P4-c 菜单模板批次一起评估。
- 冻结包已重建并静默安装到 `E:\dsh-pet-core`（setup 257,488,664 字节、签名有效）；
  `--check`（安装版 exe + 临时 `--root`）显示两个新 mod `enabled=True`、`diagnostics []`，
  安装后进程存活（PID 23652，RSS 98.9 MB）。真实桌面上的「点菜单查天气 / 拖文件解读」
  需要在用户使用时观察日志，自动化只覆盖到离屏与端口层。
- 文件解读依赖 Core 的 `file_feeding_enabled`（关闭时不会收到 drop 事件），已在
  MOD-FORMAT §8 写明。
- 两个 mod 的设置页只做了离屏测试，真实窗口在 900×620 / 125% DPI 下未实机对照。

## L046 · 2026-10-22 · P4-b 语音端口 + 报时 + 音乐歌词 + 动画循环

**范围**：`PETCORE-HANDOFF-PLAN` §P4 第二段。Core 新增 `SpeechPort`（合成/缓存/预检/
密钥在 core）与动画循环接缝；`voice.chime` 重写、`media.music` 从「媒体键」升级为
Now Playing + 歌词 + 唱跳。两个 mod 仍是可导入包（安装向导默认不勾）。

**改动**（`git diff --cached --numstat` 口径）

- `petcore/contracts/speech.py`（新，111）：`SpeechRequest/SpeechResult/
  SpeechProviderInfo/SpeechError/SpeechPort`，7 类失败 reason。
- `petcore/net/tts.py`（新，603）：edge-tts(WSS)、豆包 SSE、MiMo(OpenAI 兼容)、
  `PROVIDER_SPECS`/`DEFAULT_VOICES`；第三方网络栈只在这里 import。
- `petcore/speech/{__init__,cache,service}.py`（新，13/112/341）：后端链、无网预检、
  非空缓存、2 次重试 + 默认音色兜底、失败删产物、按 mtime 裁剪缓存。
- `petcore/platform/sapi.py`（新，212）：Windows SAPI5（ctypes COM + 线程级 CoInitialize）。
- `petcore/contracts/host.py`（+4/-1）：`PresentationPort.play_animation(loop=)` /
  `release_loop()`、`HostPorts.speech`。
- `petcore/ui/ports.py`（+132/-2）：`CoreSpeechPort`（后台合成 → 共享 `AudioAdapter` →
  回调，`stop/playing`），`build_ports` 装配。
- `petcore/ui/pet_window.py`（+19/-1）：`_loop_active`；`_play_spec()` 唯一清除点；
  `_on_finished()` 在探头/击飞/拖拽接管时解除循环；`release_loop()`。
- `petcore/ui/app.py`（+11/-2）：`_PresentationAdapter` 转发 loop/release；
  `CoreHost.speech = SpeechService(...)`（惰性 import）。
- `petcore/config.py`（+176）：`speech_*` 8 键、`voice_chime_*` 11 键、`music_*` 10 键，
  全部全局作用域 + 归一化（日程白名单、`HH:MM` 清洗、速率/音量夹取、播放器路径清理）。
- `examples/petcore-mods/voice.chime/`（1.1.0）：删除旧 `factory.py`（-134），新增
  `schedule.py`/`quotes.py`/`runtime.py`/`settings_page.py`/`host/__init__.py`；
  运行时无 PySide6。
- `examples/petcore-mods/media.music/`（1.1.0）：`now_playing.py`(450)/`lyrics.py`(519)/
  `players.py`(74)/`runtime.py`(496)/`settings_page.py`(376)/`host/__init__.py`，
  `factory.py` 变包入口 shim（+38/-140）。
- `tests/test_petcore_speech.py`（464 / 16）、`tests/test_petcore_chime_mod.py`
  （478 / 25）、`tests/test_petcore_music_mod.py`（683 / 29）、
  `tests/test_petcore_interaction.py`（+54 / 3 条循环接缝）。
- `petcore/cli.py`（+34）：`--check` 新增 `speech` 字段（backend/fallback/cache_dir/
  providers 可用性），冻结包是否真带 edge-tts/winrt/pycaw 的第一证据。
- `scripts/build_petcore.ps1`（+8/-1）：收集 `edge_tts`、`winrt.windows.media.*`、`pycaw`。
- 文档：SPEC §24、ROADMAP §24、MOD-FORMAT §12、ARCHITECTURE §14、ANIMATION-BACKLOG、
  parity backlog §2/§3.2/§4、examples README、`petcore/AGENTS.md` 三条红线。

**行为变化与理由**

- 合成与传输归 core：`voice.chime` 不再 `import QTextToSpeech`，四家后端共享缓存与
  失败兜底；密钥只进钥匙串（owner `speech.<provider>`）。
- 缓存命中要求非空文件：0 字节产物在边缘 TTS 上曾造成「永久静音」。
- 唱跳用循环接缝：`play_animation(loop=True)` + `release_loop()`，探头/击飞/拖拽
  接管时自动解除，不绕既有素材闸门。
- 歌词直连优先、最多切一次代理（同一 deadline，仅传输失败或 500/502/504，
  带 `Retry-After` 不切）；不重试、不落盘音频、不记录 URL/代理/密钥。

**验证**

- 全量门禁：`pytest tests/test_petcore_*.py tests/test_architecture.py
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q` → **1282 passed**；
  `ruff check pet/ tests/ petcore/ examples/petcore-mods` 全绿；
  `python -m petcore --check` 退出码 0。
- 新增测试 74 条（speech 17 / chime 25 / music 29 / loop 3）。
- 真实合成（子代理实测）：edge 26,208 B / 3.39s，缓存命中 0.0s；SAPI 97,234 B wav；
  `speech_backend="sapi"` 118,834 B、缓存命中 0.25s。
- 真实合成（新配置 + `SpeechService` 复测）：providers `edge=True/sapi=True/
  doubao=False/mimo=False`（无 Key）；edge 20,304 B / 2.99s，二次命中 0.000s。
- 真实歌词：`CoreHttpPort` 抓到 33 行（酷狗源，0.66s，网易云只给翻唱被拒后回退）。
- SMTC：本机无播放器时 47ms 返回「系统里没有正在播放的媒体会话」；transport 命令给明确原因。
- 性能（单次采样）：`import petcore.net.tts` +5.3MB/46.6ms（首次合成才加载）；
  `petcore.speech.service` +1.9MB/9.1ms；`SpeechService()` +0.0MB/0.0ms；
  加载 `voice.chime` 包 +14.5MB/86.3ms（含设置页 Qt 控件，仅安装并启用时）。
- 冻结包：setup 258,499,016 B、签名有效；静默安装 exit 0；安装版 `--check`
  `diagnostics []`、`voice.chime`/`media.music` 均 1.1.0 enabled、
  `speech.providers` edge/sapi Available、doubao/mimo `auth`；安装后进程存活
  （PID 20528，RSS 108.6 MB）。冻结包内真实发声未点过（留用户验收）。

**未验证 / 边界**

- 真实播放器下的唱跳与逐行歌词同步未验证（本机没有正在播放的会话）。
- 豆包/MiMo 真实合成本机无 Key；两者报 `auth`，错误分类与字段已测。
- 豆包音调（pitch）未移植 ffmpeg `asetrate` 链，`pitch` 字段对豆包无效（其余后端生效）。
- 口型主分支也未实现，不在本轮。
- 循环解除后会等当前这圈播完才回行为链（最长一个 clip 时长），不是硬切。
- `voice.chime` 的预缓存线程是 daemon、`stop()` 不 join（阻塞的网络合成不能拖住退出）。

## L047 · 2026-10-23 · P4-b2 扩展分组 / 可卸载 / 气泡分页 / 音乐识别

**范围**：Core UI（settings base/style、menu model、bubble、app、page_mods、page_extensions、mods install/state/feature、contracts、config、installer）+ 9 个示例 mod 设置页 + 测试与文档。

**改了什么**

- `petcore/ui/settings/base.py`：新增 `group_heading()`（H2）与 `section(..., level=3)`（H3），H3 卡片左缩进 12px。
- `petcore/ui/settings/style.py`：新增 `QLabel#groupTitle` / `QLabel#subsectionTitle`。
- 7 个示例 mod 的设置页（ai.chat / fun.divination / fun.festival / reminder.todo / tool.file-reader / tool.weather / voice.chime）：一个 H2 + 原分组降为 H3。
- `media.music` 设置页：H2「音乐」+ H3「播放与唱歌 / 歌词显示 / 识别范围 / 切歌与播放控制 / 播放器」，新增过滤开关、额外识别名、四个传输按钮，检测结果显示 `app_id`。
- `petcore/ui/menu_model.py`：`_populate_extensions()` 按 owner 分组；新增 `set_owner_labels()` 与 `set_extension_skip_owners()`；`petcore/ui/app.py` 从 manifest 取 `name_zh` 并跳过 Core 内置特性。
- `petcore/mods/install.py`：新增 `read_install_files()`、`_remove_listed()`、`remove_at()`；按 `install.json` 清单删除，`__pycache__/*.pyc` 一并清，未登记文件保留并报数量；无清单的 `.trusted` 包整目录删除（仍做边界与 `mod.json` 校验）。
- `petcore/mods/state.py`：新增 `clear()`；`petcore/mods/feature.py`：新增 `stop_owner()`。
- `petcore/ui/app.py`：新增 `CoreHost.uninstall_mod()` 与 `_drop_modules_under()`；UI 卸载顺序为「停 runtime → 撤菜单 → 清模块 → 删文件 → 重扫」。
- `petcore/ui/settings/page_mods.py`：trusted 包不再禁用卸载，确认文案说明保留个人数据；删除请求交给 `ExtensionsPage.uninstall_mod()`。
- `petcore/ui/settings/page_extensions.py`：新增 `uninstall_mod()` / `_drop_page()`，删除前对未保存的设置页询问保存/放弃/取消。
- `petcore/ui/bubble.py`：列宽 `248→360`（`column_for_text`）、`paginate_text()`、页码点、滚轮翻页、副标题与正文同 `bubblePanel`；高度按屏幕夹取。
- `petcore/contracts/host.py`、`ui/app.py`、`ui/ports.py`、`ui/pet_window.py`：`say()` 透传 `subtitle`。
- `examples/petcore-mods/media.music`：`allowed_app_ids()` + `accepts_singing/pick_singing_session/transport` 的 `allowed_ids`；`music_filter_enabled` / `music_filter_extra_ids` 两键；歌词气泡副标题「我在唱《…》」，纯音乐「正在听《…》」。
- `petcore/config.py`：两键进 GLOBAL/DEFAULTS/归一化。
- `packaging/petcore.iss`：新增 `[UninstallDelete] {app}\mods`。
- 文档：SPEC §25、ROADMAP §25、MOD-FORMAT §13、parity §12、AGENTS 红线、INDEX/LOG。

**验证**：`ruff check pet/ tests/ petcore/ examples/petcore-mods` 全绿；petcore 全量门禁与实机记录见 `docs/PR-REPORT-PETCORE-P4B2-2026-10-23.md`。

**未验证 / 风险**：真实播放器下的识别范围过滤（本机无播放器）；安装版卸载（构建后复验）；Python 模块不热重载，卸载后仍需重启才彻底释放；`__pycache__` 保留在用户包目录时会被当作生成物删除。

## L048 · 2026-10-23 · P4-b2.1 菜单分组落地 / 设置宽行 / 气泡显式尺寸

**范围**：`petcore/ui/menu_model.py`、`menu_layout.py`、`petcore/ui/app.py`、`petcore/ui/settings/base.py`、`petcore/ui/bubble.py` + 测试与文档。

**改了什么**

- 菜单分组：`MenuModel._append_node()` 对 `extensions_hub` 不再平铺 children，只把 children 的 id 作为 `allowed` 传给 `_populate_extensions()`；`allowed` 为空时回退全部可见项，避免旧 layout 把扩展菜单变成空。
- 旧 layout 迁移：新增 `migrate_p10_menu()`，把模板放在 hub 之外的 Core action（links / 快捷启动 / 网络信息 / 回收内存 / 免打扰）从 `extensions_hub` 搬回模板位置；`reload_menu()` 在 p8/p9 之后调用并持久化，幂等。
- 内置包名：`_register_feature_menus()` 对不在 loader 结果里的内置接缝包补读 manifest 的 `name_zh`，扩展菜单不再显示 `core.feature-demo`。
- 设置宽行：`SettingsCard.add_row(expand=True)` 改为纵向布局（文字块整行、控件另起一行）；非 expand 行的文字块包成 `settingTextBlock`，最小宽 180px。
- 气泡：`label.setWordWrap(False)` + `QFontMetrics` 显式算宽高（最长行 + 4px，下限 96；行数 × lineSpacing + 2），`setFixedSize()`；副标题同宽并 `heightForWidth()`；图片说明改固定宽 + 按宽算高；`show_text()` 在 `show()` 后再 `adjustSize()+_place()` 一次，消除「慢一句」；分页末页孤行从前页借一行。

**验证**：`ruff` 全绿；聚焦 348 passed（含 docs）；全量 1302 passed；`python -m petcore --check` exit 0。离线复现探针从「4 字 26×13 / hfw 28」变为「96×17 / hfw 17」，5/10 字均单行，长文 8 页 0 条超宽行。安装包复验见 PR 报告「第二轮修正」。

**未验证 / 风险**：真实桌面右键菜单截图（需启动安装版人工确认）；迁移会改写用户 layout 中 Core 项的位置（只搬模板明确放在 hub 之外的项，幂等）；`allowed` 为空时回退全部可见项，用户「隐藏所有 mod 项」的极端情况会重新出现。

## L049 · 2026-10-23 · 设置窗口标题栏最小化/最大化

**范围**：`petcore/ui/settings/dialog.py`、`tests/test_petcore_settings.py` + 文档。

**改了什么**：`SettingsDialog.__init__` 在原生旗标上补 `WindowMinMaxButtonsHint`，标题栏出现最小化/最大化按钮；非模态、X 保存、取消/Esc 回滚、Enter 保存的语义不变；最大化/还原由系统处理，首次显示仍按宠物位置放置。

**验证**：`test_settings_dialog_has_minimize_and_maximize` 断言旗标含 MinMax/Close、非模态，并真实走 `showMinimized/showMaximized/showNormal` 状态；真实桌面抓图确认「— / □ / ×」三个原生按钮（`.scratch/settings-minmax.png`）；聚焦 settings 族与全量 1303 passed。

**环境限制**：新 setup 在本机被 Smart App Control 拦截（签名有效、CodeIntegrity 3077/3118），改用 `dist/dsh-pet-core` 覆盖安装目录部署并 `--check` 通过。

## L050 · 2026-10-23 · P4-c1 窗口级抓屏 + ai.chat 主动识屏

**范围**：`petcore/platform/{foreground,screenshot,image_hash}.py`、
`petcore/contracts/{screen,host}.py`、`petcore/ui/ports.py`、`petcore/config.py`、
`petcore/menu_templates/petcore-default-v1.json`、`petcore/ui/menu_layout.py`、
`examples/petcore-mods/ai.chat/host/{proactive,runtime,settings_page,__init__}.py`、
测试 4 个文件 + 新增 `tests/test_petcore_proactive.py` + 四份文档。

**改了什么**（`git diff --numstat`，含新增文件）：

- `petcore/platform/foreground.py` +98/−4：`foreground_window_info()` 补 `hwnd/rect`
  （DWM `EXTENDED_FRAME_BOUNDS`，失败回退 `GetWindowRect`）、`DWMWA_CLOAKED` 过滤、
  `idle_seconds()`。
- `petcore/platform/image_hash.py`（新增 60 行）：9×8 差分哈希 + Hamming；先缩放
  再转灰度（1200×800：9.87 ms → 1.58 ms），平滑重采样避免采样抖动造假差异。
- `petcore/platform/screenshot.py` +150/−1：Windows 上用 GDI `BitBlt` / `StretchBlt`
  按窗口**物理像素矩形**直接抓（`_grab_desktop_rect`），不再做逻辑/物理换算——
  150% 缩放下「Qt 逻辑几何 + DPR 裁剪」实测会 100% 失败。两段式：
  `sample_window()`（192 边缩略图 → 指纹，不编码 PNG）与 `capture_window()`
  （768 边 + PNG + `dh_hash`）；窗口大半在屏外判 `outside_screen`；`grabber=`
  只给测试注入。
- `petcore/contracts/screen.py` +31：`ScreenCapture.hwnd/dh_hash`、`WindowInfo`、
  `ScreenPort.foreground_window()/capture_foreground()`（docstring 写明双复核与内存语义）。
- `petcore/contracts/host.py` +11/−1：`SystemPort.idle_seconds()`、`ConfigPort.set()`
  （只给显式用户动作）。
- `petcore/ui/ports.py` +65/−1：`QtScreenPort` 两个窗口采样方法（前后各查前台
  `hwnd`）、新 `SystemAdapter` 并接进 `build_ports(system=...)`、`QtConfigPort.set()`
  写全局配置并落盘。
- `petcore/config.py` +64：12 个 `ai_proactive_*` 键（默认值/钳制/白名单 50 条 ×120 字）
  全部进 `GLOBAL_CONFIG_KEYS`。
- `petcore/menu_templates/petcore-default-v1.json` +1、`petcore/ui/menu_layout.py` +1：
  在 `look_screen` 之后加 `ai.chat:proactive` 节点。旧布局不需要单独的迁移函数：
  `_merge_template_actions()` 已按模板补注册项并写回（诊断
  `default-action-added:ai.chat:proactive`），幂等。
- `examples/petcore-mods/ai.chat/host/proactive.py`（新增 470 行）：白名单/停留/
  `ProactiveLimiter`（状态文件原子写、日上限/间隔/冷却/3 次失败熔断）/
  `ProactiveWatcher`（8 s 心跳、每 tick 现读配置、代次作废迟到回调、dry-run、
  请求 180 s 不回调则自愈清忙碌）。
- `ai.chat/host/runtime.py` +71/−17：命令 `proactive_toggle`、`proactive_cue/ask/answer`、
  `_start_vision(on_fail=)`、`_record_look()` 复用；`start/stop` 接管看门狗。
- `ai.chat/host/settings_page.py` +327/−1：「主动识屏」H3 分节（12 键 + 从当前前台
  窗口添加，按软件/按标题二选一）、`_sync_proactive()` 取消回滚、搜索关键词。
- `ai.chat/host/__init__.py` +22/−1：菜单贡献 `proactive`（`checked` 读配置）。
- 测试：`test_petcore_proactive.py`（新增 17 条）、`test_petcore_screenshot.py`
  （dHash/裁剪/裁剪越界 +6）、`test_petcore_ai_mod.py`（运行时/设置页 +6）、
  `test_petcore_config_scope.py`（+2）、`test_petcore_menu_layout.py`（+2，并更新
  模板顺序断言）。

**行为变化**：右键多一个「主动识屏」勾选项（默认关；`ai.chat` 未安装时不存在）；
设置 →「AI 对话」多一个「主动识屏」分节；开关走 `ConfigPort.set` 立即落盘。默认
不工作——白名单为空即不触发。答复只冒气泡，`ai_proactive_sync_chat` 为真时静默写
会话，绝不打开对话窗。

**验证**：

- `ruff check pet/ tests/ petcore/ examples/petcore-mods`：All checks passed。
- 全量门禁：`pytest tests/test_petcore_*.py tests/test_architecture.py
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q` →
  **1345 passed, 1 skipped**。唯一 skip 是 `tool.ocr` 的真实引擎用例：本机 Smart App
  Control（`VerifiedAndReputablePolicyState=1`）在 16:49 起以 WinError 4551 拦截
  `shapely/_geos*.pyd`，测试按「确切的 4551」跳过并在报告里点名，不是放宽断言。
- `python -m petcore --check` → exit 0，`diagnostics: []`，`menu_template: json`。
- 性能（本机 150% 缩放，`QT_QPA_PLATFORM=offscreen`）：
  dHash 1920×1080 中位 3.2 ms / 800×600 0.74 ms（改序前 1200×800 要 9.87 ms）；
  `sample_window` 1200×800 中位 **33.8 ms**（只缩到 192 边算指纹，不编码 PNG）；
  确认变化后的 `capture_window`（768 边 + PNG）中位 66 ms；关闭态 tick 配置读
  0.0002 ms。稳态 = 每 8 s 一次采样 ≈ 34 ms（0.42% 占空）。
- **真机发现的缺陷**：最初实现是「Qt 抓整屏 + 按 DPR 裁剪」，本机 150% 缩放
  （逻辑 1280×800 / 物理 1920×1200）下窗口矩形被二次放大，裁剪只剩 24% 直接判
  `outside_screen`——功能 100% 不工作。改为 GDI `BitBlt`/`StretchBlt` 按物理矩形
  直接抓之后，真机取到 960×1128 / 239 KB 的窗口 PNG。
- 安装/真机 dry-run 见 PR 报告 `docs/PR-REPORT-PETCORE-P4C1-2026-10-23.md` §3。

**未验证 / 风险**：

- offscreen 平台 `grabWindow` 返回空图，窗口抓图只用注入的 `FakeScreen` 验证裁剪
  数学；真实桌面抓图在安装版上人工验证。
- 混合 DPI / 负坐标副屏：按「交集最大的屏 + 物理像素比例」换算，数学上成立，
  未在真机双屏复核。
- 抓图在 GUI 线程执行（Qt `grabWindow` 不保证跨线程安全），单次 ≈18 ms；
  若后续出现拖动卡顿，考虑移到 core 的专用线程或 printwindow 方案。
- 主分支的陪伴记忆（`proactive_memory`）、免费视觉 provider、HDR 抓屏未移植，
  记入 parity backlog §13。
- **环境 blocker（已解决）**：17:00 前后本机一度以 WinError 4551 拦截未签名的
  原生扩展（`shapely/_geos*.pyd`）和新构建的 exe。用户关闭火绒相关监测后复测，
  同一份新构建可直接运行，`shapely` 也恢复正常——拦截来自第三方安全软件的驱动层，
  不是 SAC 对开发证书的硬性拒绝（`VerifiedAndReputablePolicyState` 仍为 1）。
  19:40 已用 setup 静默升级安装到 `E:\dsh-pet-core` 并跑通 `--check` 与主动识屏
  dry-run。

## L051 · 2026-10-23 · 系统缩放（DPI）适配：模型图像封顶 / 图标与缩略图物理绘制

**范围**：`petcore/contracts/screen.py`、`petcore/platform/screenshot.py`、
`petcore/ui/ports.py`、`petcore/ui/icons.py`、`petcore/ui/menu_actions.py`、
`examples/petcore-mods/ai.chat/host/runtime.py`、测试 3 个文件、SPEC §27、
MOD-FORMAT §14、`petcore/AGENTS.md`、PR 报告。

**改了什么**：

- `contracts/screen.py` +22：新常量 `VISION_MAX_EDGE = 1024` 与
  `ScreenPort.shrink_for_vision(png, max_edge=1024)`；`screenshot.shrink_png()`
  按物理像素等比缩小并重新编码，空图/坏图/未超限原样返回。
- `platform/screenshot.py` +26 / `ui/ports.py` +8：`capture_desktop()` 抓虚拟桌面
  （所有显示器并集），`QtScreenPort.capture()` 改走它——与主分支 `all_screens=True`
  对齐，多屏/混合 DPI 不再只抓宠物所在屏；`QtScreenPort.shrink_for_vision()`。
- `ai.chat/runtime.py` +25/−4：新增 `_vision_bytes()`；「看看屏幕」「主动识屏」
  「截图提问」「提取文字/翻译的 AI 兜底」四处送模型的图统一先过它。本地 OCR 与
  「复制图像」仍拿原图。
- `ui/icons.py` +40/−12：`icon()` / `file_icon()` / `icon_from_spec()` 接受 `dpr`，
  按 `screen_dpr()` 用物理尺寸绘制并写回 DPR（1x/1.5x/2x → 36/54/72 像素）。
- `ui/menu_actions.py` +18/−5：动画缩略图按 `physical_side(64, screen_dpr(window))`
  解码，回调里写回 DPR；高分屏菜单不再把 64px 小图放大。
- 测试：`test_petcore_screenshot.py`（封顶/原样返回/DPR 无关 +3）、
  `test_petcore_menu.py`（图标物理尺寸 +2）、`test_petcore_ai_mod.py`
  （视觉载荷走端口封顶 +2）。

**行为变化**：高 DPI 屏上「看看屏幕 / 截图提问」送给模型的图不再随缩放翻倍
（150% 下 1920×1200 → 1024×640，287 KB → 165 KB）；菜单图标与动画缩略图更清晰；
其它布局/位置/钳制逻辑未变（本来就是逻辑像素）。

**验证**：

- `ruff check pet/ tests/ petcore/ examples/petcore-mods`：All checks passed。
- 全量门禁 **1356 passed, 0 skipped**（上一批唯一 skip 的 OCR 真实引擎用例本机已恢复：
  用户关掉火绒相关监测后，`shapely/_geos*.pyd` 不再被 WinError 4551 拦截）。
- 真机探针（`.scratch/probe_dpi.py`，本机 150%）：屏幕逻辑 1280×800 / dpr 1.5；
  整屏 1920×1200（288 KB）→ 模型输入 1024×640（166 KB）；前台窗口 1920×1128 →
  768×451（111 KB）；框选 400×200 逻辑 → 600×300 物理。
- 菜单图标尺寸：`dpr 1.0/1.5/2.0 → availableSizes 36/54/72`（真实 Qt 断言）。
- 打包/安装：19:39 构建（exe SHA-256 `0d3169b2…c1f`、setup `37366e58…f31`，签名
  Valid），静默升级到 `E:\dsh-pet-core`；安装版隔离 APPDATA `--check` exit 0，
  dry-run 日志两条（窗口采样在冻结包内可用）。

**未验证 / 风险**：

- 菜单对勾图仍是 14px QSS 资源（Qt 对 QSS `url()` 的 @2x 支持随版本而异，未实机
  核对），高 DPI 下可能略软；不影响功能。
- 混合 DPI 多屏只做了逻辑层测试，未在真机双屏复核。
- 图片封顶是物理像素口径（与主分支一致）；若视觉模型对小字识别不稳，再考虑改成
  逻辑像素口径（成本随 DPI 上升）。

## L052 · 2026-10-23 · P4-c2：Agent 联动 `ai.agent` 扩展（只读联动）

**范围**：`petcore/contracts/host.py`、`petcore/ui/ports.py`、`petcore/ui/app.py`、
`petcore/ui/icons.py`、`petcore/config.py`、`petcore/menu_templates/petcore-default-v1.json`、
`petcore/ui/menu_layout.py`、`packaging/petcore.iss`、新包
`examples/petcore-mods/ai.agent/`（`mod.json` + `host/{__init__,constants,protocol,tailer,links,runtime,settings_page}.py`）、
新测试 `tests/test_petcore_agent_mod.py`、`tests/test_petcore_installer.py`、
`tests/test_petcore_menu_layout.py`、`examples/petcore-mods/README.md`、
`docs/PETCORE-SPEC.md` §28、`docs/PETCORE-MOD-FORMAT.md` §15、
`docs/PETCORE-ARCHITECTURE.md` §25、`docs/PETCORE-ROADMAP.md` §27、
`docs/PETCORE-MAIN-PARITY-BACKLOG.md`、`docs/AGENT_LINK_PROTOCOL.md` §7、
`petcore/AGENTS.md`、PR 报告 `PR-REPORT-PETCORE-P4C2-2026-10-23.md`。

**改动说明**

1. Core 只加三条通用接缝，不认识任何 Agent：
   - `StoragePort.data_root()`（`StorageAdapter` 返回数据根）——mod 才能定位
     `<data>/agent-events/` 与 `<data>.parent/dsh-pet-bridge/`；之前只有
     `feature-data/<owner>`。
   - `PresentationPort.visible()`（`_PresentationAdapter` 读 `window.isVisible()`）——
     隐藏态不切联动动画。
   - `PetHandle.animations()`（`PetHandleImpl` 走 `catalog.names_for(GraphType.ACT)`）——
     联动动作池按角色真实动作名挑选。
   - `ui/icons.py` 新增 `agent` 图标（菜单/设置页共用）。
2. 13 个 `ai_agent_*` 全局键（`GLOBAL_CONFIG_KEYS` + `DEFAULTS` + `_normalize`）：
   总开关/两个来源/自定义列表/动画/过程气泡/完成通知/切换间隔/音效四键；
   自定义条目清洗 `_agent_links()`（key 校验、去重、≤8、保留 `dsh` 键）。
3. `ai.agent` v1.0.0（host-only）：
   - `protocol.py`：`state` 优先、`event` 查表（Claude hooks + DSH 事件 + 裸状态名）、
     `turn/end` 带 `aborted/blocked/max_tokens/unknown` 收敛 idle、BOM/半行/4KB 上限。
   - `tailer.py`：`ByteTailer`（首次见到已存在文件跳到末尾、监视后新增文件从头读、
     单次 64KB、半行 ≤8KB、截断/轮转重读一代）、`GlobTailer`（`dsh*.jsonl`，
     启动快照判历史，≤8 文件按 mtime）。
   - `links.py`：`LinkEngine`，折叠多写者、去抖+节流、800 ms 完成确认、
     5 s 完成冷却、错误回合报「这轮好像没能跑完」、动作池 `写代码/吃Token` 交替 +
     每 3 次插播摸鱼、过程气泡 10/8/60 s、隐藏态不切动画、三档音效带冷却。
   - `runtime.py`：`Runtime` 协议（start/stop/close），单条轮询线程 1.5 s，
     配置每轮现读（含来源签名重建），解析结果经 `scheduler.call_later(0, …)` 回 GUI；
     关闭期间继续推进偏移（重新开启不回放）；`commands={"agent_toggle"}`。
   - `settings_page.py`：H2 + 5×H3（总开关 / 事件来源 / 动画与气泡 / 音效 / 诊断），
     控件改动即时写全局配置，`discard_changes()` 从打开时快照回滚，诊断面板列出
     来源目录与最近一行事件，「发送测试事件」写 demo 事件走完整链路。
   - 菜单贡献 `ai.agent:enabled`（label「Agent 联动」，`checked` 读 `ai_agent_enabled`）。
4. 菜单模板在两个副本（JSON + `BUILTIN_DEFAULT_LAYOUT`）都插在 `ai.chat:proactive`
   之后，旧布局由既有 `_merge_template_actions()` 幂等补入。
5. 安装器：`mod_agent` 任务 `Flags: unchecked`，勾选才写 `{app}\modsi.agent` + `.trusted`。
6. 已知取舍：完成态不回「待机」动画（Core 没有 `request_link_idle` 等价 API），只
   `release_loop()`；一次性动作播完由行为链自然接管。

**验证**

- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **1426 passed**（基线 1356，新增 70）。
- `.venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods/` → All checks passed。
- `.venv/Scripts/python -m petcore --check` → exit 0，`menu_template=json`。
- 隔离 root 安装冒烟：`--root .scratch/agent-root --portable mods install examples/petcore-mods/ai.agent`
  → 装好后 `allow_feature_mods=false` 时如实报 `ai.agent: feature mods disabled`；
  打开 `allow_feature_mods` 后 `mods=[ai.agent 1.0.0 enabled]`、`diagnostics: []`。
- 源码树端到端（真实 `Config` + 真实 `QtScheduler` + 真实文件 + 真实 mod 包，offscreen，
  `.scratch/probe_agent_e2e.py`）：三条事件（`UserPromptSubmit` / `PreToolUse(bash)` / `idle`）
  → `animations=['写代码']`、`bubbles=[('正在跑命令', False), ('干完活啦', True)]`、
  `states={'demo': 'idle'}`。`thinking→working` 间隔 1 s 被 2 s 节流，只切一次动作（预期）。
- 开销（`.scratch/probe_agent.py`）：`parse_line` 2.86 µs/行、`LinkEngine.handle` 4.19 µs/事件、
  追加 10 行的 tail 读取 0.18 ms、loader 导入 95 ms（启动一次性）。
- 真机 GUI 冒烟（`--root .scratch/agent-root --portable --allow-feature-mods --verbose`，
  15 秒后 kill）：四条事件全部按 `state=thinking → working → working → idle` 落到日志，
  无异常、无 `animations() failed`。**这一轮抓到两个只在真机才暴露的问题**：
  ① `_log(level=…)` 参数不存在（单元测试用替身 ctx 没调这条路径）；
  ② `PetHandleImpl.animations()` 用了不存在的 `GraphType.ACT`——异常被端口吞掉后
     mod 拿到空动作池，联动永远不切动作。两处都已修，并补 `test_pet_handle_animations_*
     use_the_act_graph` 两条回归（用真实 `GraphCatalog`）。

**未验证 / 风险**

- 未在真实 DSH 会话下长时间跑（本机桥接目录是否存在取决于用户是否装过桥接插件）；
  诊断面板会如实显示「目录缺失」。
- 未真机验收音效三档（需要勾选音效并触发一次完成/报错）。
- 未做写方安装（DSH 插件 / Claude hooks / Cursor / OpenCode 直读）、审批卡片、成本统计，
  见 ROADMAP §27「未做（c2.1）」。
- 打包/签名未重跑（本批次只改源码树与 iss）。

## L053 · 2026-10-23 · P5-a1：灵动岛 v1（胶囊 + 3 段 + 展开卡片）

**范围**：新增 `petcore/island/{__init__,segments,layout}.py`、
`petcore/platform/{sysmon,netmon}.py`、`petcore/ui/island.py`；改
`petcore/config.py`、`petcore/ui/{app,pet_window,menu_actions}.py`、
`petcore/ui/settings/{pages_core,coverage}.py`、
`petcore/menu_templates/petcore-default-v1.json`、`petcore/ui/menu_layout.py`；
新增测试 `tests/test_petcore_island_{segments,layout,sampling,window}.py`；
文档 SPEC §29、ARCHITECTURE §26、ROADMAP §28、parity、function matrix、
`petcore/AGENTS.md`、本 log + 索引、PR 报告 `PR-REPORT-PETCORE-ISLAND-2026-10-23.md`。

**改动说明**

1. **零 Qt 契约**（`island/segments.py`）：直接从主分支 `pet/island_segments.py`
   移植宿主侧那半（状态词表、`SegmentSnapshot`、盒宽自测量 + 字体指纹缓存、
   字段盒右省略护栏、`split_value_unit`、四态 `render_compact`、两级告警 + 3pt 滞回、
   `highest_severity`），砍掉第三方注册面（`SegmentDeclaration`/`register_segment`/
   `seed_thresholds`/`drop_thresholds`）。主分支同名单测 40 条原样移植、全绿。
2. **零 Qt 布局**（`island/layout.py`）：移植 `_InfoSeg`/`_SegPlacement`/
   `place_info_segments`（19px 槽位、竖线、双盒单位）、`elide_to_width`、
   `plan_info_row`（名字省略→隐藏→尾部折 `+N`→保底）、`apply_shrink`（按 id 折、
   chip 告警取当刻最高级）、`chip_segment`、`anchored_x`（三分区锚点）。
   差异：`_NETWORK_BOX_SAMPLE` 改成读 `netmon.NETWORK_BOX_SAMPLE`（本批网络段无延迟）；
   `_InfoSeg` 新增 `detail` 字段（卡片行素材，例如 `error_reason`），布局不看它。
3. **采样**（`platform/sysmon.py`、`platform/netmon.py`）：`CpuMeter` 首拍只建基线；
   CPU/内存共用一条 1 Hz 线程（间隔硬上限 1 Hz）；网络用
   `psutil.net_io_counters()` 差分 + EMA(0.5)，首拍返回 None、计数器回绕按 0，
   `format_rate` 5 列定宽。**刻意不做 UDP 延迟探测**：那需要 socket，而架构红 line
   把网络库锁在 `petcore/net/`；`format_network_slot` 只输出 `↓ … ↑ …`。
4. **窗口**（`ui/island.py`）：44px 高固定胶囊（内缩 6、圆角 = 高/2、宽 = 行自然宽、
   下限 120），深/浅/玻璃三套配色 + 五档强调色，自绘胶囊与面板（QSS 不参与）；
   点击展开/收起卡片、拖动即收起并夹回屏幕、松手写 `island_x/island_y`、
   展开悬停暂停 15s 自动收起；卡片一行一段（段名 / 值 · 详情），错误段写原因标 `crit`，
   展开态按**卡片宽**重排（放不下折 `+N`，不画到窗外）；隐藏/停用时停掉采样线程。
5. **配置**（13 个 `island_*`）：总开关、三个显示开关、信息位（时间/自定义）、配色、
   不透明度（0.4–1.0）、强调色、单击行为、指标白名单（`network/cpu/mem/gpu/fps`，
   去重保序 ≤8）、坐标（有限值 ±100000，否则自动定位）。
6. **接线**：`CoreHost.ensure_island()/apply_island_settings()/toggle_dynamic_island()`；
   `apply_live_settings()` 顺带刷新（设置页实时预览）；`quit_app()` 停线程；
   `PetWindow.toggle_dynamic_island()` 转发；菜单项 `dynamic_island`（`pet_controls`
   内、`edge_probe` 之后，默认可见）；设置页「外观与交互 → 灵动岛」（7 行）；
   `coverage.py` 登记落点。
7. **真机渲染修正（抓图发现，已修）**：状态点原来按「窗口右边 − 内缩」反推，
   比内容右缘多退一个间距 → 压到末段上；改成按行计划预留的 trail 槽（`end + STATUS_GAP`）。
   同时补上展开态整改：面板背景（原来透明）、行按卡片宽重排、卡片文字颜色跟随配色、
   纯 glyph 段在卡片里显示中文名。

**验证**

- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q`
  → **1541 passed**（基线 1430，本轮 +111：segments 40、layout 17+2、sampling 33、
  window 21）。
- `.venv/Scripts/ruff check pet/ tests/ petcore/ examples/petcore-mods/` → All checks passed。
- `.venv/Scripts/python -m petcore --check` → exit 0。
- 真机渲染探针（`.scratch/probe_island_real.py`，真字体 + 150% DPI）：收起 434×44 逻辑
  （651×66 物理），内容 `深深 | 22:30 | ↓1.2M ↑340K | CPU 87%(warn) | 内存 61% •`；
  展开 349×205，行 `('primary','network','cpu','chip')`、level 4（末尾折 `+1`）。
- 整程序冒烟（`--root .scratch/island-app --portable --verbose`，9 秒）：
  `island apply: metrics=['network','cpu','mem'] style=dark`，0 错误 0 traceback。

**未验证 / 风险**

- 混合 DPI 双屏、真实多屏迁移未复核（只按 `screen.availableGeometry()` 做逻辑像素）。
- 卡片行未做 tooltip/无障碍描述（主分支有），长错误原因会被截断显示。
- 网络段没有延迟读数（架构红线），要延迟得先在 `petcore/net/` 加探测端口。
- 打包未重跑：新增的是纯 Python 模块，PyInstaller 静态分析能收到；`psutil` 早已在构建脚本。


## L054 · 2026-10-24 · 已复现问题收口：安装、菜单、采样与 Agent

**范围/理由**：执行既有能力质量计划；Python3.11清理失败不能吞、Qt子菜单不能失主、
GUI停用不能等阻塞读取也不能丢线程引用。新增世代隔离采样器，布局折叠同步采样需求；
Agent 同类阻塞/迟到回调已复现后修复，不改变默认开关，不启动 P4-c3。

**文件（相对本轮基线累计 numstat；含后续托盘刷新回归）**

| 文件 | 增/删 |
|---|---|
| `petcore/mods/install.py` | +27 / -14 |
| `petcore/platform/sampling.py` | +135 / -0 |
| `petcore/platform/sysmon.py` | +25 / -32 |
| `petcore/platform/netmon.py` | +28 / -33 |
| `petcore/ui/menu_model.py` | +11 / -4 |
| `petcore/ui/menu_actions.py` | +3 / -3 |
| `petcore/ui/app.py` | +8 / -2 |
| `petcore/ui/island.py` | +7 / -3 |
| `examples/petcore-mods/ai.agent/host/runtime.py` | +55 / -22 |
| `tests/test_petcore_install.py` | +92 / -0 |
| `tests/test_petcore_monitor_lifecycle.py` | +261 / -0 |
| `tests/test_petcore_island_sampling.py` | +2 / -0 |
| `tests/test_petcore_island_window.py` | +49 / -4 |
| `tests/test_petcore_menu.py` | +33 / -0 |
| `tests/test_petcore_tray.py` | +26 / -0 |
| `tests/test_petcore_agent_mod.py` | +101 / -0 |

**验证**：menu red11→green32；tray刷新 red1→green33；install red7→green35；
island red2→UI green88；monitor red12→related140；Agent red5+2→green79。
准确命令与输出文件见 [质量审查报告](PR-REPORT-PETCORE-QUALITY-REVIEW-2026-10-24.md)。
**限制**：取消不是强杀 OS 读取；永久阻塞只保留旧 daemon，不启动重叠线程；整仓门禁另记 L056。

## L055 · 2026-10-24 · 逐域后台生命周期与资源审查修复

**范围/理由**：HTTP/HTTPError 确保 close；Speech 错误回调回GUI；天气/文件停止后不再发布，
线程列表剪枝，文件请求传 cancel；音乐停用保留阻塞SMTC线程且旧歌词不得跨代。
AI 请求按 cancel 身份发布，旧完成不能删新取消句柄；vision 停用可取消；proactive旧结果不清新busy。
Windows MSG 用真实结构读取，修64位HWND高位误当消息ID。没有添加网络/常驻线程。

**文件（相对本轮基线累计 numstat）**

| 文件 | 增/删 |
|---|---|
| `examples/petcore-mods/ai.chat/host/proactive.py` | +4 / -2 |
| `examples/petcore-mods/ai.chat/host/runtime.py` | +67 / -38 |
| `examples/petcore-mods/media.music/host/runtime.py` | +41 / -20 |
| `examples/petcore-mods/tool.file-reader/host/runtime.py` | +36 / -7 |
| `examples/petcore-mods/tool.weather/host/runtime.py` | +25 / -9 |
| `petcore/net/errors.py` | +19 / -12 |
| `petcore/net/http.py` | +11 / -9 |
| `petcore/platform/session.py` | +6 / -3 |
| `petcore/ui/ports.py` | +7 / -6 |
| `tests/test_petcore_ai_mod.py` | +120 / -0 |
| `tests/test_petcore_file_reader_mod.py` | +84 / -0 |
| `tests/test_petcore_http_port.py` | +21 / -0 |
| `tests/test_petcore_music_mod.py` | +62 / -0 |
| `tests/test_petcore_net.py` | +11 / -0 |
| `tests/test_petcore_proactive.py` | +23 / -0 |
| `tests/test_petcore_speech.py` | +70 / -0 |
| `tests/test_petcore_weather_mod.py` | +42 / -0 |
| `tests/test_petcore_session.py` | +37 / -0 |

**验证**：HTTP red4→green151；Speech red3→green66；天气/文件 red5→green38，
随后后台相关176 passed；音乐 red2→green37；AI身份/vision各red2、proactive red1→相关98passed；
MSG red3→green3，关联59 passed/1 skipped。所有原始输出在 `.scratch/petcore-quality-review/`。
**限制**：真实网络服务/TTS/SMTC播放器未使用账号验收；没有触发真实系统退出。

## L056 · 2026-10-24 · 五域审查证据、主题测试隔离与阶段口径

**文件**：`tests/test_petcore_p5.py` +9/-5：像素断言原先只适用于亮色，暗色探针red1，
显式亮/暗两主题后菜单相关63passed；没有改产品QSS。文档更新 `petcore/AGENTS.md`、
`petcore/README.md`、`examples/petcore-mods/README.md`、`docs/PETCORE-SPEC.md`、
`PETCORE-ROADMAP.md`、`PETCORE-MAIN-PARITY-BACKLOG.md`、`PETCORE-ANIMATION-BACKLOG.md`、
`PETCORE-LOG.md`/`PETCORE-LOG-INDEX.md`/`INDEX.md`；两份历史PR报告仅追加范围纠正，保留原文。
新增 `PR-REPORT-PETCORE-QUALITY-REVIEW-2026-10-24.md`；逐文件原因及完整增删行数以该报告为准。

**口径**：P4-c2只读Agent、P5-a1已实现；待办调度/农历/48签/Agent写端/灵动岛二阶段未做。
设置X保存，取消/Esc恢复；不把选定petcore测试说成仓库全量；不启动下一阶段。

**验证/风险**：15s预热+60s×3采样前后实测；Windows125%单屏隔离源码运行与30轮资源检查；
Python3.12仅stdlib安装/覆盖/卸载/只读清理冒烟（无Qt/pytest）。CPU高负载三遍与最终测试数字
见报告；整仓存在旧路径兼容/菜单/编码失败与设置退出顺序相关原生崩溃，尚未全绿。
不得把本条作为合并/分发验收通过。准确未闭环项和继续断点在 `.scratch/petcore-quality-review/HANDOFF.md`。

## L057 · 2026-10-24 · P4-c3 A：整仓退出阻断与兼容性收口

**边界**：主代理串行，保留上一轮48个未提交文件。开始快照与当前原件校验在
`.scratch/petcore-p4c3/baseline/` / `preserved-baseline.json`；原48文件均保留，
其中仅5份阶段/索引文档追加本批内容。无提交、推送、发布或系统配置变更。

**根因与改动**：`pet/app.py`对子窗口直接`deleteLater()`，去除可在父对象销毁后调用
失效QObject的零延时singleShot；`pet/sprite_menu.py` / `pet/overlay_shell.py`子菜单显式绑定父菜单。
`pet/frameseq_provision.py`私有L8掩膜用字节读取兼容Pillow11；新增像素测试辅助器，保留5族原断言。
新增独立进程销毁/真实两测试顺序回归与菜单GC/释放回归。历史品牌门禁仅精确允许旧报告两行真实
分支引用，新增锁范围测试；没有修改该报告正文、全局Qt补丁、版本降级或新增skip。
逐文件原因及本批/对HEAD两种增删行数见[本批PR报告](PR-REPORT-PETCORE-P4C3-A-2026-10-24.md)第二节。

**环境**：项目内`.venv`为Python3.11.1，Qt6.11.1/Pillow11.2.1；从原requirements安装，
约束/freeze/pip-check保存在scratch，未改全局Python或提高最低版本。原环境OCR失败因缺
omegaconf与OpenCV发行名不匹配，独立环境依赖/OCR族68passed，pip check无冲突。

**验证**：旧失败族25failed→关联Pillow/文档260passed；原退出码0xC0000005，新增回归4failed→
设置/菜单92passed。完整无路径过滤pytest：**9716passed、20skipped、15warnings，1315.19s、exit0**；
原始full-a-1.txt/XML/JSON保留，没有用分段结果拼接全量。20skip逐项记录；其中bash/ffmpeg
仅PATH缺失的5项通过隔离工具补测5passed（27.38s），不改写原全量统计。
20个自有CPU负载进程下连续三遍各143passed（97.00/100.87/98.81s），负载99.6–99.9%，均exit0。
15s预热+60s×3菜单前后实测：构造三轮均值0.6277→0.6328ms，销毁0.07942→0.07904ms，
旧子菜单180/180失效→0/180，遗留菜单均0；不宣称性能更快。最终Ruff通过，
架构/文档/公共回归门禁387passed（15.58s），包含本轮新增报告，均exit0。

**实机与风险**：Windows原生隔离设置/菜单30轮及100轮均正常退出；petcore源码菜单/托盘、
设置保存取消、双宠、岛折叠/隐藏停止采样与30轮资源检查通过，退出后Python线程仅MainThread。
旧设置100轮RSS约145→182MiB，但活QWidget为0、Qtwrapper恒423；tracemalloc追加60轮RSS下降，
既有构造位置有约342KiB Python留存。没有把“无活窗口增长”说成“已排除内存泄漏”。
其他平台/真实TTS/安装包/分发仍未验收，详见报告限制。此前质量报告仍保留当时失败记录。

**后续**：A功能退出门已过；B通用接口、C待办、D节日生日、E48签及候选分发尚未实现。
不得用本条为新功能或候选包验收背书；交接在`.scratch/petcore-p4c3/HANDOFF.md`，后续从B开始，不跳到发布。


## L058 — 2026-10-24 — P4-c3 B通用提醒与共享语音端口

- 实现按slot绑定展示、真实气泡/托盘交付、DND有界跨扩展单摘要，以及有界单语音通道、真实结束回调、按token/owner/slot取消和可撤销让位规则。
- 不将业务日程放Core；保留旧on_done/手动force语义。LoadedMedia门控修复独立进程实际复现的立即播放取消阻塞。
- 修改文件/增删与证据见[本批报告](PR-REPORT-PETCORE-P4C3-B-2026-10-24.md)；保留baseline-b原62文件差异。
- 最终重点68passed；整仓9729passed/20skipped/14warnings、pytest exit0；高负载三遍32passed。Windows隔离双宠/隐藏通知/汇总/设置/30轮/退出及15+60秒前后各三遍性能通过。scratch回显编码错误单列说明，不改写测试原始结果。
- 限制：无真实TTS、物理通知点击、其他Python/平台/双屏/候选包证据。后续C→D→E串行推进，无发布。


## L059 — 2026-10-24 — P4-c3 C待办调度与独立持久化

- 实现slot隔离、一次性/每日/提前/到期、10分钟宽限与高水位去重、无损旧清单迁移、非模态CRUD和设置取消不回滚触发状态。
- Core0.2.0/API1，todo1.1.0；逐文件增删、TDD与后续性能/实机见[C报告](PR-REPORT-PETCORE-P4C3-C-2026-10-24.md)。
- 模型11passed、功能18passed、关联95passed/13.05s/exit0；Ruff通过。累计全仓、高负载与Windows综合仍待C–E冻结，不沿用B结果。
- 下一批D历法/生日，随后E48签；无子代理/提交/发布。


## L060 — 2026-10-24 — P4-c3 D节日、节气与生日

- 本地tracked纯规则/文案移植，46节日/节气规则、slot版本化调度、默认关闭、独立生日MM-DD与让位规则；不import旧pet业务、不加动画开关。
- fun.festival1.1.0；逐文件增删/来源/风险与证据见[D报告](PR-REPORT-PETCORE-P4C3-D-2026-10-24.md)。
- d-red1collectionerror→60passed；关联126passed/14.54s0、Ruff通过。综合性能/Windows/全仓待最终C–E冻结；进入E48签及chime最小适配。


## L061 — 2026-10-24 — P4-c3 E：48签、语音联动与C–E联合验收

- 实现稳定48签/档位权重/无放回轮次、全宠同日共享与旧daily迁移；每宠设置与目标展示不全局化。
- 新增真实播放结束后的2.8秒揭签/6秒等待上限、完整签卡、首次互动提示、最多两条可取消预热；只改chime共享语音/让位与晚回调所需部分。
- TDD同时关闭同步语音拒绝导致todo回调未绑定token、失效目标让抽签任务卡住、quiet期间继续第二条预热、720px新增页裁切，以及动态历法依赖遗漏。无全局Qt补丁。
- 关联179passed；追加布局6passed、跨进程与配置回归15passed；Windows隔离源码30/120循环和真实PCM结束时序正常退出。最终整仓9837passed / 20skipped / 15warnings / 1565.27s / exit0，petcore/公共门1662passed，CPU高负载3×86passed、15+60秒前后各三轮性能完成；精确数字见[E报告](PR-REPORT-PETCORE-P4C3-E-2026-10-24.md)。
- 逐文件/增删见E报告，C/D原始切片表分别回填其报告。原48文件和各批快照保留，无提交/发布/真实账号/系统设置修改。
- 交付止于E；分发包/远程清单/下载加固/公开发布不在本轮，缺口不得标成完成。

- E收尾追加：真实FeatureManager卸载/新建runtime复现阻塞预热重复线程，单owner进程级准入修复；红1failed→45passed，随后重新原生/压力/性能/全部最终门禁，未复用修复前结果。


## L062 — 2026-10-24 — 分发阶段详细交接与本批提交交付

- 用户要求为较弱继任模型准备下一阶段计划，允许继任使用多智能体，并将A–E及本次交接提交到对应远程分支。本模型仍串行，不启动分发实现。
- 新增[详细计划](superpowers/plans/2026-10-24-petcore-p4c3-distribution.md)：T00–T09、公共接口、三组不重叠worker写集、真实源码缺口、TDD种子、安装恢复/资源预算/构建与发布边界。更新市场/路线图/文档索引并建立本地scratch任务卡。
- 本批为文档及一处测试文件末尾空行清理（AST不变）；逐文件增删、复验结果与提交号追踪见[交接报告](PR-REPORT-PETCORE-P4C3-HANDOFF-2026-10-24.md)。同一提交包含既有质量及A–E产品改动，其性能与Windows证据仍以各批原报告为准，不能扩大纯文档豁免。
- 远程核对：origin对应MerZlin/dsh-pet-indesktop，分支feat/petcore-vpet-architecture；fetch后HEAD与FETCH_HEAD无分叉。提交前复跑整仓9837passed / 20skipped / 14warnings / 1215.63s / exit0，高负载三遍各86passed（CPU99.9/100/100%），文档/公共架构300passed与Ruff通过；最终文档另复验。真实输出见报告；不强推、不合并、不上传Release。

- 提交前仅清理新历法测试末尾两行空行（AST一致、52passed）；用户要求取消重复全仓，已停止自有测试/等待进程。沿用本轮已完整运行的全仓/三遍负载，取消运行不计为通过。

- 主交付提交 `b77d4436ff623594eb4419ae9cbb2e1143657bd9`：130文件，+9423/−801，含原有质量修复、A–E及本批交接；本行与索引/报告为同批提交号回填。精确推送目标仍为origin对应仓库的 `feat/petcore-vpet-architecture`，不创建Release或合并main。

## L063 — 2026-10-24 — 动画画质评估与串行执行任务书

**授权与边界**：用户仅要求记录可交给较弱模型执行的计划；本批不实施 DPR 修复、
不新增产品测试/性能探针，不改源码、配置或素材，不提交、推送或发布。

**改动**：新增[评估与任务书](PETCORE-ANIMATION-QUALITY-ASSESSMENT-2026-10-24.md)，
固定本地 `7ab09683` 与对方 `9ce91ec8`；保留前轮会话的 105/106 素材同源、150% DPR、
Q70 单帧误差与缩放微基准，明确不是本批重测，也未核验对方发行二进制。
T00–T06 写明文件/函数、前置条件、命令、预期结果、停止条件与交接模板；未来任务全部未开始。
同步总索引、动画 backlog、素材流水线互链及日志索引；不改变现行生产编码档位或既有规范。

**逐文件增删**：`docs/PETCORE-ANIMATION-QUALITY-ASSESSMENT-2026-10-24.md`（新增）+381/−0；
`docs/ASSET-PIPELINE.md` +4/−0；`docs/INDEX.md` +3/−2；`docs/PETCORE-ANIMATION-BACKLOG.md` +4/−0；
`docs/PETCORE-LOG.md` 与 `docs/PETCORE-LOG-INDEX.md` 为本条目自身追加（+17/−0、+2/−0）。

**验证**：同批文档/架构门 `pytest -q tests/test_petcore_docs.py tests/test_pr_report_discipline.py
tests/test_architecture.py tests/test_petcore_architecture.py tests/test_ci_workflows.py` = **363 passed**；
`ruff check .` All checks passed。纯文档不改变运行行为，未跑全量 pytest、性能与 GUI；
整仓复跑见 L064。风险与下一步：任务书尚未执行，继任必须重新核对环境与基线，
不能以历史数字宣称修复完成；完整原始调查输出仅在会话中，后续须生成自己的文件证据。

## L064 — 2026-10-24 — 分发计划本机环境校正 + 整仓复跑

**授权与边界**：用户指出分发 T00–T09 计划里的环境事实来自另一台电脑，要求按本机适当优化，并重跑一次整仓；同时明确动画任务书（L063）保留但不实施。本批只改文档中的环境事实，不改分发实现、协议、版本、构建脚本或任何产品/测试代码；L063 的「逐文件增删 / 验证」两处占位按同批实际证据补齐（见 L063），动画任务本身仍未启动。

**改动**：
- `docs/superpowers/plans/2026-10-24-petcore-p4c3-distribution.md`：Global Constraints 换成实测本机事实——工作区 `E:\Work\dsh-pet-0`、Shell `pwsh` 7（禁 5.1）、`git` 走 PATH、`.venv` = Python 3.12.10 / PySide6 6.12.0 / pytest 9.1.1 / psutil 7.2.2；补 PyInstaller 6.22.3、`tools\InnoSetup\ISCC.exe`、rapidocr 3.10.0 已就绪，删除"venv 无 PyInstaller / rapidocr 不可导入"旧前提；§0.3 命令块路径与解释器探针同步；T00 依赖探针、T08 冻结包前提、Tech Stack、§0.1 的 A 行、§12 矩阵统一改成"本机 3.12.10 主跑、最低支持 3.11 不抬、3.11 专有语义另补跑"。
- 未改 `scripts/build_petcore.ps1`、`packaging/`、`petcore/`、`examples/`、`tests/`。

**为什么不能只改路径**：`rapidocr` 可导入后，整仓 skip 清单里「rapidocr not installed」不再成立；PyInstaller 已在 `.venv` 意味着 T08 不必新建独立构建 venv。这两条会直接改变 T00 基线口径与 T08 的退出门，因此必须写进计划而不是留在会话里。

**逐文件增删**：`docs/superpowers/plans/2026-10-24-petcore-p4c3-distribution.md` +14/−11；`docs/PETCORE-LOG.md` / `docs/PETCORE-LOG-INDEX.md` 为本条目自身追加。

**验证**：纯文档批次。产品/测试零改动，故性能实测与 Windows 实机行为无变化，不重复采集。同机门禁：`ruff check .` 全绿；`python -m petcore --check` exit 0；文档/架构/PR 纪律/CI 门 **363 passed**；`tests/test_petcore*.py` + 架构/PR 门 **1664 passed**（Python 3.12.10 / PySide6 6.12.0）。

**整仓复跑（本批文档落盘后）**：`PYTHONUTF8=1 QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest -q --tb=short --junitxml=.scratch/petcore-p4c3-rerun/full-rerun-20261024-162458.xml`，实际 **9841 passed / 18 skipped / 20 warnings / 1247.57s / exit 0**，XML 9859 例、failure/error 均 0。相对 E 报告（9837/20/15warnings）：收集 +2 例，skip −2 —— 那两条是 `test_agent_link`/`test_final_cleanup` 之外的「缺 bash」条件项，本机 Git Bash 可用后已实际执行并通过；本机 `rapidocr` 可导入，因此不再出现「rapidocr not installed」跳过。18 条 skip 全部来自旧 `pet/` 与平台/素材条件（符号链接权限 3、缺 ffmpeg 3、GIF 素材未生成 1、需真实前台窗口 2、素材未供给 1、POSIX 2、macOS 2、Windows 无 `tzset` 1、Cocoa 1、headless 截图 1、opt-in 声卡 1），petcore 域无 skip。原始输出与 JUnit 见 `.scratch/petcore-p4c3-rerun/`（gitignored）。

**未验证/风险**：计划里的发布链路、候选 ZIP、SAC 拦截与 3.11 子集仍未执行；本机 SAC 仍会拦未签名新构建。下一步按 T00 基线开始，先复核环境探针再派 worker。

## L065 — 2026-10-24 — P4-c3-D1/T01 分发契约冻结

**授权与边界**：用户批准 D1（T00–T07）。本批只冻结跨模块契约，不改默认市场源、不改 Core/API/mod 版本、
不改任何业务行为；T02/T03/T05 由 worker 并行、T04/T06/T07 随后。

**改动**：新增 `petcore/contracts/archive.py`（`ArchiveLimits` / `BudgetExceeded` / `MARKET_ARCHIVE_LIMITS` = 64MiB / 256MiB / 10000）、
`petcore/contracts/market.py`（`PackageOrigin` + `writes_trusted_marker()`）、`petcore/net/market_transport.py`
（`fetch_artifact` 签名接通既有下载，下载后复核压缩体积）；扩展 `petcore/contracts/http.py`
（`TransferSpec` / `TransferReport` / `ResumePolicy`，HTTP 默认只允许 https）；`petcore/market/install.py`
增加 `origin` 参数并在来源无授信资格时剔除包内 `.trusted`（防标记走私）。文档：MOD-FORMAT §18、MARKET D1/T01 节、SPEC 边界表。

**逐文件增删**：`petcore/contracts/archive.py` +54、`contracts/market.py` +28、`contracts/http.py` +52、
`net/market_transport.py` +66、`market/install.py` +18、`tests/test_petcore_distribution_contracts.py` +211、
`docs/PETCORE-MOD-FORMAT.md` +47、`docs/PETCORE-MARKET.md` +14、`docs/PETCORE-SPEC.md` +13（均为 +/−0，除文档外无删除）。

**验证**：契约测试 **11 passed / 1.73s**；市场相关 7 个测试文件 **63 passed / 11.09s**；`ruff check petcore tests` 全绿。
loopback 下载 4096 字节落盘且 `.part` 清理；2048 字节对 1024 上限抛 `BudgetExceeded(kind=compressed)` 且不留文件；
`market`/`local-zip` 装完无 `.trusted` 且消息含「已移除」，`bundled` 保留。

**性能**：无稳态路径变化（预算对象只在市场调用时构造，`origin` 分支仅一次 `exists()`）；T00 已采
`before-perf.json`，T01 标「新增路径无旧对应」，after 对照留 T09。

**未验证/风险**：`fetch_artifact` 的体积复核在下载之后，挡不住大文件先落盘（T02 移进读流）；
`open_pack`/`install` 的 `limits` 尚未落地（T03），**解包预算此刻不生效**；`origin` 只做标记剔除，
授权与事务仍归 T04。不得据此声称分发已可用。

## L066 — 2026-10-24 — P4-c3-D1/T02+T03+T05（三 worker 并行）

**授权与边界**：主模型串行完成 T00/T01 后，按批准计划派 3 个不重叠写集 worker 并行；主模型复核 diff、
补契约口径并集成。worker 未提交、未推送、未跑整仓、未改文档。本批不改默认源、不改版本、不改 UI。

**改动**：
- T02（`94d80650`）：`net/market.py` +378/−48、`net/market_transport.py` +25/−14、新增安全回归 +670、
  `contracts/http.py` +7/−2。206 按 `Content-Range` 起点对齐才追加、416 需本地长度与总长一致、压缩预算移入读流、
  跳转受跳数/协议/主机三重约束、所有路径关闭响应、取消保留 `.part`。
- 契约修正（主模型）：发现「同主机」会拒绝 GitHub Release 的 `github.com → objects.githubusercontent.com`，
  增加 `TransferSpec.allowed_hosts`（默认空 = 只同主机），并把 `resumed_from` 收窄为「仅区间对齐时非零」；MOD-FORMAT §18.2 同步。
- T03（`359446b5`）：`mods/install.py` +55/−10、新增 +245。`open_pack/install(limits=)`、解包前预检条目与声明展开、
  写入按实际字节计数（防声明造假）、失败清 staging、`limits=None` 行为不变。
- T05（`34a247cb`）：新增 `scripts/build_petcore_extensions.py` +549、`scripts/verify_petcore_extensions.py` +373、
  测试 +398、`.gitignore` +2。白名单 + 固定元数据 + 排序，两次构建 sha 相同；校验器独立重算并拒绝篡改与 `.trusted`。

**验证**：T02+T03+T05 与关联族 `46 passed / 18.04s`、`62 passed / 8.91s`；`ruff check petcore tests scripts` 全绿；
真实构建 4 包（19169 / 41454 / 9655 / 17522 字节，`excluded unknown=0`），`verify` **4/4** 独立复跑通过。
worker 红证据：旧实现 18 failed、缺 `limits` 关键字 8 failed、缺模块 exit 2。

**性能**：无新增线程/定时器/轮询；新增成本仅在市场调用路径（每 206 一次头解析、每 64KiB 一次计数、每次解包一次
`infolist()`、每次 3xx 一次比较）。T00 before 基线已在 `.scratch/.../before-perf.json`；after 对照按计划留 T09，
本批不声称更快。

**未验证/风险（关键）**：① `market/download.py` 仍走 `download_to(policy=None)`，**逐跳加固尚未进生产路径**，T04 必须切到
`fetch_artifact`；② `install_package` 的 `open_pack` 仍未传 limits，**市场解包预算尚未生效**；③ 多 URL 回退未实现；
④ 无真实 HTTPS/代理/CDN 实机；⑤ `install()` 仍以 `(False, msg)` 代替抛异常，T04 若要分类需在 `open_pack` 层拦。

## L067 — 2026-10-24 — P4-c3-D1/T04 身份·授权·事务

**边界**：只把市场安装接到 T02/T03 的加固上并补齐交叉校验与事务一致性；不改版本、不改默认源、不改 UI。

**改动**：
- 接线：`market/download.py` 的 `_fetch_one` 在 fetcher 暴露 `fetch` 时走 `HttpFetcher.fetch → fetch_artifact`，
  构造 `TransferSpec`（size / GitHub CDN 允许列表 / 超时）；只实现 `download` 的替身保持旧路径。
  `download_artifact` 与 `install_package` 新增 `limits`（默认 `MARKET_ARCHIVE_LIMITS`）并下传到 `open_pack`。
- 交叉校验：`verify.verify_manifest` 增加「能力在已知表内」「能力 ⊆ 索引声明」「api_version 一致」
  「manifest.core_requires 满足当前 Core」四项，错误点名不一致字段。
- 事务：锁写失败由「已安装但写锁失败」改为 `_rollback_failed_commit()`——有备份换回旧版，无备份删除新装目录，
  消息如实写「已回滚」/「回滚失败」；`BudgetExceeded` 被捕获并转成 `InstallOutcome(False, …)`。
- 契约：新增 `TransferSpec.allow_loopback_http`（默认真），回环判断放进 `net/market_transport.py`
  ——`market/` 不能 import `urllib`（架构门），这也顺带修掉了首版实现踩红的那条。

**逐文件增删**：`market/download.py` +60/−3、`net/market.py` +8/−0、`net/market_transport.py` +13/−1、
`contracts/http.py` +3/−0、`market/install.py` +32/−8、`market/verify.py` +35/−2、
`tests/test_petcore_market_install.py` +180/−0、`tests/test_petcore_market_transport_security.py` +17/−1、
`docs/PETCORE-MOD-FORMAT.md` +4/−4。

**验证**：市场族 58 passed / 13.78s；指定四文件 57 passed / 23.70s；全量 petcore + 公共门 **1738 passed / 123.00s**；
`ruff check petcore tests` 全绿。行为实测：本地 http 索引 + 真实 `HttpFetcher.fetch` 的 CLI `list→install→update→rollback`
通过；`allow_loopback_http=False` 时同一回环 URL 在连接前被拒且服务端 0 命中。

**性能**：无新增线程/定时器；安装路径多一次 `getattr` 探测与 `TransferSpec` 构造，下载多一次临时 staging
创建/删除与 `os.replace`；校验为集合差 + 一次版本比较。无旧同工作量可对照，after 留 T09。

**未验证/风险**：真实 HTTPS/CDN/代理下载未跑；设置页与 CLI 尚未暴露 `limits`；`install()` 对本地目录仍返回 `(False, msg)`
不抛异常；目录来源不套预算；锁失败后的 UI 重载留 T06/T07。

## L068 — 2026-10-24 — P4-c3-D1/T06 根索引·file: 链路·市场页销毁

**边界**：只加待发布根索引与离线读取链路、修设置页销毁时的线程生命周期；不改版本、不建 tag、不上传资产、不改 UI 版式。

**改动**：
- 新增根 `extensions-index.json`（137 行）：由 T05 `build_index(local=False)` 从真实候选清单生成，
  四包 `blocked=true`（理由「待发布：候选产物尚未公开」），每个版本带真实 size/sha256 与计划中的 Release URL。
- `market/model.py`：`normalize_index_url` 接受 `file://`；`market/source.py`：显式 `file:` 源**不回落**公网源。
- `net/market.py`：`fetch_index_file()`（`url2pathname` 在 net/ 内，守住架构红线）+ `HttpFetcher.fetch_index` 分支。
- `net/market_transport.py`：`file:` artifact 直接拷贝并按大小校验压缩预算，T07 本地验收由此可行。
- `ui/settings/page_market.py`：模块级 `_ORPHAN_JOBS` 持有运行中的索引线程到 `finished`；`refresh()` 在 `_disposed` 后短路。

**逐文件增删**：`extensions-index.json` +137、`market/model.py` +1/−1、`market/source.py` +3/−0、
`net/market.py` +22/−0、`net/market_transport.py` +29/−1、`ui/settings/page_market.py` +8/−1、
`tests/test_petcore_extension_index.py` +123、`tests/test_petcore_market_ui.py` +41。

**验证**：索引族 **6 passed / 0.67s**；索引+源+UI **22 passed / 1.15s**；UI 7 passed / 0.94s；`ruff check .` 全绿。
行为实测：`file:` 索引 CLI list 4 包 state=blocked exit 0；`install reminder.todo --allow-feature` exit 1、
消息含「待发布」且磁盘无 `mods/reminder.todo`；索引读取中被 dispose 后线程自行结束、迟到结果不写回、孤儿集合清空。

**性能**：`file:` 索引从「误走公网回落、约 42s」变为本地解析（测试集 0.67s）；artifact 为一次拷贝，无 socket；
销毁路径多一次 set 增删；无新增线程/定时器。

**未验证/风险**：索引四包仍 blocked，公开索引要等 Release；`RELEASE_REPO/TAG` 是拟定常量待 T09 确认；
阻塞式索引读取仍不可取消（8s 上限）；dispose 只保证不销毁运行中线程，不等同取消。

## L069 — 2026-10-24 — P4-c3-D1/T07 真实候选装卸·升级回滚·资源循环（D1 收口）

**边界**：验收批次。产品代码零改动；用 T05 真实 ZIP + `file:` 索引跑端到端与 60 次资源循环；不发布、不建 tag。

**改动**：新增 `tests/test_petcore_extension_candidates.py`（201 行，5 条）：本地索引可装、未授权被拒且零落盘、
四包 ZIP 安装后无 `.trusted` 且真实 `FeatureManager.load` 返回空 diagnostics、合成 `1.1.1` 的
`update → rollback → install` 三步与用户数据 SHA 不变、`doctor` 与 lock 一致。
scratch 探针 `.scratch/petcore-p4c3-distribution/t07/resource_loop.py` 记录 30× 装卸 + 30× 市场页开关。

**验证**：用例 **5 passed / 3.20s**（含一次四包构建）。资源循环 **2.54s**：RSS 70,651,904 → 81,752,064
（install 段 +1.63 MB 且收敛；page 段 +9.68 MB 但每 5 轮增量由 14.5 MB 递减到 1.2 MB），线程恒 4，
存活 QWidget 恒 0，staging/`.part` 恒 0。
探针自身曾误判「每页泄漏 69 个 QWidget」——补 `sendPostedEvents(DeferredDelete)` 后归零，属探针缺陷而非产品问题。

**未验证/风险**：全程 `file:`，无真实 HTTPS/CDN/断流；升级是改版本号的合成包，不是真旧版兼容矩阵；
`doctor` 不带 `--index-url` 仍回落默认源（既有语义）；原生设置窗手工点击、双屏/混合 DPI、非 Windows 未验。

**D1 状态**：T00–T07 全部完成。下一步 D2 = T08（Windows 冻结包 + 签名/SAC 决策）与 T09（性能 before/after、整仓门禁、发布准备）。

## L070 — 2026-10-24 — D2/T08 冻结候选包与开发证书签名

**授权**：用户选择「开发证书签名」并批准做 T08。本批不装系统、不发布、不改安全策略、不删既有构建产物。

**改动**：
- `scripts/build_petcore.ps1`：新增 `-OutputRoot` / `-PythonPath`；`--distpath/--workpath/--specpath`、`--check` 输出、
  exe 路径、Inno 源与输出全部跟随；拒绝仓库根与已含 setup 的目录；`-Clean` 仍只传 `--clean`。
- `packaging/petcore.iss`：新增 `MySourceDist` / `MyOutputDir` 覆盖变量（默认值保持旧行为）。
  **修复真实缺陷**：此前只重定向 Inno 输出，源目录仍指向根 `dist/`（本机有 832 MB 旧构建），
  候选包会打进旧代码；修后日志 3,816 行确认打包的是隔离构建。
- 新增 `tests/test_petcore_candidate_packaging.py`（6 条文本契约）；`docs/ONEDIR_PACKAGING.md` 补参数小节；
  `petcore/AGENTS.md` 补打包红线；新增 `docs/PETCORE-D1-ACCEPTANCE-2026-10-24.md`（D1 对外验收说明）。

**逐文件增删**：`scripts/build_petcore.ps1` +29/−8、`packaging/petcore.iss` +10/−2、
`tests/test_petcore_candidate_packaging.py` +63、`docs/ONEDIR_PACKAGING.md` +19、`petcore/AGENTS.md` +3、
`docs/PETCORE-D1-ACCEPTANCE-2026-10-24.md` +149、`docs/INDEX.md` +1。

**验证**：构建 exit 0；exe 15,079,368 B sha256 `dc40aa268ceb3f4c…`、setup 261,718,360 B `bc26e800044a2f14…`，
两者 `Get-AuthenticodeSignature` 均 **Valid**（`CN=DSH Pet Core Dev`）；Inno 编译 96.296 s，onedir 582 MB。
冻结包 `--check` **exit 0 / 715 ms / diagnostics [] / menu_template json**；冻结 `market` CLI 用 `file:` 索引
安装四个候选包全部 exit 0，`mods/` 四目录齐全；GUI 启动进程存活（96 MB）后按流程终止。打包契约测试 6 passed。

**未验证/风险**：安装向导只构建未安装（装机会写用户目录/注册表/自启，属 T09）；SAC 结论只对本次签名构建有效；
根 `dist/` 的 832 MB 旧构建未删；setup 内 `examples/petcore-mods` 勾选/不勾选的落盘差异未实测。

## L071 — 2026-10-24 — D2/T09 性能对照·整仓门禁·安装器验收·发布准备

**边界**：只做验收与发布文档；产品代码零改动；不建 tag、不传资产、不切默认源、不装到真实系统目录。

**改动**：新增 `docs/PETCORE-EXTENSIONS-RELEASE.md`（发布手册：产物摘要/三个先决确认/五步流程/逐步回滚/明确不做）
与 `docs/PR-REPORT-PETCORE-DISTRIBUTION-T09-2026-10-24.md`；`docs/INDEX.md`、`docs/PETCORE-ROADMAP.md`、
`docs/PETCORE-D1-ACCEPTANCE-2026-10-24.md` 补 T09 状态。探针（`after_perf.py`、`installer_acceptance.ps1`、
`task_matrix.ps1`、`stress.py`）只在 `.scratch/petcore-p4c3-distribution/t09/`。

**性能（before/after 同探针，3 轮 15s+60s）**：下载 32.739→32.485 ms、续传 33.141→33.214、解包 12.993→12.689、
本地安装 38.512→37.328、市场页 13.369→13.865；p95 下载 38.774→34.230、解包 15.060→13.630；CPU 中位 R1/R2 33.3%→33.3%，
R3 40.95%→33.3%，循环数 170–180→178–180。结论：无稳态回退，部分 p95 改善。

**验证**：整仓未过滤 `pytest -q` **9941 passed / 18 skipped / 20 warnings / 1220.48s / exit 0**（JUnit 9959，failure/error 0）；
安装器隔离矩阵：`/TASKS=` 空 → 0 包、`mod_todo` → 1 包 + `.trusted`、`mod_todo,mod_festival` → 恰好 2 包、
不传 `/TASKS`（两次）→ 0 包；四种用例卸载 exit 0、目录删除、HKCU 无残留。
高负载：7 个受影响文件在 20 个自有负载进程、每轮开机 CPU 100% 下三遍 **92 passed**（105.10 / 146.78 / 110.94 s，exit 0）。

**排查留痕**：最早一次手工调用装出 9 个带 `.trusted` 的包；改用 `.ps1` 固定参数后 5 次均为上表结果。
根因是 Git Bash/MSYS 把 `/TASKS=...` 改写成 `C:/Program Files/Git/TASKS=...`，参数未到 Inno——调用方式问题，非安装器缺陷。

**未验证/风险**：真实 HTTPS/CDN/断流未跑；安装器只验静默模式（向导点击、自启、覆盖升级未验）；
性能探针为 loopback 合成负载；整仓未在 20 负载进程下跑三遍；开发证书不能用于公开分发。

## L072 — 2026-10-25 — petcore 市场生命周期、授权与候选索引修复

**边界**：按当前审查计划关闭市场线程退出、断点续传、远程功能包预算、`file://` 授权、回滚语义和候选/发布索引混用六类阻断；不上传 Release，不改变默认公开源。

**改动**：应用级 `MarketJobRegistry` 持有索引/安装/回滚 `QThread`，页面销毁只取消并断开信号，退出阶段做 2 秒有界等待；下载把 `.part` 与元数据稳定存入市场缓存并保留可恢复状态；`effective_archive_limits()` 只给远程 `feature` 包套 64 MiB/256 MiB/10000 条目上限；`file://` 仅在显式本地索引、授权根目录和同根路径同时满足时可用，网络索引与重定向不能借机访问本机文件；回滚返回结构化 `RollbackResult`，恢复失败不再伪报成功；构建器默认生成 blocked 的 `candidate` 索引，只有显式 `published` 才解除 blocked。同步补充架构红线与故障回归测试。

**逐文件增删**：`git diff --cached --numstat` 实测：实现 `petcore/contracts/archive.py` +41/−0、`contracts/http.py` +5/−0、`market/cli.py` +11/−2、`market/download.py` +90/−6、`market/install.py` +160/−38、`market/source.py` +30/−5、`net/market.py` +37/−6、`net/market_transport.py` +103/−27、`ui/app.py` +8/−0、`ui/market_jobs.py` +82/−0、`ui/settings/page_market.py` +82/−18、`scripts/build_petcore_extensions.py` +25/−6；测试 `tests/test_petcore_extension_build.py` +6/−0、`tests/test_petcore_market_hardening.py` +311/−0、`tests/test_petcore_market_install.py` +17/−4。

**验证**：市场传输/安装/UI/远程预算/索引/构建/本批 hardening 联合 **90 passed / 19.56s**；其中新增市场阻断族 **51 passed / 8.46s**；后续完整门禁仍待本批全部代码与文档稳定后重跑。

**限制**：本批没有真实 HTTPS/CDN、真实 Release、冻结包或外部代理验收；网络、PySide6 与文件源的确定性回归不等同公开分发已完成。`_ORPHAN_JOBS` 仅保留为旧探针兼容符号，实际任务已由应用级 registry 持有。

## L073 — 2026-10-25 — WorkerHost 与 petcore DPR 渲染边界收口

**边界**：在市场阻断关闭后，补齐本轮计划中仍有明确证据缺口的两个运行时边界：真实 worker 会话握手/心跳/取消/代次和帧渲染物理像素/DPR；不扩展主分支不存在的动画语义，不删除旧 `pet` 兼容实现。

**改动**：`WorkerSession` 增加 READY/退出事件、显式握手等待、心跳超时收口和有界退出；`WorkerHost` 为同一 owner 维护代次，替换旧 worker 后拒收迟到消息、错误和退出回调。`petcore.ui.renderer.frame_pixmap()` 按窗口所在屏的 DPR 将逻辑尺寸换算为物理像素、写回 pixmap DPR，并保留镜像行为；`PetWindow` 帧入口传入 `screen_dpr(self)`。新增子进程 worker 及 offscreen Qt DPR 回归测试。

**逐文件增删**：`petcore/platform/worker.py` +79/−23、`petcore/ui/pet_window.py` +1/−0、`petcore/ui/renderer.py` +19/−7、`tests/test_petcore_renderer.py` +43/−0、`tests/test_petcore_worker.py` +90/−109。

**验证**：worker + renderer 聚焦族 **5 passed / 4.20s**；与市场 hardening 联合运行 **56 passed / 11.83s**；`ruff` 通过。真实 worker 使用当前 Python 子进程和 JSON 管道，Qt 测试使用 `QT_QPA_PLATFORM=offscreen`；未将旧 `pet` 的历史 DPR 测试冒充本次 petcore 实机验证。

**限制**：本机没有双屏/混合 DPI 实机条件，尚未验证真实窗口跨屏、Windows GPU/解码性能和冻结包运行；这些保留在最终报告的验证缺口中。

## L074 — 2026-10-25 — 重构收尾状态与最终交付证据

**边界**：记录本轮两个可独立回滚提交的实际收口范围，不把市场/Worker/DPR 的自动化测试误报为完整主分支 parity、双屏实机、候选安装器或公开 Release 验收。

**改动**：补充 `PETCORE-EXTENSIONS-RELEASE.md` 的 candidate/published 显式状态转换；更新 `PETCORE-MAIN-PARITY-BACKLOG.md`、`PETCORE-ROADMAP.md`、`PETCORE-SPEC.md` 的当前状态快照；新增 `PR-REPORT-PETCORE-REFACTOR-FINAL-2026-10-25.md`，并登记 `docs/INDEX.md` 与 `.scratch/petcore-refactor-final/HANDOFF.md`。产品代码对应提交为 `9e973b53` 与 `e371f92c`。

**证据**：市场聚焦族 90 passed / 19.56s；Worker + renderer 5 passed / 4.20s；联合市场/Worker/renderer/架构族 56 passed / 11.83s；Ruff `All checks passed!`；架构/文档门禁 316 passed / 4.60s；CPU 高负载三遍每次 12 passed（4.98s/4.97s/4.95s）；整仓 9951 passed / 20 skipped / 14 warnings / 1289.12s / exit 0；隔离根 `python -m petcore --check` 返回 0。

**交付**：`9e973b53`、`e371f92c`、`5c2ba786` 已按独立提交推送至 `origin/feat/petcore-vpet-architecture`，推送输出为 `6326e31c..5c2ba786`，返回码 0；未上传 Release、未推送 tag、未合并 main。

**限制**：PyInstaller、双屏/混合 DPI、macOS/Linux、真实外部 TTS、真实 HTTPS/CDN 和公开 Release 未在本机完成；默认 C 盘旧数据迁移的 `os.replace` 探针返回 WinError 17，已记录为环境/迁移缺口；不沿用历史报告冒充本轮通过。

## L075 — 2026-10-25 — 运行时迁移诊断与 Worker 生命周期收口

**边界**：只改 petcore/Core 与 reminder.todo 的已存在运行时接缝；补齐迁移结果诊断、schema 识别、原子写入失败留痕和 Worker 子进程的有界退出/非法消息拒收。不新增业务 worker，不改变旧 `pet` 实现。

**改动**：`petcore/config.py` 增加 `MigrationRecord`、状态集合、备份优先迁移和失败阶段诊断；`petcore/chat/session_store.py` 增加 schema/version 校验与诊断；`examples/petcore-mods/reminder.todo/host/store.py` 保留旧待办源并区分迁移/备份/写入/校验失败；`petcore/platform/worker.py` 增加 shutdown 锁、退出码、读管道线程有界收口和未知消息拒收；新增 `tests/test_petcore_refactor_final.py` 的迁移与 Worker 回归。

**逐文件增删**：`examples/petcore-mods/reminder.todo/host/store.py` +57/−13、`petcore/chat/session_store.py` +26/−4、`petcore/config.py` +169/−22、`petcore/platform/worker.py` +66/−21、`tests/test_petcore_refactor_final.py` +156/−0（新文件）。

**验证**：Ruff 全目录通过；编译通过；新增回归 6 passed / 1.00s；本轮受影响 petcore 联合族 136 passed / 23.24s；整仓本次门禁 9957 passed、20 skipped、15 warnings、3048.17s、exit 0。高负载三遍联合族均 136 passed，pytest 分别 29.44s、24.65s、27.28s；驱动脚本总耗时分别 31.15s、38.63s、28.45s。

**限制**：默认用户数据根的旧迁移仍需独立处理 `WinError 17` 环境探针；隔离数据根 `python -m petcore --check` 可通过。没有把旧 `pet` 测试结果当作 petcore 迁移验收。

## L076 — 2026-10-25 — 角色导入、媒体边界与点击生命周期收口

**边界**：补齐已有角色目录/ZIP 导入、媒体点击按下/释放 token、彩蛋头像/提示配置和关闭时音频取消；不引入新媒体格式、不删除旧 `pet` 兼容层、不新增 VPet LPS/PNG。

**改动**：`petcore/content/importer.py` 使用临时目录、有界 ZIP 解压、路径/符号链接拒绝、单根目录规范化和 no-force 原子安装；`petcore/media/click_sound.py` 增加 `ClickSoundPair` token 状态；`petcore/ui/pet_window.py` 将点击/拖拽/探头/关闭接入 token 生命周期；`petcore/ui/easter_egg.py` 使用配置头像并回退首图；新增回归覆盖 ZIP 路径穿越、重复导入和点击 token 幂等。

**逐文件增删**：`petcore/content/importer.py` +71/−9、`petcore/media/click_sound.py` +46/−0、`petcore/ui/easter_egg.py` +25/−3、`petcore/ui/pet_window.py` +36/−7。

**验证**：角色、彩蛋、点击音效、设置和新增 refactor 测试均纳入联合 petcore 族；联合结果 136 passed / 23.24s；Ruff 与 compileall 通过。ZIP 导入在真实本机文件系统执行，重复 ID 不覆盖原角色，恶意 `../` 条目不落盘。

**限制**：没有真实双屏/混合 DPI、冻结候选包或外部媒体服务条件；本批不声称媒体跨屏实机通过。

## L077 — 2026-10-25 — 已有 parity 设置、余额入口与 GraphType 菜单收口

**边界**：只补已有 Core 账户、设置和动画入口，不新增 provider、不扩展 Agent 写端、不改变默认开关和设置作用域。

**改动**：`petcore/ui/settings/pages_core.py` 增加 ZIP 导入入口；`page_interaction.py` 增加 `easter_egg_hint`/`easter_egg_avatar` 的实时预览、保存、取消和搜索；`page_api.py` 增加异步余额查询按钮、稳定错误反馈和 disposed 后迟到结果抑制；`menu_actions.py` 使用同一 `GraphType` 枚举增加摸头、说话、睡觉、启动、工作、悬空/抛掷的可选懒加载分组。

**逐文件增删**：`petcore/ui/menu_actions.py` +11/−0、`petcore/ui/settings/page_api.py` +73/−1、`petcore/ui/settings/page_interaction.py` +64/−0、`petcore/ui/settings/pages_core.py` +28/−8。

**验证**：API/账户/设置/覆盖 petcore 族 95 passed / 52.08s；与运行时、媒体和角色回归合计 136 passed / 23.24s；架构、文档和设置覆盖门禁 318 passed / 4.46s；Ruff 通过。余额失败只显示分类原因，不将失败伪装成 0；真实外部服务未调用。

**限制**：GraphType 分组按角色资源懒加载，缺资源时保持隐藏并回退已有动作；未把“所有角色都具备全部动画资源”写成通过。候选包、双屏、多平台和公开发布仍未验收。

## L078 — 2026-10-25 — 重构收尾文档、petcore-only 最终门禁与交接

**边界**：按用户最新要求，最终验证不再重复旧 `pet` 实现整仓门禁，只运行 `petcore` 测试、Ruff 和 petcore 专项文档/架构/设置覆盖/交付纪律门禁；不切换默认入口、不构建候选包、不上传 Release。

**改动**：更新 `PR-REPORT-PETCORE-REFACTOR-FINAL-2026-10-25.md`、`PETCORE-MAIN-PARITY-BACKLOG.md`、`PETCORE-ROADMAP.md`、`PETCORE-SPEC.md`、`docs/INDEX.md`，补齐实现/自动化/Windows 源码/待验证状态；新增 `.scratch/petcore-refactor-final/HANDOFF.md` 精确记录提交、命令、缺口和 SSH over 443 推送断点。

**逐文件增删（相对代码提交 `42856889` 的当前工作区实测）**：`docs/INDEX.md` +1/−1、`docs/PETCORE-LOG-INDEX.md` +1/−0、`docs/PETCORE-LOG.md` +11/−0、`docs/PETCORE-MAIN-PARITY-BACKLOG.md` +18/−0、`docs/PETCORE-ROADMAP.md` +13/−0、`docs/PETCORE-SPEC.md` +11/−0、`docs/PR-REPORT-PETCORE-REFACTOR-FINAL-2026-10-25.md` +89/−108；最终提交前再次核对 `git diff --numstat`。

**验证**：`tests/test_petcore_*.py` 由 PowerShell 显式展开后 **1479 passed in 132.94s (0:02:12)**；`tests/test_petcore_architecture.py tests/test_petcore_docs.py tests/test_petcore_settings_coverage.py tests/test_pr_report_discipline.py` **302 passed in 4.03s**；`.venv\Scripts\python.exe -m ruff check petcore tests scripts` → `All checks passed!`；`git diff --check` 在清理报告 Markdown 尾随空格后通过。此前已完成的一次整仓 **9957 passed / 20 skipped / 15 warnings / 3048.17s / exit 0** 仅保留为历史证据，不再重复。

**限制与下一断点**：本机探针为单屏/DPR 1.0，PyInstaller 未安装；双屏混合 DPI、候选包、macOS/Linux、真实 TTS/CDN/余额服务和公开 Release 仍未验收。下一步只做最终文档提交、SSH over 443 `fetch` + `merge --ff-only`，若远端无新提交则推送 `origin/feat/petcore-vpet-architecture`。

## L079 — 2026-10-25 — 候选包构建交接与弱模型执行说明

**边界**：将 PyInstaller/Inno Setup、Windows 候选包构建、隔离数据目录验收和证据留存交给另一台电脑执行；本机不安装打包工具、不构建冻结包、不上传 Release。后续测试范围继续按用户要求限定为 `petcore` 与必要的 petcore 专项门禁，不重复旧 `pet` 实现整仓测试。

**改动**：新增 `docs/PETCORE-CANDIDATE-PACKAGING-TASK-2026-10-25.md`（详细任务说明）和 `docs/PETCORE-CANDIDATE-PACKAGING-HANDOFF-2026-10-25.md`（可推送交接文档），按环境探针、独立 venv、petcore-only 门禁、onedir、候选 `--check`、Inno 安装器、实机冒烟、SHA/文件清单、停止条件和最终回传格式编排；另在 `.scratch/petcore-packaging-candidate/HANDOFF.md` 保留本地交接副本；更新 `docs/INDEX.md` 登记两份文档。

**逐文件增删**：本次提交前以 `git diff --numstat` 为准；产品代码、构建脚本和依赖声明均未修改。构建二进制、个人配置和探针输出只允许留在被忽略的 `.scratch` 路径。

**验证**：本次仅做文档/交接改动；提交前执行 `git diff --check`、`tests/test_petcore_docs.py`、`tests/test_petcore_architecture.py`、`tests/test_petcore_settings_coverage.py`、`tests/test_pr_report_discipline.py` 及 Ruff。既有 petcore 终态证据为 1479 passed、专项门禁 302 passed、Ruff 通过；PyInstaller、候选包、安装器、双屏和跨平台验证由继任电脑按任务说明实际执行。

**下一断点**：继任模型完成或阻断候选包构建后，回填真实工具版本、退出码、SHA、安装/卸载结果和验证缺口；候选验收不等于公开 Release。

## L080 — 2026-10-25 — petcore 摸头互动

**边界**：新增 petcore 桌宠的鼠标摸头互动，不修改旧 `pet` 实现，不新增动画引擎、线程、定时器、网络请求或菜单入口。仅在窗口可见、可交互且动作空闲时，使用角色 `head_box`（缺失时回退 `body_box`）检测头部内连续往返移动。

**改动**：新增纯逻辑 `HeadPatTracker`，按 4 px 单段、14 px 累计、反向向量点积 `<= -0.25`、1.2 秒轨迹窗口和 0.65 秒冷却判定；新增默认点击、自定义名称、全部合格单次动画三种选择及连续不重复选择。`PetWindow` 接入鼠标跟踪、逻辑坐标还原、透明像素过滤、忙碌/拖拽/投掷/click-through/隐藏/关闭/换角清理；`InteractionPage` 增加启用开关、模式、多选动画列表、全选/恢复点击/清空操作，配置按宠物 slot 保存并遵守 Save/Cancel/Esc 契约。

**逐文件增删**：`petcore/engine/head_pat.py` +167/−0（新文件）；`petcore/config.py` +31/−0；`petcore/ui/pet_window.py` +89/−1；`petcore/ui/settings/page_interaction.py` +202/−0；`tests/test_petcore_head_pat.py` +137/−0（新文件）；`tests/test_petcore_interaction.py` +71/−1；`tests/test_petcore_settings.py` +43/−1。以上为本轮代码/测试变更的 `git diff --numstat` 加新文件实际行数；最终文档与报告增删以提交前 `git diff --numstat` 为准。

**验证**：摸头/交互聚焦族 **24 passed / 1.10s**；设置聚焦族 **34 passed / 6.37s**；petcore 全部 `test_petcore_*.py` **1490 passed / 130.18s / exit 0**；`ruff check petcore tests scripts` 输出 **All checks passed!**；`python -m petcore --check` 返回 **0**。100,000 次纯逻辑更新耗时 **0.042175s**（约 **2,371,062 events/s，0.422 µs/event**）；设置开关/模式循环 30 次耗时 **0.235223s**（约 **7.841 ms/cycle**）。

**性能与资源**：实现只在已有 `mouseMoveEvent` 中执行轻量计算；不新增后台线程、Qt 定时器、网络或磁盘写入。设置列表只在页面刷新/角色变化时重建，不为每次鼠标移动分配持久任务。未进行旧 `pet` 测试。

**实机与限制**：本机本轮只执行 offscreen Qt 和 Core 检查，未执行真实 Windows 桌面鼠标摸头、click-through、拖拽/投掷和双 slot 可视化验证；因此“Windows 实机通过”仍为未验证，不能用自动化结果替代。动画资源缺失时由现有 catalog 结果决定不触发并节流记录诊断。

**提交**：实现与测试提交为 `2a5f80e9`；候选构建、安装器、Release 和 CDN 交由另一台电脑继续。

## L081 — 2026-10-25 — P5 灵动岛、余额、UI、性能与 Core 更新收口

**范围与设计**：本批只修改 `petcore`、`tests/test_petcore_*.py` 和必要文档，不运行旧 `pet` 整仓测试。实现 Dynamic Island P5-a2（停靠/展开/消息/余额/第三方段/折叠停采样/避让）、按 slot 的 `BalancePresenter` 与左键/右键/灵动岛共用余额入口、菜单/设置图标与 QComboBox 字体度量安全边距、1 Hz 采样与聚合性能计数、HTTPS 更新 manifest/ETag/镜像/Range/断点/校验，以及仅 frozen Windows 启动独立安装器的 Core 自更新边界。传输失败保留可复用 `.part` 状态，协议/大小/摘要失败清除断点；源码运行和非 Windows 不原地替换。

**逐文件增删口径**：实现文件包括 `petcore/account/__init__.py`、新增 `account/presenter.py`、新增 `performance.py`、新增 `update/{__init__,model,service}.py`、`cli.py`、`config.py`、`island/segments.py`、`net/http.py`、`platform/{netmon,sysmon}.py`、`ui/{app,island,menu_actions,menu_model,menu_style,pet_window}.py`、`ui/settings/{coverage,dialog,page_about,page_api,style}.py`；测试包括新增 `test_petcore_{balance,island_p5,menu_icons,performance,update}.py` 及 CLI/岛/设置相关扩展；文档同步 `PETCORE-ROADMAP.md`、`PETCORE-SPEC.md`、`PETCORE-MAIN-PARITY-BACKLOG.md`、`ONLINE-UPDATE.md`、`ONEDIR_PACKAGING.md`、`STABLE_BUILDS.md`、`INDEX.md`、本报告和 `.scratch/petcore-p5-complete/HANDOFF.md`。完整 `git diff --numstat` 见 `docs/PR-REPORT-PETCORE-P5-COMPLETE-2026-10-25.md`。

**验证**：`ruff check petcore tests scripts` 输出 `All checks passed!`；P5 聚焦族 `111 passed`，CPU 压力进程下连续三遍分别 `8.22s/7.29s/6.73s`；全部 `tests/test_petcore_*.py` 为 `1511 passed in 124.28s (0:02:04)`、exit 0；`python -m petcore --check` exit 0，报告 `frozen=false/can_auto_install=false` 且 HTTPS trusted host 检查通过。性能探针按 15 秒预热、60 秒采集、active/hidden/off 各 3 次执行，原始 JSON 为 `.scratch/petcore-p5-complete/performance-2026-10-25.json`。

**状态与限制**：本机只做 Windows 进程级 `--check` 和 offscreen Qt；PySide6 6.11.1、Python 3.11.1、psutil 7.2.2 可用，项目 venv 无 PyInstaller 模块，未启动真实安装器。GPU/FPS 无原生探针时显示具体 unavailable 原因，不伪造 0。真实桌面菜单/高 DPI/双屏、冻结候选包、真实余额服务、macOS/Linux、CDN/Release 仍是环境缺口；本轮不上传、不覆盖安装、不切换默认入口。


## L082 — 2026-10-25 — P5 更新取消与可选探针收尾

**改动**：在 P5 初始实现基础上收口 `petcore/ui/settings/page_about.py` 的下载中状态和取消按钮、`petcore/ui/app.py` 的取消结果与 generation 拒收；`petcore/ui/island.py` 增加 `set_probe_snapshot()` / `clear_probe_snapshot()` 作为可选 GPU/FPS 平台探针接缝；`petcore/config.py` 与 `petcore/platform/sysmon.py` 修正不可用能力口径；新增取消和真实 probe snapshot 回归。当前工作区相对基线的相关增删为：`petcore/ui/island.py` +258/−10、`petcore/config.py` +5/−1、`petcore/ui/settings/page_about.py` +68/−0、`petcore/ui/app.py` +213/−2、`petcore/platform/sysmon.py` +4/−2、`tests/test_petcore_island_p5.py` +97/−0（新增）、`tests/test_petcore_about_page.py` +15/−0。

**行为**：更新下载现在先进入 `downloading` 状态，设置页可取消；取消会使本代回调失效，不会在取消后更新 UI、启动安装或写入完成状态。GPU/FPS 有真实平台快照时显示注入的值和单位，无探针时继续显示明确 unavailable 原因，不创建第二采样线程、不伪造 0。

**验证**：`ruff check petcore tests scripts` 输出 `All checks passed!`；P5 聚焦族 `121 passed in 13.08s`，CPU 压力下 3 次分别 `13.08s / 13.29s / 12.96s`；`tests/test_petcore_*.py` 全部 `1513 passed in 126.19s (0:02:06)`、exit 0；`python -m petcore --check` exit 0；`git diff --check` 无空白错误（仅报告 LF/CRLF 转换提示）。

**限制**：本机无真实桌面、冻结安装器或原生 GPU/FPS 探针；未使用真实余额服务、CDN/Release、真实 API key，也未修改旧 `pet`。
