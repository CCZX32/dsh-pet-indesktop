# PR 报告：petcore P5 交互易用性与扩展反馈（2026-10-20）

分支：`feat/petcore-vpet-architecture`（未提交）
范围：气泡贴近角色、台词大框、设置 Enter 保存、免打扰页、扩展命令反馈、菜单对勾、
多宠碰撞改圆链。

## 1. 修改文件说明

### 1.1 气泡与角色贴合

- `petcore/ui/pet_window.py`：`_update_body_local()` 同时计算 `_head_local`；
  新增 `bubble_anchor_rect()`（`head_box` → `body_box` → 整窗）；`say()` 用它做锚点。
- `petcore/ui/bubble.py`：`_place()` 改为主分支同款候选顺序（上居中/上偏左右/两侧/
  下方），`BUBBLE_GAP = 6`，候选必须落在可用区且不与锚点相交；无解时兜底夹进屏幕。

### 1.2 台词候选改多行大框

- 新增 `petcore/ui/settings/text_lines.py`：`parse_lines()`（按行切、兼容旧 `a | b`）、
  `format_lines()`。
- `petcore/builtin/features/fun.self-talk`、`fun.click-talk`：`QLineEdit` →
  `QPlainTextEdit`（120px 高、占位「每行一条台词」），`textChanged` 250ms 防抖；
  `discard_changes()` 现在会恢复数字与文本控件（此前只恢复勾选）。
- 设置配置仍是 `list[str]`，旧单行数据打开后自动变多行。

### 1.3 设置键位

- `petcore/ui/settings/dialog.py`：`keyPressEvent` —— `Return/Enter` → 焦点不在
  `QPlainTextEdit`/`QTextEdit` 时 `accept()`；文本框内保持换行。

### 1.4 免打扰

- `petcore/ui/ports.py`：`QuietMode.remaining_seconds()`。
- `petcore/builtin/features/tool.quiet-mode/host/factory.py`：页面重写为「默认时长
  下拉 + 当前状态 + 恢复提醒 + 立即静默四档」；运行时新增 `restore` 命令，
  `quiet_30` 改按配置默认档静默；确认气泡 `force=True`；菜单贡献带 `checked`。

### 1.5 扩展命令反馈

- `petcore/contracts/host.py`：`PresentationPort.say/notify` 增加 `force` 关键字。
- `petcore/ui/app.py`：`_PresentationAdapter` 仅 `force=False` 时受免打扰抑制；
  `_register_feature_menus` 支持 contribution 的 `checked` 回调。
- `tool.network-info`：文案重排（流量 / 网卡 / 本机不联网），`say(force=True)`，
  设置页加「现在查看一次」。
- `tool.memory-trim`：`notify(force=True)`，`trimmed==0` 也给明确结果。

### 1.6 右键菜单对勾

- `petcore/ui/menu_style.py`：新增 `check_image_path()`（运行时生成 14px 对勾 PNG，
  浅/深两套），`menu_stylesheet()` 注入 `QMenu::indicator:checked { image: url(...) }`
  与 `:unchecked` 清空规则；`menu_text_color()` 作为文字色单一事实来源。
- `petcore/ui/menu_model.py`：`_append_item()` 对勾选项不再设置 icon（QSS 菜单里图标
  与勾选共用左边槽位，有图标就看不见勾）。

### 1.7 碰撞圆链

- `petcore/engine/collision.py` 重写：`circles_from_rect()`（内切三圆）、
  `deepest_overlap()`（逐圆对取最深，同心用稳定哈希方向）、
  `separation_distance()`（slop 0.5 / 60% / 1..12px / force_full 4×12）、
  `collide()` 保留冲量与摩擦（approach ≥80、恢复系数 0.82），新增 `slot` 字段。
- `petcore/ui/pet_manager.py`：`_overlap_streak` 记录连续重叠 tick（≥3 走强制分离）、
  每 tick 最多两轮分离、反馈阈值 `HIT_FEEDBACK_MIN_SPEED=300`、分离结果仍过
  `_clamp_position()`，关闭子宠时清理 streak。
- 测试：`tests/test_petcore_p5.py` 新增几何/分离/实际两只 shenshen 不相交等用例。

## 2. 性能分析

- 气泡定位是常数级候选比较（≤8 个矩形），只在 `say()` 时执行。
- 三圆链碰撞每对 9 次圆心距离，仍是 O(1)；`_tick_collision` 多跑一轮分离（最多 2 轮），
  在宠物 < 4 只时可忽略；`_overlap_streak` 命中分离的宠物后立即清零，不累积。
- 菜单对勾图片只在首次构建菜单时生成一次（写入系统临时目录，14×14 PNG）。
- 台词防抖 250ms，避免每次按键都写配置 + 重启 self-talk 定时器。

## 3. 实机运行记录

- 全量门禁：`636 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 绿；
  `petcore --check` 退出码 0。
- 探针（offscreen）：
  - shenshen 0.72：头部锚点 `(600,606,181,97)`，气泡 `y+h=600`，距头 6px（此前锚点是整窗）；
  - 贴屏幕上沿时气泡移到侧/下方且不与锚点相交；贴右缘时整体不越界；
  - 免打扰页：三段（默认时长/当前状态/立即免打扰），静默后标签显示「静默中，剩余约 15 分钟」；
  - 菜单：勾选行渲染出 ✓，未勾选行无标记，普通命令行保留图标；
  - 两只 shenshen 重叠 6px 起，30 tick 后三圆链不再相交。
- 依赖缺口（本轮实测发现）：`psutil` 在 `requirements.txt` 有声明但 `.venv` 未安装、
  打包产物也没有——内置 mod 以数据分发，PyInstaller 看不到函数内的 `import psutil`。
  所以「网络信息」只会回「缺少 psutil」，「回收内存」0/0 无反馈。已装 `psutil 7.2.2`，
  构建脚本加 `--hidden-import psutil` / `--hidden-import PySide6.QtTextToSpeech`；
  复测输出：`网络信息：发送 548.6 MB / 接收 268.7 MB
以太网 …`、
  `回收内存：已回收 26 个进程（跳过 295 个）`。
- 打包：`-Clean` windowed + Inno 安装包重新构建；`dist/dsh-pet-core/_internal/psutil/`
  含 `_psutil_windows.pyd`，`dsh-pet-core.exe --check` 退出码 0。

## 4. 未验证 / 边界

- Windows 11 真实主题下对勾的清晰度、菜单行高与图标的视觉对齐未实机比对。
- 圆链碰撞的贴合距离与旧椭圆不同（中间更早碰、四角更晚碰），手感需实机确认。
- 免打扰语义变化：静默期内用户主动点的命令仍会冒泡（有意），自动冒泡仍被抑制。
- 气泡锚点依赖角色 `head_box`；未声明的角色回退 `body_box`，可能仍偏远。
- 没有做「设置里 Enter」在全部控件类型（下拉、列表、树）上的逐个手测，只有单测覆盖
  侧边栏与多行框两种焦点。

## 5. 追加修复：碰撞瞬移 / 被撞斜（L015）

- `MotionController.set_velocity()`：切 `thrown` 前把 `_x/_y` 锚到窗口当前位置。
  此前 `_x/_y` 停留在构造时或上一次抛掷的旧坐标，碰撞冲量后的第一个 tick 会把整只
  宠物挪到旧坐标——表现为「被撞后闪现到屏幕另一端」。
- `PetManager._collide_pair()`：确认圆链真的重叠后，先让探头中的宠物
  `_edge_probe.cancel("collision", restore=True)` 回到屏内直立姿态，再重算分离；
  只是靠近不会触发。修复「被撞斜、停在 45° 探头姿态」。
- 测试：`set_velocity` 重锚、真实窗口不跳变、探头被撞退出且贴回屏内、30 tick 位移护栏。
