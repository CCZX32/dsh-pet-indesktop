# PR 报告：petcore P1-C 窗口可移动、10–300% 大小、设置实时预览、菜单/设置一致性、文档体系

> **基线**：`feat/petcore-vpet-architecture`（P1-A 完成后的工作区）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-20
> **范围**：实现 15 个文件、测试 6 个文件、文档 6 份；`pet/` 产品代码未改。
> **关联**：[`PETCORE-ROADMAP.md`](PETCORE-ROADMAP.md)、[`PETCORE-SPEC.md`](PETCORE-SPEC.md)、[`PETCORE-LOG.md`](PETCORE-LOG.md) 的 `L003`。

## 一、核心特性

解决五类用户可见问题：

1. **设置/关于窗口不再阻塞桌宠**：两个窗口改为 `NonModal`，打开时桌宠仍可拖动、点击、滚轮缩放；重复打开复用同一实例。
2. **大小可连续调整**：设置 →「外观与交互」新增滑条 + 百分比数字框 + 四档预设，范围 10%–300%；旧配置超过 300% 会被夹取。
3. **设置实时反馈**：角色/大小/置顶/穿透/跨屏等改动立即作用到桌宠；「保存」只负责落盘，「取消/关闭」恢复打开时的快照。
4. **大小默认移出右键菜单**：默认模板 `size.visible=false`；菜单编辑器仍可重新勾选；旧「未改过的默认布局」一次性迁移为隐藏，自定义布局不动。
5. **菜单/设置一一对应**：每个 Core 菜单项在 `coverage.py` 有设置落点，测试守住；补上「显示桌宠」「回到右下角」「退出桌宠」等入口。

**红线 / 不变量**：`petcore/engine/` 禁 Qt、`contracts/` 只用标准库、`pet.*` 只允许两个适配层、全包禁网络库；`pet/` 产品代码不动。

## 二、修改文件说明

### 实现

| 文件 | 规模 | 改动意图 |
|---|---|---|
| `petcore/engine/geometry.py` | 88 行 | 新增 `SCALE_MIN=0.10`、`SCALE_MAX=3.00`、`clamp_scale()`；四档 `SCALE_STEPS` 保留。 |
| `petcore/engine/pet_state.py` | 26 行 | `set_scale()` 改用 `clamp_scale()`，与 Config/窗口同一口径。 |
| `petcore/config.py` | 196 行 | scale 夹取改为 10%–300%；新增 `restore(snapshot)` 供设置取消回滚。 |
| `petcore/ui/pet_window.py` | 550 行 | `set_scale/set_character/set_always_on_top/set_click_through` 增加 `persist=False`；新增 `set_visible()`；`_remember_geometry/_restore_geometry` 支持不落盘；`open_settings(initial_page)`。 |
| `petcore/ui/app.py` | 323 行 | `CoreHost` 持有设置/关于单例；新增 `apply_live_settings()` 差异应用；`open_settings()` 改 `show()`；`show_about()` 改用非模态窗口；菜单迁移入口。 |
| `petcore/ui/about.py` | 94 行（新） | 非模态关于窗口：版本、数据目录、日志、角色/扩展数、打开数据目录/设置。 |
| `petcore/ui/placement.py` | 22 行（新） | `place_beside_pet()`：把设置/关于放到桌宠旁边并夹在可用屏幕内。 |
| `petcore/ui/settings/dialog.py` | 421 行 | 非模态、页面 key 跳转、16 ms 合并实时应用、配置快照与取消回滚、窗口定位。 |
| `petcore/ui/settings/pages_core.py` | 417 行 | 大小卡片（滑条/数字框/预设/恢复默认）、显示桌宠、回到右下角、退出桌宠；控件变化写内存配置并发 `changed`。 |
| `petcore/ui/settings/base.py` | 219 行 | `SettingsPage.changed` 信号、`make_slider/make_spin`、`add_row(expand=)`。 |
| `petcore/ui/settings/coverage.py` | 32 行（新） | Core 菜单项 → 设置页/行映射；`missing_settings_entries()`。 |
| `petcore/ui/settings/style.py` | 266 行 | 补 `QSpinBox`、`QSlider` 的浅/深样式。 |
| `petcore/ui/menu_layout.py` | 380 行 | 新增 `migrate_default_size_visibility()`：只迁移未改过的旧默认布局，避免覆盖用户自定义。 |
| `petcore/ui/menu_actions.py` | 125 行 | 大小子菜单增加「自定义大小…」打开设置外观页。 |
| `petcore/menu_templates/petcore-default-v1.json` | 40 行 | `size` 默认 `visible:false`。 |

### 测试

| 文件 | 规模 | 覆盖 |
|---|---|---|
| `tests/test_petcore_settings.py` | 367 行 | 非模态、10–300%、数字框 237%、实时预览（不点保存）、取消/关闭回滚、保存落盘。 |
| `tests/test_petcore_menu_layout.py` | 226 行 | 默认隐藏 size、编辑器仍可见、旧默认迁移、自定义布局不迁移。 |
| `tests/test_petcore_live_settings.py` | 120 行（新） | Config 夹取与 restore、PetWindow 不落盘、CoreHost 差异应用、无窗口安全。 |
| `tests/test_petcore_about.py` | 75 行（新） | 关于窗口非模态、CoreHost 复用同一实例。 |
| `tests/test_petcore_settings_coverage.py` | 56 行（新） | 菜单项覆盖矩阵与页面/行合法性。 |
| `tests/test_petcore_docs.py` | 65 行（新） | 5 份文档存在且登记、log 与 log-index 对齐、AGENTS/SPEC 契约关键词。 |

### 文档

| 文件 | 规模 | 内容 |
|---|---|---|
| `docs/PETCORE-SPEC.md` | 144 行（新） | 最终形态：core/mod 边界、用户能力、菜单/设置契约、素材/角色包、交付门、非目标、退出旧架构判定。 |
| `docs/PETCORE-LOG.md` | 123 行（新） | 追加式日志 L001–L003。 |
| `docs/PETCORE-LOG-INDEX.md` | 14 行（新） | 日志索引（先读索引，只读命中条目）。 |
| `petcore/README.md` | 126 行（新） | 开发者上手：环境、运行、目录地图、加菜单项/mod/角色包、测试门禁、已知边界。 |
| `petcore/AGENTS.md` | 74 行（新） | 每次改动写 log + index、架构红线、菜单/设置一致性、非模态与 300% 上限。 |
| `docs/INDEX.md` | +16 行 | 登记上述文档与 P1-C PR 报告。 |
| `AGENTS.md` | +6 行 | 根指南增加 petcore 入口与 log 硬要求。 |
| `README.md` | +1 行 | 开发者章节指向 `petcore/README.md`。 |
| `docs/PETCORE-ARCHITECTURE.md` | 更新 | §7 菜单默认隐藏/覆盖矩阵；新增 §8 非模态、实时预览、大小范围、窗口定位。 |
| `docs/PETCORE-ROADMAP.md` | 更新 | P1-C 完成条目、P1-D 角色包、P1-C 验收表。 |

> 本分支此前批次留下的 `.github/workflows/pr-test.yml`、`.gitignore` 改动不属于本批，未改动。

## 三、实现要点

1. **非模态是「能拖动」的根因修复**：Qt 应用级模态会拦截其他窗口的鼠标事件；只改窗口位置或 `raise_()` 都无效。改为 `NonModal` 后，桌宠窗口（`WindowDoesNotAcceptFocus`）仍能收到鼠标事件。
2. **实时预览走差异应用，不重建窗口**：页面把控件值写入内存 `Config`，`CoreHost.apply_live_settings()` 对比窗口运行态，只调用变化的 `set_*`；`persist=False` 分支跳过 `config.save()` 与位置落盘。
3. **16 ms 合并而不是每次抖动都应用**：`QTimer` 单次 16 ms，首次变化启动、后续变化不重启；避免拖滑条时每毫秒 resize 窗口，也避免「持续拖动永远不触发」。
4. **取消回滚是快照级**：对话框打开时 `config.snapshot()`，取消时 `Config.restore()` + 页面 `discard_changes()` + `apply_live_settings()`；拖宠造成的位置变化不属于设置项，保留。
5. **默认隐藏 size 的兼容迁移**：只对「去掉 mod 动作后 Core 结构完全等于旧默认」的 `menu_layout` 生效；用户改过顺序/显隐的布局不碰。

## 四、性能分析

**方法（可复现）**：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python .scratch/petcore-evidence/p1c_bench.py`
环境：Windows、Python 3.12.10、PySide6 6.12.0；样本见括号。

| 指标 | 实测 | 归属 |
|---|---|---|
| `set_scale(persist=False)`（n=200） | 中位 **0.010 ms**，P95 **0.014 ms** | 新增实时路径 |
| `set_scale(persist=True)`（n=200） | 中位 **1.415 ms**，P95 **2.676 ms** | 既有滚轮/菜单路径 |
| 100 次实时缩放后 `config.json` mtime | **未变化** | 证明实时路径不写盘 |
| `apply_live_settings()` 空 diff（n=500） | 中位 **0.000 ms**，P95 **0.001 ms** | 新增 |
| `apply_live_settings()` 单差异（n=500） | 中位 **0.001 ms**，P95 **0.001 ms** | 新增 |
| `frame_pixmap` 640×360 → 1920×1080（n=50） | 中位 **3.437 ms**，P95 **4.070 ms** | 300% 单帧缩放上限 |

**结论**：

- 稳态开销：设置窗打开但无操作时没有新增轮询；16 ms 定时器只在控件变化时启动并单次触发，空 diff 成本在微秒级。
- 新增路径：实时缩放本身约 0.01 ms，真正成本在窗口 resize/重绘；300% 单帧缩放中位 3.4 ms，未出现卡死。
- 磁盘：实时路径 100 次调用 **0 次写盘**；只有「保存」一次 `config.save()`。旧路径每次约 1.4 ms，实时路径避免了滑条拖动时的写放大。
- 系统调用/线程/网络/内存：没有新增线程、网络或轮询；`QTimer` 是 Qt 既有机制。未测长时内存曲线，未发现新增缓存。

## 五、实机运行记录

**环境**：Windows 10/11、1920×1200 单物理屏、150% DPI、PySide6 6.12.0。以下操作通过 KimiCU 真实鼠标输入完成（不是 QTest 直接投递）。

1. **启动**：`python -m petcore --character shenshen`，真实窗口 `692×389`，角色 shenshen 正常待机。
2. **设置非模态 + 拖动**：右键 →「桌宠设置」打开设置；在设置窗口保持打开的情况下，按住桌宠身体从屏幕 `left=480` 拖到 `left=380`，窗口矩形确实左移 100 px。截图：`.scratch/petcore-evidence/p1c-settings-size.png`。
3. **实时大小**：设置 →「外观与交互」→ 滑条 `set_value 150`，桌宠立即从 `692×389` 变为 `1440×810`（150% × 1.5 DPR 的物理像素），无需点保存。截图：`.scratch/petcore-evidence/p1c-pet-150.png`。
4. **取消回滚**：点「取消」，桌宠回到 `692×389`，`config.json` 未写入 150%。
5. **手输 + 保存**：重新打开设置，百分比框输入 `237`，点「保存」；`config.json` 中 `scale=2.37`，桌宠变为 `2276×1280` 物理像素。随后把配置恢复为 0.72 继续验证（237% 超出 1920×1200 屏幕，属于允许范围但会超出屏幕）。
6. **菜单默认隐藏**：重启后右键菜单只剩「切换角色 / 隐藏桌宠 / 桌宠控制 / 扩展 / 桌宠设置 / 关于 / 退出」，没有「大小」；`config.json` 中 `size.visible=false`。截图：`.scratch/petcore-evidence/p1c-menu-no-size.png`。
7. **菜单编辑器**：设置 →「菜单」，树中「大小」为 `checked=off`，仍可重新勾选；迁移没有删除节点。
8. **关于窗口**：右键 →「关于」，窗口非模态；在关于窗口打开时把桌宠从 `left=0` 拖到 `left=99`，拖动有效。截图：`.scratch/petcore-evidence/p1c-about.png`。
9. **从关于打开设置**：关于 →「打开设置」，设置直接停在「关于与诊断」页，验证 `initial_page` 跳转。

**未能实机验证**：

- 本机只有 1 块物理屏，跨屏拖动/非模态窗口跨屏摆放未验证；多屏逻辑仍只有伪造几何单测。
- macOS/Linux 的 `WindowDoesNotAcceptFocus` + 非模态对话框焦点组合未验证。
- 300% 满尺寸下的长时间拖动手感未做主观评价；只测了单帧缩放成本。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `.venv/Scripts/ruff check pet/ tests/ petcore/` | **All checks passed** |
| petcore 聚焦 | `QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py -q` | **243 passed** |
| 结构 + 文档/CI 纪律 | `pytest tests/test_petcore_*.py tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q` | **520 passed, 5 skipped** |
| 内容自检 | `.venv/Scripts/python -m petcore --check` | shenshen 106 段全部 webm，`body_box [212,60,428,330]`，无诊断 |

## 七、已知限制与后续

- 旧用户自定义 `menu_layout` 若改过顺序/显隐，不会被强行隐藏 size；这是有意的「尊重用户布局」。未改过的旧默认会迁移。
- 237%/300% 在 1080p/1200p 屏幕上会超出屏幕；这是「允许 300%」的直接结果，未做自动窗口内缩放。
- 设置/关于窗口不置顶；桌宠默认置顶，拖动时可能盖住设置窗口（可用旁边位置或先移动桌宠）。本轮只保证「能拖动」，不保证「窗口永远可见」。
- 热卸载、mod 沙箱仍不支持。
- 后续：P1-B 快捷键/自启/多宠/打包/首跑素材供给；P1-D 角色资源包导入；P2 功能域迁包。详见 `PETCORE-ROADMAP.md`。
