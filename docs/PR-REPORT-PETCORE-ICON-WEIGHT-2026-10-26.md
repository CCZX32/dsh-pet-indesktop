# PR 报告：图标重量与菜单/侧栏几何对齐（2026-10-26）

> 关联日志：`docs/PETCORE-LOG.md` L097。关联提交：`37d40e22`。

## 0 结论先行

用户第二次反馈「设置和右键菜单的图标还是过大、动画预览还是过小」。这次先量后改，
用同一块 18px 画布把三个版本的不透明像素数（alpha>40）量了一遍：

| 图标 | 首个重写版 `0922b13a`（用户认作正常） | 上一版（L096） | 主分支 `pet/` |
|---|---|---|---|
| settings | **68** | 120 | 121 |
| chat | **20**（被裁）+ 完整约 70 | 131 | 125 |
| network | **70** | 104 | 84 |
| play | **42** | 56 | 84 |

结论：L096 把笔宽钉成「恒 1.6 逻辑像素」（`_STROKE_PX / scale` 反向补偿），18px 槽位
下的墨量是初版的 1.8–6 倍——**这就是「过大」的全部原因**，与槽位 18px 无关。
初版「正常」的真实机制是：36 单位设计稿不缩放，笔画随画布一起缩到约 0.8px。

菜单几何也用离屏 `grab()` 量了：petcore 行高 **32px**、图标墨迹 12×12 起于 **x=9**、
菜单高 106；主分支 modern **24px**、14×14 起于 **x=17**、菜单高 86。

## 1 修改文件说明

| 文件 | 改了什么 | 为什么 | 行数 |
|---|---|---|---|
| `petcore/ui/icons.py` | 笔画改回设计单位口径：`pen = max(1.6 设计单位, 0.75px / scale)`；新增 `SIDEBAR_ICON_SIZE=16`；`fitted_icon()` 填充率 0.96→**1.04**、y −0.2 | 恢复「正常」那一档的笔画重量；缩略图按主分支口径略微超出槽位而不是留白 | +95/−8 |
| `petcore/ui/menu_style.py` | 对齐主分支 modern：`padding 6`（+1px 边框=7）、`border-radius 12`、`icon-size: 18px`、`QMenu::icon { left: 9px }`、item `3px 29px 3px 13px` + `border-radius 9`、分隔线 `margin 4px 4px`、右箭头 `7×11 margin-right 10`；`min-height = max(18, 字号+5)` | 旧 QSS 用 `QMenu::icon { width/height }`（Qt 会忽略），行高 32px 让图标只占 56% | +29/−13 |
| `petcore/ui/menu_actions.py` | 缩略图仍走 `fitted_icon`，跟随新的填充率 | 同一份几何口径 | +7/−8（含 L096 迁移） |
| `petcore/ui/settings/dialog.py` | 侧栏行高 42→**34**、页面图标按 `SIDEBAR_ICON_SIZE=16` 绘制（视图槽位仍 18） | 主分支 `SIDEBAR_ROW_HEIGHT=34` / `SIDEBAR_ICON_SIZE=16` | +14/−7 |
| `tests/test_petcore_icons.py`（新增） | 槽位常量、字形不裁且占 55%–95%、**墨量上限**（settings ≤90 等）、14/16px 档仍有笔画、全套 24 个字形不出界、QSS 用 `icon-size` | 把「重量」变成可回归的数字 | +186 |
| `tests/test_petcore_menu.py` | 行高 24 / 菜单高 86±6 / 图标贴左缘；`min-height` 断言 26→18、31→23 | 旧断言锁的是 32px 行 | +34/−5 |
| `tests/test_petcore_settings.py` | 侧栏行高断言 `>=42` → `==34` | 同上 | +114/−6（含本轮新增用例） |

## 2 性能分析

- 笔画在**设计坐标系**里画，槽位不变：18px / DPR=1 时物理画布仍是 18×18（DPR=1.5 时 27×27），
  与上一版同尺寸；变化只在笔宽（1.6 → 0.8 逻辑像素）。
- `fitted_icon()` 只是把 `extent` 由 `size*0.96` 改成 `size*1.04`、`y` 减 0.2，
  没有新增解码或缓存；缩略图仍按 `THUMBNAIL_MAX_SIDE=128` 解码一次。
- 菜单项变矮（32→24px）让同一菜单少占 8px/项，滚动与命中都更省。
- 无新增线程、定时器、磁盘 IO。

## 3 实机运行记录

- 离屏对照图：`.scratch/icons-compare.png`（now / `0922b13a` / 主分支 pet 三行，4× 放大），
  `.scratch/menu-now.png`（5 项菜单 160×134）。
- 量测（`QT_QPA_PLATFORM=offscreen`，DPR=1）：
  - 18px 墨量：settings 64、chat 78、network 68、play 40、application 72（上限断言 90/105/90/—/95）；
  - 字形包围盒 `(2,2)-(15,15)`，未出界；
  - 菜单：`actionGeometry().height() == 24`、菜单高 86、图标墨迹起于 x≈19。
- `pytest -q tests/test_petcore_icons.py tests/test_petcore_menu.py tests/test_petcore_settings.py`
  → **68 passed**；合并 C2 后同一批 **115 passed**。
- `ruff check petcore tests examples scripts` → 通过。
- 未做真机目视验收（离屏环境缺中文字体，文字渲染成方块，只用于几何/像素核对）。
