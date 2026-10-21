# PR 报告：petcore P2-A / P2-B1（2026-10-20）

分支：`feat/petcore-vpet-architecture`（未提交）
范围：`petcore/`、`tests/test_petcore_*`、`scripts/`、`packaging/`、`docs/PETCORE-*`
目标：在 P1 的 core 上补交互、单进程多宠、关于并入设置、菜单/设置对齐与本地打包，并落下第一批内置离线 mod。

## 1. 修改文件说明

### 1.1 交互 Core

- `petcore/engine/physics.py`：弹簧步进、松手初速估算、抛掷积分/碰边/静止、弹弓速度/形变/轨迹、力度档位。
- `petcore/engine/squash.py`：Q 弹几何（底部居中、横向鼓出、纵向压扁）。
- `petcore/engine/spin.py`：黄金回旋缓动与常量。
- `petcore/engine/collision.py`：椭圆近似碰撞、逆质量分离、冲量/摩擦、拖拽无限质量。
- `petcore/engine/feeding.py`：投喂统计预算（20000 文件 / 2s）、字节格式化、吃动画候选。
- `petcore/ui/effects.py`：Q 弹、黄金回旋、探头击飞角度；统一 `effect_angle()`。
- `petcore/ui/motion.py`：普通拖拽/弹簧拖拽/抛掷/碰边；位置始终走 `_clamp_position`。
- `petcore/ui/slingshot.py`：拖拽中右键瞄准、左键发射、Esc/右键取消、橡皮带与轨迹绘制。
- `petcore/ui/feeding.py`：拖文件进入/放下、统计写 `file_eaten_stats.json`、吃动画与气泡；不删除/移动文件。
- `petcore/ui/pet_window.py`：统一鼠标事件、Q 弹/旋转绘制、命中逆变换、播放速率、`animation_gap_seconds`、no_move/lock_position/shift_drag、拖放事件。

### 1.2 多宠

- `petcore/ui/pet_manager.py`：slot 0 主宠 + slot 1–15 子宠；`config-pet-N.json`；`active_pets` 恢复；16ms 碰撞 tick。
- `petcore/paths.py`：`pet_config_path()`、`builtin_features_dir()`。
- `petcore/config.py`：`filename=` 支持、`active_pets`/`spawn_*`/交互键归一化。
- `petcore/ui/app.py`：`CoreHost.pets`、按窗口绑定菜单、共享设置扇出、快捷键显示/隐藏全部。
- `petcore/ui/settings/page_pets.py`：生成/收回/列表/继承大小。

### 1.3 关于、菜单与设置

- `petcore/ui/settings/page_about.py`：关于并入设置，增加桌宠数、复制诊断、项目主页。
- 删除 `petcore/ui/about.py` 与 `CoreHost.show_about`；默认模板删除 `about`。
- `petcore/menu_templates/petcore-default-v1.json`：主分支顺序 + 新架构项归位 + 内置 mod 项。
- `petcore/ui/menu_actions.py`：动画菜单、播放速率、拖动物理、不自动移动、黄金回旋、生小肥鱼/退出子肥鱼。
- `petcore/ui/settings/page_interaction.py`：Q 弹/音效/拖拽/弹弓/碰撞/投喂/回旋/动画设置。
- `petcore/ui/settings/coverage.py` 与 `dialog.py`：新页面与覆盖矩阵。

### 1.4 mod 宿主与内置 mod

- `petcore/mods/feature.py`：`load_builtin_features()`、`FeatureContext.host`。
- `petcore/contracts/host.py`：`pets`/`interaction`/`quiet` 端口。
- `petcore/ui/ports.py`：QtScheduler、AudioAdapter、StorageAdapter、PetRegistry、InteractionAdapter、QuietMode。
- `petcore/builtin/features/`：`fun.self-talk`、`fun.click-talk`、`fun.divination`、`fun.festival`、`reminder.todo`、`voice.chime`、`media.music`、`tool.quick-launch`、`tool.quiet-mode`、`tool.links`、`tool.memory-trim`、`tool.network-info`。

### 1.5 打包

- `scripts/setup_packaging.ps1`：PyInstaller 装 `.venv`；Inno Setup 6.7.3 下载/校验/便携安装到 `tools/InnoSetup`。
- `scripts/build_petcore.ps1`：`-Clean/-Installer/-Console`、内置 mod 数据、`--check --out`、非零退出。
- `packaging/petcore.iss`：本地 `ChineseSimplified.isl`。
- `petcore/cli.py`：`--out` 与 UTF-8 stdout；`--check` 输出 `active_pets`/`pet_configs`。

### 1.6 测试

新增：`test_petcore_interaction.py`、`test_petcore_multipet.py`、`test_petcore_about_page.py`、`test_petcore_builtin_mods.py`。
更新：菜单布局、设置页标题/索引、coverage、CLI、窗口 smoke 的 FakeHost 兼容。

## 2. 性能分析

- Q 弹/回旋/击飞共用一个 16ms `PreciseTimer`；无效果时停表，静止路径不增加 tick。
- 拖拽/抛掷/碰撞各自 16ms；碰撞 O(n²)，n≤16，单屏 16 只上限下最多 120 对/tick。
- 投喂统计有文件数 + 墙钟双预算（20000 / 2s），大目录不会无限扫描。
- 多宠每只独立 `ClipLibrary`；未做共享解码 broker，P4 处理。
- 内置 mod 加载是启动时一次扫描；单个包异常只产生诊断，不阻断 core。

本轮未做独立基准；性能证据以启动/交互实机与测试耗时为口径，未宣称帧率数字。

## 3. 实机运行记录

- `python -m petcore --check --out .scratch/petcore-evidence/p2-check.json`：角色 shenshen 106 段，无诊断，`active_pets=[0]`。
- offscreen 脚本创建主宠 + 2 子宠：`active_slots=[0,1,2]`；截图 `.scratch/petcore-evidence/p2-pet-{0,1,2}.png`。
- 菜单布局：`character → animations_hub → playback_speed → music → pet_controls → quick-launch → tools_help → quiet → todo → festival → voice → divination → extensions_hub → settings → quit`。
- 内置 mod 加载：13 个 feature（含 demo），12 个 mod 设置页；官方菜单贡献 16 个 + demo 1 个。
- PyInstaller 6.22.3 onedir 构建成功；`dist/dsh-pet-core/dsh-pet-core.exe --check --out dist/check.json` 通过。
- Inno Setup 6.7.3 编译成功：`dist/dsh-pet-core-setup.exe`（约 153 MB）。
- 全量门禁：`579 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 绿。

## 4. 未验证 / 已知边界

- Q 弹中间帧已补截图 `.scratch/petcore-evidence/p2-click-squash-80ms.png`（progress≈0.64）；真实拖拽惯性/弹弓发射/碰撞仍以 offscreen 与单测为主。
- 安装包只验证构建，未做静默安装/卸载端到端。
- 多宠真实鼠标碰撞、拖拽惯性、弹弓真实发射未做逐帧录屏；offscreen 行为与单测通过。
- macOS/Linux 的窗口出屏、旋转命中未实机验证。
- `media.music` 只提供 Windows 系统媒体键，歌词/歌名/SMTC 未接入；P3 网络/worker 域未开始。`fun.festival` 只含公历固定日期，农历节日待数据包。
- `tool.memory-trim`、`tool.quick-launch`、`tool.links` 未逐项实机操作验证。
