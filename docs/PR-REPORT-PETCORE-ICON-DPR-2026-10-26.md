# petcore 图标 DPR 修复 + 灵动岛去头标 / 消息开关（2026-10-26）

## 修改文件说明

| 文件 | 增/删 | 改了什么 + 为什么 |
|---|---|---|
| `petcore/ui/icons.py` | +52 / −6 | `_pixmap()` 去掉多乘的那次 DPR（`painter.scale(ratio*scale)` → `scale`）：画布已按 DPR 建并 `setDevicePixelRatio`，Qt6 的 QPainter 在带 DPR 的 QPixmap 上坐标系就是逻辑像素。新增 `pet/tools/web/todo/download/sparkles/capture/eye` 八枚字形——前四个名字早被 builtin 与示例 mod 引用，之前落到兜底小圆点。 |
| `petcore/ui/menu_style.py` | +123 / −77 | `QMenu::indicator` 收到 1px + `image: none`，新增 `MenuCheckLayer` + `install_check_layer()`（13px 强调色圆 + 白勾，圆心距行右缘 21px，主分支 `ModernCheckLayer` 移植）；QSS 对勾图片方案（`_render_check` / `check_image_path` / `_CHECK_*`）整体退役。 |
| `petcore/ui/menu_model.py` | +28 / −7 | `_append_item` 不再对勾选项跳过 `setIcon`（旧行为丢掉了 `主动识屏/Agent 联动/免打扰` 的图标）；`_append_node` 的子菜单图标回退链加 `MenuItem.icon` 与 `SUBMENU_ICONS`（`扩展` 之前明明注册了 `application` 也不显示）；`build()` 末尾装勾选层；删掉未使用且与 `icons.MENU_ICON_SIZE` 打架的 `MENU_ICON_SIZE=QSize(24,24)`。 |
| `petcore/ui/menu_actions.py` | +1 / −1 | `截图提问` 图标 `screen` → `capture`（原来三行连续三个一样的显示器）。 |
| `examples/petcore-mods/ai.chat/host/__init__.py` | +1 / −1 | `主动识屏` 图标 `screen` → `eye`（同上去重）。 |
| `petcore/ui/app.py` | +6 / −1 | 托盘菜单（`build_tray_menu`，裸 QMenu + QSS）也装勾选层，且必须装在 `aboutToShow` 重建钩子**之后**——否则「鼠标穿透」的勾选状态在 UI 上完全不可见，而托盘是开启穿透后唯一能关回来的入口（子代理复核发现的高危项）。 |
| `petcore/ui/settings/menu_editor.py` | +8 / −0 | 图标选择列表补 `pet/tools/web/todo/download/sparkles/capture/eye`。 |
| `petcore/ui/island.py` | +17 / −24 | 删头标绘制、`ICON_PX/ICON_GAP`、`_lead_trail` 的 icon 分支与两个缓存键里的 `show_icon`；`IslandConfig` 删 `show_icon`、加 `show_messages`；`add_message()` 在关闭时直接 return；`_card_rows()` 关闭时不出「最近消息」；`_IslandCard.set_show_messages()` 收起「清除消息」。 |
| `petcore/island/layout.py` | +0 / −12 | 删 `_ICON_PX/_ICON_GAP_PX`、`ICON_RING_COLORS`、`icon_ring_color()`（唯一消费点已删）。 |
| `petcore/config.py` | +7 / −3 | 键清单与 `DEFAULTS`：`island_show_icon` → `island_show_messages`（默认 `False`）；`normalize` 同步。 |
| `petcore/ui/settings/pages_core.py` | +14 / −6 | 「显示元素」去掉「显示头标」，新增「消息显示」行；`_on_island_changed` 改写 `island_show_messages`。 |
| `tests/test_petcore_icons.py` | +35 / −0 | 新增四档 DPR 裁切断言（1.25 即红）、字形清单补八枚新字形。 |
| `tests/test_petcore_menu.py` | +140 / −0 | 勾选项保留图标 + indicator 1px、三个模板子菜单图标、行尾勾选层的像素位置与「只有勾选行有标记」，以及**生产路径**（`popup` → `aboutToShow` → 0ms 表 `sync` → 菜单上有强调色像素、`close` 后层隐藏）。 |
| `tests/test_petcore_tray.py` | +19 / −0 | 托盘菜单带勾选层，且重建动作后新 QAction 会被补接 `toggled`。 |
| `tests/test_petcore_menu_icons.py` | +2 / −1 | 断言从已被 Qt 忽略的 `QMenu::icon` 改为真机制 `icon-size: 18px`。 |
| `tests/test_petcore_p5.py` | +39 / −30 | QSS 对勾图片用例换成勾选层用例（勾选行有墨、未勾选行无墨）。 |
| `tests/test_petcore_island_p5.py` / `island_window.py` / `island_visuals.py` / `probe_hub.py` | +27 / −10 | 去掉 `island_show_icon` 夹具；`icon_ring_color` 断言与头标像素断言换成「无头标 + 内容从 19px 起排」；新增消息开关三例（默认关不入队/不出行/按钮隐藏、打开后按行出现、关掉立刻消失）。 |
| `tests/test_petcore_settings.py` | +19 / −0 | 「显示头标」控件与键不存在、消息开关默认关且写配置。 |
| `docs/PETCORE-LOG.md` / `PETCORE-LOG-INDEX.md` | +? | 新增 L101 与索引行。 |
| `docs/PETCORE-SPEC.md` | +12 / −7 | 灵动岛配置键表（删 `island_show_icon`、加 `island_show_messages`，顺手订正「13 个」→ 15 个）、§15 勾选口径、§27 @2x 条目、绘制段落。 |
| `docs/PETCORE-ARCHITECTURE.md` / `docs/PETCORE-ROADMAP.md` | +2 / −2 与 +2 / −2 | §18「菜单对勾」与 H4 检查表改成行尾自绘口径、去掉「对勾图 @2x 未做」。 |
| `petcore/AGENTS.md` / `docs/INDEX.md` / `docs/PETCORE-LOG*.md` | +18 / −9 等 | 图标 DPR 红线、勾选与头标/消息口径、L101、报告登记。 |

## 性能分析

命令：`.venv/Scripts/python .scratch/bench_icons.py`（同进程 7 轮 × 50 次取均值，
Windows 11 / PySide6 offscreen QPA / 本机 150% 缩放）。修复前后的 `icon()` 用同一脚本
monkeypatch 旧 `_pixmap` 对照测量。

| 路径 | 前 | 后 | 说明 |
|---|---|---|---|
| `icon()` ×14 @dpr1.5 | 0.4712 ms | **0.4455 ms** | 少一次缩放乘法，量级不变 |
| `icon()` ×14 @dpr1.0 | — | 0.2824 ms | 100% 屏路径未变 |
| `MenuModel.build()` 8 行 | 0.4196 ms | 0.5754 ms | 勾选层 = 1 个子 QWidget + 2 个 about 信号 + 每项 1 个 `toggled`，一次性建菜单时付 |
| `MenuCheckLayer.sync()` | — | 0.0017 ms | 仅 `aboutToShow` / `show` 时调 |
| `MenuCheckLayer.render()` | — | 0.1456 ms | 只在菜单打开且重绘时跑（与菜单自身绘制同帧） |
| 灵动岛内容层重建 | 0.1417 ms | 0.1417 ms | 删掉头标绘制，口径未变（缓存命中路径不变） |

- **稳态开销**：菜单关闭时没有任何新定时器/线程；勾选层是菜单的子控件，随菜单销毁。
- **新增路径成本与触发频率**：`install_check_layer` 每次建菜单递归一次（子菜单各一层），
  `sync()` 每次 `aboutToShow` 一次，勾选层重绘与菜单自身重绘同帧。
- **系统调用/网络/磁盘/线程**：无新增。旧实现对勾选还要**写一个临时 PNG**（`check_image_path`
  首次调用 `QPixmap.save()` 到 `%TEMP%`），本轮删除 → 少一次磁盘写。
- **内存**：每张菜单多一个 13px 圆的重绘层（无位图缓存）；图标 pixmap 尺寸不变
  （`logical × dpr`）。岛侧删掉 `_recent_messages` 关闭态入队，内存只会更少。

## 实机运行记录

环境：Windows 11、150% 缩放（`app.devicePixelRatio()` 实测 1.5）、真实平台插件
（`platformName=windows`、`style=windows11`），仓库 `.venv`。

1. **图标裁切复现与修复对照**（真实平台插件，非 offscreen）：
   ```
   .venv/Scripts/python - <<'PY'   # 打印 18px 槽位 pixmap 的 alpha 包围盒
   icon(name, 18, dpr=1.5).pixmap(QSize(18,18), 1.5)
   PY
   ```
   修复前：`play (14,8,26,26)`、`screen (5,8,26,26)`、`quit (10,5,26,26)`（27px 画布，贴死右下角）；
   修复后：`play (9,5,21,21)`、`screen (3,5,23,22)`、`quit (6,3,20,19)`。
2. **菜单截图**（`.scratch/verify_menu_icons.py`，`QT_SCALE_FACTOR` 取 1 / 1.5 / 2）：
   `.scratch/accept/menu-{1,1.5,2}x-{dark,light}.png`。14 个顶层行全部有图标
   （切换角色/播放动画/AI 对话/看看屏幕/主动识屏/Agent 联动/截图提问/隐藏桌宠/桌宠控制/
   工具与帮助/免打扰/扩展/桌宠设置/退出），字形四周留白、无右下裁切；
   `主动识屏` 行尾出现蓝底白勾，其余行没有。
3. **设置侧栏截图**：`.scratch/accept/sidebar-icons-{1,1.5,2}x.png`，16px 绘制的 14 枚字形
   完整可辨（含新增 `pet/tools/web/todo/download/sparkles`）。
4. **灵动岛截图**（`.scratch/verify_island.py`，offscreen + `QT_SCALE_FACTOR=1.5`）：
   `.scratch/accept/island-capsule-messages-{0,1}.png`、
   `island-card-messages-{0,1}.png`。胶囊左侧不再有强调色圆点，文字从内缩 6+19px 起排；
   `messages=0` 卡片行 `['CPU','内存','网络']` + 两个按钮（刷新余额/设置）；
   `messages=1` 行 `['最近消息','最近消息','CPU','内存','网络']` + 三个按钮（多「清除消息」）。
5. **门禁**：
   ```
   QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py \
     tests/test_architecture.py tests/test_pr_report_discipline.py -q
   → 2122 passed in 154.49s
   .venv/Scripts/ruff check petcore/ tests/  → All checks passed
   ```
6. **托盘菜单勾选**（复核后的高危修复）：用测试同款 `CoreHost.build_tray_menu()`
   + `popup()` 实测——勾选层可见、几何等于 `menu.rect()`、「鼠标穿透」行有 **86** 个强调色像素，
   `close()` 后层隐藏。修复前同一行 **0** 个强调色像素（QSS 只留 1px indicator），
   即「穿透状态看不见、也无法从界面确认」。
7. **全量门禁**：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest -q`
   → **10303 passed, 18 skipped, 19 warnings in 1632.73s (0:27:12)**（19 条均为主分支既有
   DeprecationWarning）；`ruff check pet/ tests/ petcore/` → All checks passed；
   `python -m petcore --check` → 退出码 0、`strict.problems=[]`。

### 子代理复核（同轮修复）

复核只读跑了 `git diff` + 等价脚本，提出 1 高 / 1 中 / 3 低，全部在本轮修完：

- **高**：托盘菜单没有勾选层（QSS 对勾退役后勾选只剩层这一条路径）→ 已在
  `build_tray_menu()` 装层并加托盘用例；上面第 6 条是修复后的实测。
- **中**：SPEC §15/§27、ARCHITECTURE §18、ROADMAP 两处仍写着「QSS check 图片 + 勾选项
  不设 icon」→ 全部改成行尾自绘口径；顺带订正灵动岛键表「13 个」→ 15 个。
- **低**：设置页「强调色用于头标与正常状态点」→ 改「状态点与卡片强调」；
  图标选择器补齐 `sparkles/capture/eye`；消息开关文案补「消息引发的胶囊果冻也一并停掉」；
  新增生产路径（真 popup）用例，避免「层没装上但测试全绿」。

复核确认无问题的点：残留引用（`show_icon`/`icon_ring_color`/`MENU_ICON_SIZE(QSize)`/
`check_image_path`）清零；勾选层生命周期 30 轮 popup/close/GC 与「popup 后立刻
`deleteLater`」无异常；`layer.geometry()==menu.rect()` 与 `actionGeometry()` 同坐标系；
`fitted_icon`/`file_icon` 的 DPR 口径本来就对；四条新断言回退修复后都会变红。

### 未验证 / 已知限制

- offscreen（fusion）下带 QSS 的 QMenu **一个图标都不画**（实测：加 `QMenu::item` padding
  后图标列为空），所以「菜单里图标的位置」只能靠真实平台插件截图验收，不能进 CI 断言。
- 展开卡片三个按钮在深色卡片上仍是系统默认浅色底（既有观感问题，本轮未动）。
- 老配置里的 `island_show_icon` 读入即弃、不被清理（`Config` 只保留 `DEFAULTS` 键）。
