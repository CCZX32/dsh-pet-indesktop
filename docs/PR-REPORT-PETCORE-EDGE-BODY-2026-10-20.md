# PR 报告：petcore 贴边按角色身体框（body_box）

> **基线**：`feat/petcore-vpet-architecture`（P1-C 完成后的工作区）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-20
> **范围**：实现 5 个文件、测试 3 个文件、文档 5 份；`pet/` 产品代码未改。
> **关联**：[`PETCORE-ARCHITECTURE.md`](PETCORE-ARCHITECTURE.md) §9、[`PETCORE-ROADMAP.md`](PETCORE-ROADMAP.md) §7、[`PETCORE-LOG.md`](PETCORE-LOG.md) 的 `L004`。

## 一、核心特性

修复「桌宠靠边时按动画画布边框碰撞，而不是角色形象区域」：

- 贴边、右下角/主屏落位、位置恢复/比例、屏幕热插拔迁移全部改用
  `manifest.body_box × scale` 的稳定身体框；
- 窗口透明边允许越界：拖到左/右缘时身体贴屏，画布可以部分出屏；
- `body_box` 缺失时回退整窗，保持旧行为；
- 记录下一阶段 P1-F 边缘探头设计（本次不实现）。

**红线 / 不变量**：`engine/` 禁 Qt、`contracts/` 只用标准库、`pet.*` 只允许两个适配层；
`pet/` 产品代码不改。

## 二、修改文件说明

### 实现

| 文件 | 规模 | 改动意图 |
|---|---|---|
| `petcore/engine/geometry.py` | +约 150 行 | 新增 `body_local_rect/body_at/clamp_body/clamp_body_to_screens/body_position_ratio`；多屏并集覆盖判定；保留旧 API。 |
| `petcore/engine/motion.py` | +约 20 行 | `clamp_to_screens(..., body_local=)`；新增单屏 `clamp_to_screen()`。 |
| `petcore/platform/screens.py` | +约 50 行 | `restore_position/migrate_layout/adopt_position` 支持 `body_local`；优先 `body_rx/body_ry`；默认落位按身体框。 |
| `petcore/config.py` | +约 10 行 | 顶层与 `positions` 增加 `body_rx/body_ry`。 |
| `petcore/ui/pet_window.py` | +约 70 行 | `_body_local` 缓存、`body_local_rect/body_rect`；钳制/恢复/记录/热插拔/落位全部改用身体框。 |

### 测试

| 文件 | 规模 | 覆盖 |
|---|---|---|
| `tests/test_petcore_geometry.py` | 新 | 身体框缩放、左右/上下贴边、超宽身体、跨屏缝、屏间空洞、比例往返。 |
| `tests/test_petcore_screens.py` | +60 行 | `body_rx/body_ry` 还原、旧 `rx/ry` 回退、迁移透传、adopt 按身体钳制。 |
| `tests/test_petcore_window_smoke.py` | +40 行 | shenshen `body_box` 左 x=-153 / 右 x=1611、右下角身体贴屏。 |

### 文档

- `docs/PETCORE-ARCHITECTURE.md` §9「贴边、摆放与身体框」；
- `docs/PETCORE-CHARACTER-PACKS.md`：`body_box` 是运行期定位锚点；
- `docs/PETCORE-SPEC.md`：菜单/设置契约增加「贴边按身体框」；
- `docs/PETCORE-ROADMAP.md`：P1-E 完成、P1-F 边缘探头设计；
- `docs/PETCORE-LOG.md` L004 + `PETCORE-LOG-INDEX.md`；
- `petcore/AGENTS.md`：位置钳制必须用 `body_box` 的红线。

## 三、实现要点

- **身体局部框**：`body_local = round(body_box × scale)`；`body_box` 是 640×360 源像素、已镜像对称化。
- **单屏**：合法窗口 x 范围 `[screen.left - body.x, screen.right - body.x - body.width]`；身体比屏宽时钳到下界。
- **多屏**：身体逐点落在各屏并集内就不动（跨缝合法）；落进空洞才对每块屏求候选，取位移平方最小。
- **恢复**：`body_rx/body_ry` 用「身体合法窗口范围」做分母，身体贴边时窗口可部分出屏；旧配置回退旧 `rx/ry` 公式，再用身体钳制收口。
- **落位**：`x = screen.right - CORNER_MARGIN - body.x - body.width`，`y = screen.bottom - body.y - body.height`。
- **回退**：`body_box=None` 时 `body_local == 整窗`，所有函数退化为旧行为。

## 四、性能分析

**方法**：`.venv/Scripts/python` 直接调用纯几何函数，n=20000，Windows/Python 3.12.10。

| 指标 | 实测 | 归属 |
|---|---|---|
| `clamp_body()` n=20000 | 中位 **0.0006 ms**，P95 **0.0009 ms** | 新增热路径 |
| `clamp_body_to_screens()` n=20000 | 中位 **0.002 ms**，P95 **0.0035 ms** | 新增多屏路径 |
| `_body_local` | `_activate/set_scale` 时缓存，拖拽/移动 tick 只读元组 | 新增缓存 |

**结论**：

- 稳态开销：每次拖拽/移动 tick 只增加几个整数比较，微秒级；没有新增线程、网络、磁盘或 Qt 调用。
- 新增路径：`body_local_rect` 不在 hot path 重新计算（缓存），没有每帧读 manifest。
- 内存：只多一个 4 元组缓存；无增长曲线。
- 旧路径：`body_box=None` 时等价于整窗钳制，逐像素行为与改造前一致。

## 五、实机运行记录

**环境**：Windows、shenshen、scale 0.72、150% DPI、逻辑可用区 1280×752。

1. `python -m petcore --character shenshen` 正常启动。
2. 拖到左缘：窗口逻辑 `x=-153`（物理 -230），身体左缘 = 0；透明画布出屏。截图 `.scratch/petcore-evidence/p1d-left-edge.png`。
3. 拖到右缘：窗口逻辑 `x=971`（物理 1457），身体右缘 = 1280；透明画布出屏。截图 `.scratch/petcore-evidence/p1d-right-edge.png`。
4. 重启：`config.json` 的 `body_rx=1.0` 还原到同一物理位置 `left=1457`，不跳位。
5. 检查 `config.json`：`body_rx/body_ry` 与 `pos_x/pos_y` 同时写入；旧 `rx/ry` 保留。

**未能实机验证**：

- 本机 1 块物理屏；多屏跨缝/空洞只有伪造几何单测，真实双屏未验。
- 无 `body_box` 的角色仍回退整窗；本次只验证 shenshen。
- 边缘探头（P1-F）只写设计，未实现，未验。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `.venv/Scripts/ruff check pet/ tests/ petcore/` | All checks passed |
| petcore 聚焦 | `QT_QPA_PLATFORM=offscreen pytest tests/test_petcore_*.py -q` | **257 passed** |
| 结构 + 文档/CI 纪律 | 加 `test_architecture.py` / `test_pr_report_discipline.py` / `test_ci_workflows.py` | **536 passed, 5 skipped** |
| 内容自检 | `.venv/Scripts/python -m petcore --check` | shenshen 106 段全部 webm，无诊断 |

## 七、已知限制与后续

- 旧配置首次运行可能仍停在旧窗口位置（不会自动吸到身体边缘）；拖动一次后写入
  `body_rx/body_ry`。
- 无 `body_box` 的角色包必须补 manifest，否则仍按整窗贴边。
- P1-F 边缘探头：45° 探头、`head_box` 露头锚点、放宽域、旋转渲染/命中反向映射；
  预计在下一批实现，设计见 `PETCORE-ROADMAP.md` §8。
