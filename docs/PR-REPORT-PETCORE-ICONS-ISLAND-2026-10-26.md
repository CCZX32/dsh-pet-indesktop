# PR 报告：图标槽位与灵动岛停靠/动效移植（2026-10-26）

> 关联日志：`docs/PETCORE-LOG.md` L096。关联产物：本轮无安装包（用户要求的是源码改动 +
> 自动化验证；打包沿用 `rel-balance-2026-10-26` 的流程）。

## 0 结论先行

用户报的三件事，根因各不相同：

| 现象 | 真根因 | 修法 |
|---|---|---|
| 设置与右键菜单图标过大 | 菜单 QSS 把图标槽位写死 24px，设置侧栏 `setIconSize(24)`；而图标设计稿是 36 单位坐标系，谁也不敢把尺寸改小（会被裁） | 设计稿与槽位解耦（按 `size/36` 缩放 + 笔宽补偿），槽位统一收到 **18px**（主分支 `small_icon_size(menu)=18`），菜单左内边距 38→30 |
| 动画预览图标过小 | 动画帧是 640×390 的整块视频画布，角色只占中间 100×150，直接缩进 18px 槽位只剩 3×7 像素 | 先按 alpha 包围盒裁掉透明留白再适配槽位（`icons.fitted_icon`，主分支 `fitted_pet_pixmap_icon` 同款）；同素材不透明像素 20 → 164 |
| 灵动岛无法拖动 | `mouseMoveEvent` 调 `self.startDragDistance()`，而 `QWidget` **没有这个方法**（实测 `AttributeError`），每次拖拽在第一帧抛异常 → 退化成单击 | 改用 `QApplication.startDragDistance()`，并按主分支口径补齐起拖三清 |

同时把主分支灵动岛的**停靠（吸附）+ 滑出 + 几何动画 + 悬停缩放 + 事件果冻**移植过来。

## 1 修改文件说明

> 工作树里另有前两轮未提交的改动（审计修复 L088–L094、余额验收 L095），下表
> numstat 是相对 `1c1507f1` 的**文件级**口径；「本轮」列只描述本次改动。

| 文件 | 本轮改了什么 | 为什么 | 行数（相对 HEAD） |
|---|---|---|---|
| `petcore/ui/icons.py` | `_pixmap()` 拆开「36 单位设计稿」与「显示槽位」，按 `size/36` 缩放并反向补偿笔宽；新增 `MENU_ICON_SIZE=18`、`fitted_icon()`（裁 alpha 包围盒 + 适配槽位 + DPR 归一）；`icon/file_icon/icon_from_spec` 默认尺寸 36→18 | 图标尺寸不可调的历史包袱；缩略图被整帧画布稀释 | +83/−8 |
| `petcore/ui/menu_style.py` | 新增 `MENU_ICON_SIZE`，`QMenu::icon` 24→18（通过 `%(icon_size)d`），`QMenu::item` 左内边距 38→30 | 菜单图标与文字的左间隙 | +14/−5 |
| `petcore/ui/menu_actions.py` | `_request_thumbnail()` 改用 `fitted_icon`；`_apply_thumbnail()` 收 `QIcon` | 同上「过小」 | +7/−8 |
| `petcore/ui/settings/dialog.py` | 侧栏 `setIconSize` 24→`MENU_ICON_SIZE`；页面图标按槽位生成 | 同上「过大」 | +11/−6 |
| `petcore/ui/island.py` | 拖动改用 `QApplication.startDragDistance()` + `buttons()` 守卫 + 起拖三清；新增停靠态（`_docked/_hover_peek/_dock_edge`）、`_target_rect/_apply_fixed_size/_animate_to/_on_anim_tick/_dock_back/_hover_rects`；细条绘制；悬停缩放与事件果冻弹簧；`_update_size` 拖拽冻结 + 三分区锚点（首次定型跳过）；`_sync_sampling` 细条闸门；`refresh_from_config` 关掉开关即退出细条 | 拖动不可用 + 主分支停靠/动效缺失 | +688/−71 |
| `petcore/island/layout.py` | 新增零 Qt 纯函数 `dock_edge_for()`、`strip_rect_for()`、`ease_out_cubic()` 与 `DOCK_THRESHOLD_PX/STRIP_*` 常量 | 判定必须在零 Qt 层（AGENTS 红线） | +68 |
| `petcore/config.py` | 新增 `island_edge_dock`（True）、`island_dock_edge`（`none`）+ 白名单归一化 | 停靠开关与落盘 | +196/−5（含前轮 `extra` 区块） |
| `petcore/ui/settings/pages_core.py` | 「外观与交互 → 灵动岛」新增「贴边停靠」复选框，写 `island_edge_dock` | 新键必须有设置落点 | +96/−2 |
| `tests/test_petcore_icons.py`（新增） | 6 例：槽位常量、字形不裁边且占槽位 ≥55%、QSS 18px、整帧裁剪后角色撑满、宽高比守恒、空源返回空图标 | 把两个几何口径钉住 | +119 |
| `tests/test_petcore_island_dock.py`（新增） | 18 例：40px 停靠阈值（四边/41px 不算）、细条几何（中心/长度/厚度）、拖动真的移动窗口、抖动仍是单击、边缘停靠、非边缘不停靠、开关关闭不停靠、关开关退出细条、拖出停靠恢复胶囊、悬停滑出、800ms 收回、光标在区内不收回、细条停采与滑出恢复、动画插值到终点、隐藏即落位、拖拽冻结宽度 | 用户指出的「拖不动」与主分支口径 | +308 |
| `tests/test_petcore_menu.py`、`tests/test_petcore_settings.py` | 旧断言跟着新口径改：占位图标 36→18；缩略图判据从「64×51 原图」改成「cacheKey 变化 + 18×18」；侧栏 iconSize 24→`MENU_ICON_SIZE` | 旧测试锁的是旧实现细节 | +8/−3、+58/−1 |

产品行为变化：菜单/侧栏图标 24→18px；动画预览从「几乎看不见」变成撑满槽位；
灵动岛可拖动、可贴边停靠并悬停滑出（新键 `island_edge_dock` 默认开启）。

## 2 性能分析

**图标（静态，只在构造时算一次）**

- 旧：每个图标按 36 逻辑像素 × DPR 绘制（150% 屏 = 54×54），再由 Qt 缩到 24px 显示。
  新：按 18 逻辑像素 × DPR 绘制（27×27）。**像素量降到 1/4**，绘制时间同比例下降。
- `fitted_icon()` 每次菜单动画项解码后调用一次：裁剪是一次 `createAlphaMask` +
  `copy`（64×51 级别，实测单次 <0.5ms）；相比旧路径还少了一次 QIcon 内部缩放。
- 未新增线程、网络、磁盘；没有常驻缓存结构。

**灵动岛**

- 停靠/滑出/展开/收起：16ms 表**只在动画期间运行**（`_animating()` 为假即 `stop()`），
  静止时零开销（与主分支同口径）。单次动画 180ms ≈ 11 帧 → 约 11 次
  `setGeometry` + 1 次回调；每次 `setGeometry` 的成本与旧实现的一次性 `setFixedSize` 同量级。
- **省电**：细条态（16px、内容不画）停掉 psutil 的 CPU/内存/网络采样线程与 GPU/FPS 探针
  ——旧实现只在隐藏/折叠时停，停靠后原本会白烧采样。
- 悬停缩放/果冻：16ms 表 + 两个浮点弹簧，停止阈值（0.001 / 0.01）触发后连速度归零，
  不会长期占 CPU。
- 新增系统调用/网络/磁盘：0。位置与停靠边写盘与旧实现相同（release 一次拖拽多一次
  `config.save()`，实测 <1ms）。

**实测数字**

| 项 | 值 |
|---|---|
| 全套 petcore 测试 | 见 §3.3（本轮新增 24 例） |
| 菜单项高度/宽度（离屏，font_size=13） | 32px 高；左内边距 30px（图标 4..22，文字 30 起） |
| 缩略图不透明像素（640×390 整帧 → 18px 槽位） | 裁剪前 20 → 裁剪后 164 |
| 帧序列缩略图解码 | 沿用 `ThumbnailCache`（≤2 线程、磁盘缓存），本轮未改 |

## 3 实机运行记录

### 3.1 根因探针（都是本机真实输出）

```text
# 1) 拖不动：QWidget 没有 startDragDistance
QWidget.startDragDistance -> False
ERR AttributeError 'PySide6.QtWidgets.QWidget' object has no attribute 'startDragDistance'
QApplication.startDragDistance() -> 10

# 2) 缩略图被整帧画布稀释（同一素材）
未裁剪：18px 槽位里角色 ≈ 3×7 像素（不透明像素 20）
裁剪后：18px 槽位里角色 18×18（不透明像素 164）

# 3) 无 alpha 通道的帧会让 createAlphaMask() 返回空图（不能当成「全透明」丢掉）
opaque  -> QRect(0, 0, 64, 64)
clear   -> QRect(0, 0, 0, 0)
blob    -> QRect(270, 121, 100, 149)
```

### 3.2 离屏渲染核对

- `.scratch/menu-icons.png` / `.scratch/menu-anim.png` / `.scratch/icon18.png`：
  菜单图标 18px、动画缩略图撑满槽位；离屏平台缺中文字体，文字渲染成方块（不影响
  几何核对，真机字体正常）。
- `.scratch/menu-pad38.png` vs `.scratch/menu-pad30.png`：左内边距收紧后图标与文字
  之间的空档从 ~21px 收到 ~13px。

### 3.3 测试与静态检查

| 命令 | 结果 |
|---|---|
| `pytest tests/test_petcore_icons.py -q` | 6 passed |
| `pytest tests/test_petcore_island_dock.py -q` | 18 passed |
| `pytest -q $(ls tests/test_petcore*.py)`（全量） | **1737 passed in 125.59s，exit 0** |
| `pytest tests/test_petcore_docs.py tests/test_pr_report_discipline.py -q` | 303 passed |
| `ruff check petcore tests examples scripts` | All checks passed |

### 3.4 无法自动验证的部分（需真机手测）

- **停靠观感**：半屏吸附、悬停滑出/收回的节奏、细条在上下左右四条边的位置；
- **多屏 + 混合 DPI**：松手落在另一块屏时的选屏与缩放；
- **设置侧栏 18px 图标**在 42px 行高下的观感（若嫌小只需调 `nav.setIconSize`，
  图标本身按槽位缩放、不会再被裁）；
- **真实角色素材的动画预览**：本轮用合成帧验证几何，真实角色帧的透明留白比例需目视。

## 4 仍未做完 / 风险

1. 状态点五态（实心/空心/感叹）、声纳环、回复后 5s 呼吸浮动、130ms 内容淡化仍未移植
   ——最后一项依赖「内容位图缓存」这个前提，petcore 目前逐帧绘制。
2. 主分支的视觉装饰（三层投影 / sheen / 软陶笔高光）不做逐像素对齐。
3. 停靠与动画只在离屏环境自动化；真实多屏、混合 DPI、隐藏后重新显示的交接仍需人工验收。
4. 工作树中 L088–L095 的改动仍未提交，与本轮一起待用户决定提交方式。
