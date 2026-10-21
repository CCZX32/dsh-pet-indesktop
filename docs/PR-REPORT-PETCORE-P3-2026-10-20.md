# PR 报告：petcore P3 收口（2026-10-20）

分支：`feat/petcore-vpet-architecture`（未提交）
范围：设置页聚合、可导入 mod 样板、快捷启动菜单位置、移动朝向/位移同步。

## 1. 修改文件说明

### 1.1 设置页聚合

- 新增 `petcore/ui/settings/tabs.py`：主分支同款 `SettingsTabContainer`（tab bar/checkable 按钮/QStackedWidget）。
- 新增 `petcore/ui/settings/page_extensions.py`：`ExtensionsPage` 把 `ModsPage` 与所有 mod `settings_page` 收进页内标签。
- `petcore/ui/settings/base.py`：`SettingsPage` 记录 `scroll/content/heading`，新增 `prepare_embedded()`。
- `petcore/ui/settings/page_mods.py`：新增「允许功能扩展」复选框与「重新加载扩展」按钮。
- `petcore/ui/settings/dialog.py`：侧边栏只保留 7 个 Core 页；`ExtensionsPage` 替代 `ModsPage`；支持 `extension:<tab>` 选择。
- `petcore/ui/settings/style.py`：补 `#settingsTaskTabBar` / `#settingsTaskTab` 浅深 QSS。

### 1.2 可导入 mod 样板

- `fun.divination`、`fun.festival`、`reminder.todo`、`voice.chime`、`media.music` 从 `petcore/builtin/features/` 移到 `examples/petcore-mods/`。
- 新增 `examples/petcore-mods/README.md`（安装、`allow_feature_mods`、端口、规范）与 `scripts/install_example_mods.ps1`。
- 默认菜单删除这 5 个 mod 的显式节点；`tool.quick-launch:open_menu` 移入 `tools_help` 子菜单。
- 新增 `tests/test_petcore_example_mods.py`；`test_petcore_builtin_mods.py` 期望改为 7 个内置。

### 1.3 移动修复

- `contracts/content.py`：`CharacterSpec.move_curves`。
- `content/legacy.py`：`_move_data` 同时读取 stride/curve；`_read_move_curves`；curve 清洗到 0..1。
- `content/modcontent.py`：合并 media root 与 manifest 声明路径的 curve。
- `engine/motion.py`：`body_reach`、`choose_move_direction`、`quantize_move`、`move_position_at_frame`、`wander_target_y`。
- `ui/pet_window.py`：
  - `_begin_move` 按屏幕可达空间选方向，先设 `state.facing` 再重建首帧；
  - plan 保存 curve/frames_per_loop/loops；`_on_frame` 按 clip 帧号推进；
  - `_on_finished` 处理多圈重播与末拍提交；`_tick_move` 只做守卫；
  - 点击/拖拽/探头/缩放等打断统一 `_cancel_move_plan()`。
- 新增/更新 `tests/test_petcore_motion.py`、`tests/test_petcore_move_sync.py`、`tests/test_petcore_legacy.py`。

## 2. 性能分析

- 移动位置由 clip 帧回调驱动，不再额外跑 33ms 位移 timer；`_move_timer` 16ms 只做失活守卫，静止/无 plan 时不写位置。
- `move_position_at_frame` 是 O(1) 插值；curve 最长 241 帧，单次调用成本可忽略。
- 设置页内嵌页面按需构建；所有页面仍在打开设置时一次创建，未引入额外后台线程。
- 示例 mod 只有安装后才加载，不增加未安装用户的启动成本。

## 3. 实机运行记录

- 全量门禁：`591 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 绿。
- `petcore mods validate examples/petcore-mods/<id>` 5/5 通过。
- 设置无头检查：侧边栏 7 项；「扩展管理」标签 = 扩展管理 + 7 个内置设置页。
- shenshen 左移（offscreen）：plan `start_x=467 → target_x=294`，curve 241 帧；前 ~2s 静态段窗口不动，约 11s 到 target；facing=left。
- `tests/test_petcore_move_sync.py` 断言 plan 方向与 facing 一致、curve 长度=帧数。
- `tests/test_petcore_example_mods.py` 把 5 个示例包全部 `install()` 到临时数据根，再 `load_mods(allow_feature_mods=True)` 确认 5 个都启用且无诊断。
- 非 `SettingsPage` 的第三方设置页不再被静默丢弃，而是挂进「扩展管理」并显示“不参与保存”的提示（`test_plain_widget_contribution_is_hosted_with_hint`）。

## 4. 未验证 / 边界

- 示例 mod 安装后的完整 UI 点击/卸载恢复未逐项实机操作；只做了 `install()` + `load_mods` 冒烟。
- 真实桌面逐帧录屏未做；移动手感以 offscreen 采样与单测为准。
- 多屏/混合 DPI 的移动空间未实机验证。
- ~~`petcore --root X mods ...` 的全局选项顺序仍不支持~~ 已在同批次修复：`main()` 先定位子命令
  再下发根目录，`petcore --root X mods doctor` 与 `petcore --portable mods list` 均可用
  （`tests/test_petcore_cli.py::test_mods_subcommand_accepts_global_root`）。
- 设置页内嵌页保留自己的滚动区，视觉上可能有双层滚动；实机截图待补。
