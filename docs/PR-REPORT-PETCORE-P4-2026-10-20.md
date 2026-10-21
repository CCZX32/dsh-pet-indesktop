# PR 报告：petcore P4 交互与安装器收口（2026-10-20）

分支：`feat/petcore-vpet-architecture`（未提交）
范围：朝向镜像口径、黄金回旋接续、碰边逐次反馈、多宠穿模/落座、边缘探头吸附、
设置搜索与分页溢出、安装器选装扩展与无终端窗口、首次点击预热。

## 1. 修改文件说明

### 1.1 朝向与效果

- `petcore/engine/pet_state.py`：`facing` 默认值改回 `"left"`（与主分支一致）。
- `petcore/ui/pet_window.py`：`_mirrored()` 改为「`facing == "right"` 才镜像」——
  素材原生朝左，此前按 `left` 镜像导致移动方向与面朝向相反。
- `petcore/ui/effects.py`：`_begin_spin()` 补 `_ensure_timer()` + `update()`。
  此前点击动画播完后 `consume_click_finished()` 只置 `_spin_active`，计时器没起，
  角度永远停在 0°，表现为「动画播完没有触发黄金回旋」。
- `petcore/ui/pet_window.py`：新增 `_warm_interaction_assets()`，启动后预热全部
  `TOUCH_BODY` 点击 clip 与点击音效。
- `petcore/media/sound.py`：`SoundPlayer` 按路径缓存 `QSoundEffect`，新增
  `prepare()`；`play()` 复用实例，首次点击不再现场初始化 QtMultimedia。

### 1.2 物理与碰撞

- `petcore/ui/motion.py`：抛掷碰撞改为按「离地→接触」的接触沿触发
  `_on_motion_bounce()`（左右/上/下四向接触状态），并加 `BOUNCE_TRIGGER_SPEED`
  最低冲击速度；删掉「整个抛掷只响一次」的 `_throw_bounced` 闸。
- `petcore/engine/edge.py`：`edge_side_at_rest` 支持 `tolerance` 参数；新增
  `EDGE_ENGAGE_TOLERANCE_PX = 28` 与 `edge_snap_x()`。
- `petcore/ui/edge_probe.py`：进入探头先 `stop_for_probe()`，再吸附压边——落地
  反弹停在离边十几像素处也能进入探头。
- `petcore/ui/pet_manager.py`：
  - 碰撞分离结果走 `window._clamp_position()`，不会再把宠物顶出屏幕；
  - 碰撞发生时取消双方移动计划（帧驱动写位置会把分离结果覆盖回去 → 穿模互弹）；
  - 拖拽中的桌宠不参与碰撞结算，不再把别只一路推走。
- `petcore/engine/spawn.py`（新）：`candidate_positions()` / `choose_spawn_position()`，
  按「右→左→上→下」逐圈找不重叠且整只落在可用区内的落座点。
- `petcore/ui/pet_manager.py::_place_spawned` 改用该函数，去掉「主宠右侧 +24」硬编码。

### 1.3 设置

- `petcore/ui/settings/base.py`：`SettingsCard.add_row()` 返回行控件并支持 `sub`
  （缩进子项）；新增 `page_label_texts()` / `reveal_text()`。
- `petcore/ui/settings/dialog.py`：搜索口径纳入页面内所有行文案，命中后切页并
  `reveal_text()` 滚到该行。
- `petcore/ui/settings/tabs.py`：标签条装进 `QScrollArea`，两侧翻页箭头按溢出显隐，
  `setCurrentIndex` 自动滚到可见。
- `petcore/ui/settings/style.py`：补滚动区与箭头的浅深 QSS。
- `petcore/ui/settings/page_interaction.py`：「点击时跳过点击动画」标为子项，仅在
  「点击触发黄金回旋」开启时显示；`discard_changes` 后重新同步显隐。
- `petcore/ui/settings/page_mods.py`：列表标出「随安装包」，选中显示类型/版本/
  位置/授权来源。

### 1.4 扩展授信与安装器

- `petcore/mods/trust.py`（新）：`.trusted` 标记读写。
- `petcore/mods/loader.py`：feature 包在 `allow_feature_mods` **或** 带 `.trusted`
  时启用（仍然只认用户 mods 目录）。
- `petcore/ui/app.py`：`attach_window()` 不再自己复读全局开关，只认 `mod.enabled`
  ——否则随安装包投放的扩展永远激活不了。
- `packaging/petcore.iss`：5 个示例扩展改为 `[Tasks]` 可勾选项，装到
  `{userappdata}\dsh-pet-core\mods\<id>`，并投放 `.trusted`；排除 `__pycache__`。
- `packaging/trust_marker.txt`（新）：授信标记的源文件。
- `scripts/build_petcore.ps1`：默认 `--windowed`（无终端窗口），`-Console` 仅排障。
- `petcore/cli.py`：`_ensure_streams()` 兜底窗口化构建下 `sys.stdout is None`。

### 1.5 测试

- 新增 `tests/test_petcore_p4_fixes.py`：落座候选、落座避开已占位、满屏兜底、
  每次落地都触发反馈、慢速滑动不触发、回旋接续起表、贴边余量与吸附、子宠不出屏、
  碰撞分离不出屏、窄窗分页可滚动、音效实例复用。
- `tests/test_petcore_settings.py`：子选项联动显隐、搜索命中行并跳页。
- `tests/test_petcore_move_sync.py`：断言 `_mirrored()` 与移动方向一致。
- `tests/test_petcore_example_mods.py`：`.trusted` 可在关闭全局开关时加载。

## 2. 性能分析

- 音效从「每次点击新建 `QSoundEffect` + 异步加载」改为「启动预建 + 复用」，首次
  点击不再有后端初始化停顿；缓存上限 16 个。
- 点击 clip 预热从「只热一个随机点击素材」改为「全部点击素材」，每次点击都命中
  已创建的 clip。
- 碰撞 tick 仍是每对宠物 O(1)；新增的 `_clamp_position` 只是两次整数比较。
- 落座候选最多 12 个位置，逐个大配对 `rect_overlap_area`，成本可忽略。
- 设置搜索在对话框构建后对每页做一次 `findChildren(QLabel)` 文案抽取，输入时只
  做字符串包含；不新开线程、不访问磁盘。

## 3. 实机运行记录

- 全量门禁：`607 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 绿。
- 探针（offscreen，shenshen，0.5）：
  - 朝向：`facing=left → mirrored=False`，`facing=right → mirrored=True`；
  - 回旋：点击后 10.0s（点击动画全片长）开始旋转，角度 0 → -359 → 归零；
  - 碰边：一次抛掷内触发 2 次落地反馈（此前恒为 1 次）；
  - 探头：开着拖动物理贴左缘松手，落在离边 21px 后吸附压边并 `PEEKING`；
  - 多宠：两只重叠 100ms 内分开且都在屏内；拖拽时另一只不动；
  - 落座：主宠贴右缘时新子宠落到上方/左侧空位，`body` 不越界。
- 打包：`scripts/build_petcore.ps1 -Clean`（windowed）+ ISCC 成功；
  `dsh-pet-core.exe` PE `Subsystem=2`（GUI，无终端窗口）；
  `dist/dsh-pet-core-setup.exe` 180,500,361 字节，包含 5 个可勾选扩展与 `.trusted`。

## 4. 未验证 / 边界

- 安装向导的勾选流程没有真正跑一遍安装（避免污染本机 `%APPDATA%`）；只验证了
  ISCC 编译、包里含扩展文件、以及 loader 对 `.trusted` 的行为。
- 真实桌面逐帧录屏未做；朝向/回旋/碰边以 offscreen 采样与单测为准。
- 多屏/混合 DPI 下的落座与碰撞未实机验证。
- 点击动画本身在素材里是 241 帧 / 10.04s（VPet 原始 webm 即如此），所以「点击 →
  回旋」的自然等待时间较长；这是素材时长，不是逻辑缺陷。
- 首次点击是否彻底无卡顿没有做帧时间测量，只做了「预建 + 复用」路径验证。
