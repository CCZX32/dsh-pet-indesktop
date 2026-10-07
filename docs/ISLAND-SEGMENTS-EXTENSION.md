# 灵动岛第三方段扩展契约（P3 Slice F1）

> 基线：分支 `feature/island-segment-redesign`，2026-10-07（P3 Slice F1）。契约的权威实现是
> `pet/island_segments.py`（零 Qt）；本文是**对第三方的公开说明**，字段与规则变了要同步改这里。
> 相关：P1 段化重设计（`PR-REPORT-ISLAND-P1-SEGMENT-REDESIGN-2026-10-07.md`，段契约与宽度白名单先例）、
> 卡片四分区与「不支持段不占位」机制（`PR-REPORT-ISLAND-*`，见 `docs/INDEX.md`「PR 报告存档」）。

## 一句话

第三方只交**数据与声明**，岛上怎么画、画多宽、折谁、卡片怎么写，全部是宿主的事——
**你拿不到 QPainter**。契约层 `pet/island_segments.py` 不 import 任何 Qt。

```text
from pet import island_segments as segments
segments.register_segment(id=..., label=..., format_value=..., max_text=..., ...)
```

## 一、声明字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 稳定标识。非空、单行、无空白、≤ 32 字符，且不得是内置保留字（`network` / `cpu` / `mem` / `gpu`）。折叠、`+N` chip、卡片行都按它索引 |
| `format_value` | ✅ | `裸值 -> 文案` 的可调用对象。**异常与巨型串在这里被兜住**（见 §五） |
| `max_text` | ✅ | 最坏读数样本（如 `"888"`）。声明盒宽 = 实测它。**缺它直接拒注**：没有盒宽契约，岛宽会跟着读数跳，那是本项目的红线 |
| `label` | — | ≤ 6 字符，可空（纯 glyph 段）。超长自动截断并告警 |
| `unit` | — | 单位盒的串（`%` / `°C`）。非 `ok` 态不画单位但**盒宽仍占**，状态切换不跳宽 |
| `unit_full` | — | 单位全称（卡片详情列用） |
| `source` | — | 来源口径（卡片详情列用，如「本机无线网卡」） |
| `detail` | — | 一句话补充（卡片详情列用） |
| `thresholds` | — | `(warn, crit)` 两个**有限数**且 `warn < crit`。声明后并进告警阈值表：你的段与 CPU/内存走**同一条**判定链（两级 + 3pt 滞回，见 §六） |
| `read` | — | 无参取值函数。声明了就能用 `declaration.sample()` 一步拿到快照；没声明也能注册，只是 `sample()` 如实报 error |

`register_segment()` 也接受一个现成的 `SegmentDeclaration` 实例（两种调用形式等价）。

## 二、四态

段快照的 `state` 决定呈现（`render_compact`）：

| state | 胶囊文案 | 谁用 |
|---|---|---|
| `ok` | `label + 读数` | 有真读数 |
| `sampling` | `label + --` | 还没采到第一拍（**不是** 0） |
| `unknown` | `label + --` | 不认识这个 id / 读数不可解释 |
| `error` | `label + --` | 取值或格式化失败；原因进卡片（`detail["error_reason"]`） |
| `unsupported` | **不占位**（返回 `None`） | 已知 id 但当前没有能力（GPU 占位走这条） |

`--` 与声明样本同盒宽语义，所以状态切换不改岛宽。**不许伪造读数**：拿不到就说拿不到，
`sampling` 与 `--` 是两种不同的"没有"。

## 三、宽度纪律

- 盒宽 = `horizontalAdvance(label) + (4px) + horizontalAdvance(max_text)`，**实测**，
  按 `(id, 字体指纹)` 缓存；字体/DPI 一变自动重测。
- **采样值不进任何宽度键**：读数只在盒内右对齐伸缩（`9% → 100%` 个位不动）。
  你的格式化函数无论返回什么，都不可能改岛宽——这是结构保证，不是纪律。
- 运行期读数超过盒宽 → 右省略到盒宽 + warning（见 §五第二道护栏）。

## 四、120px 降级规则

声明盒宽 > `MAX_SEGMENT_WIDTH_PX`（120px）**不拒绝注册**：

```text
segments.oversize_segment_ids(font_metrics)   # -> 首批折叠候选（注册序）
```

- 超宽段照常注册、照常在注册表里（**不禁止表达**）；
- 它进「`+N` 首批折叠候选」名单，并在**首次**测到时记一条 warning（按
  `(id, 字体指纹)` 去重，不逐帧刷屏）；
- 判决在 `oversize_segment_ids()` 处做而不是在注册处，因为 px 必须实测——
  第三方注册时进程里通常还没有字体。**长段自付被先折的代价。**

## 五、恶意/失控段护栏（四处）+ 注册期拒注面

1. **格式化函数抛异常** → 段降级成 `error` 态（`--` + 卡片原因），warning 留痕。
   一次脏输出不会让整条岛停止绘制；`read` 抛异常同样走这条；
2. **返回巨型串** → 在**度量之前**按 `MAX_VALUE_CHARS`（32 字符）截断 + warning。
   理由：几万字符进一次 `QFontMetrics.horizontalAdvance` 就是自己给自己排一个 O(n) 长任务；
3. **返回多行串** → 压平成单行（段契约禁换行，否则撑破行高）；返回 `None` →
   `error` 态（漏写 return 不是"读数就是 None"）；
4. **异常文案同样限长压平**（`MAX_DETAIL_CHARS` = 120）：原因文案也是你的输入；
5. 以上任意一条触发后，**整岛宽度、收缩级、其他段的位置一个像素都不变**——
   失控段推不歪整岛。

注册期拒注面（明确报错，不静默吞）：重复 id → `ValueError`；非法 id（空/含空白/超长/
保留字）→ `ValueError`；字段缺失或非法 → `ValueError`；类型不对（id 非 str、
`format_value` 不可调用、多给字段关键字）→ `TypeError`。

## 六、告警阈值

```text
thresholds=(70.0, 85.0)   # 升到 70 上 warn、85 上 crit；降过"线 − 3"才褪色
```

判定是纯函数（`alert_severity(id, value, previous)`），滞回要的"上一拍"由宿主持有——
你只要声明阈值，不需要维护状态。没有读数的拍不会褪色（"还没读数"≠"读数降到安全值"），
所以被折叠停采样时告警不会凭空消失。

## 七、完整示例（可跑）

下面这段原样可跑（`tests/test_island_segment_extension.py` 会把它抽出来 exec 一遍，
示例腐烂测试就红）：

```python
"""第三方段最小完整示例：一个 CPU 温度段。"""
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

from pet import island_segments as segments

app = QApplication.instance() or QApplication([])

# 1) 数据源：真实实现里在这里读传感器（示例给固定值，避免依赖本机硬件）
_reading = {"celsius": None}


def read_celsius():
    return _reading["celsius"]


def format_celsius(value):
    """值 → 文案。异常与巨型串都由契约层兜住，这里可以放心写。"""
    if value is None:
        return "--"
    return f"{round(float(value))}"


declaration = segments.register_segment(
    id="cpu_temp",
    label="温度",                  # ≤ 6 字符（超了自动截断 + 告警）
    format_value=format_celsius,
    max_text="888",                # 必填：最坏读数样本，声明盒宽 = 实测它
    unit="°C",                     # 单位盒（10px 降色）
    unit_full="摄氏度",             # 以下四项只在展开卡片的详情列出现
    source="本机传感器",
    detail="CPU 封装温度",
    thresholds=(70.0, 85.0),       # warn < crit，进既有的告警判定链
    read=read_celsius,             # 可选的数据源；不声明也能用 snapshot(value)
)

# 2) 取一拍 → 段快照（护栏已在契约层生效）
_reading["celsius"] = 74.0
snapshot = declaration.sample()
assert snapshot.state == segments.STATE_OK
assert segments.render_compact(snapshot) == "温度74"        # 胶囊文案
assert segments.alert_severity(declaration.id, 74.0) == segments.ALERT_WARN

# 3) 宽度与降级判决（宿主排版时用同一份实测缓存）
metrics = QFontMetrics(QFont("", 13))
assert declaration.width_px(metrics) == (
    metrics.horizontalAdvance("温度") + segments.LABEL_GAP_PX
    + metrics.horizontalAdvance("888"))
assert declaration.is_oversize(metrics) is False
assert segments.oversize_segment_ids(metrics) == ()

# 4) 卸载时注销：声明、并进阈值表的阈值一起撤（不留第二真值）
assert segments.unregister_segment("cpu_temp") is True
assert segments.alert_thresholds("cpu_temp") is None
```

## 八、宿主接线现状（如实）

F1 交付的是**接口与护栏**，以及 GPU 占位。当前状态：

| 能力 | 状态 |
|---|---|
| 声明/校验/注销、四态、宽度自测量、120px 判决、恶意段护栏 | ✅ 已实现（`pet/island_segments.py`） |
| `gpu`：已知 id、恒 `unavailable`（本版本没接数据源） | ✅ 已接线（config 白名单 + `_unavailable_reasons` + 卡片原因行 + 设置页开关） |
| 第三方段进**胶囊**的渲染接线（`_compose_info_segments` 收第三方段） | ⬜ 未做（本 slice 无第三方段实例，接线点见该函数；现在做等于给不存在的路径铺代码） |
| `oversize_segment_ids()` 在**收缩流水线**里的消费（先折候选） | ⬜ 未做（同上：`plan_info_row` 的折叠面目前只在被测对象存在时才谈得上"先折"） |

也就是说：**接口面（注册 + 护栏 + 文档）已冻结可依赖，渲染接线在下一 slice 做**。
在那之前注册的段不会出现在胶囊上——这一点必须让第三方知道，不许含糊。

## 九、红线

1. **不碰 QPainter**：段契约层零 Qt；第三方拿到的只有数据（`format_value` 收裸值、
   返回串），没有画笔、没有窗口、没有字体对象。
2. **采样值永不进宽度键**：盒宽只认 `max_text` 与 label。你的格式化函数返回什么
   都不改几何。
3. **不伪造读数**：没数据源/取值失败 → `error`；还没采到 → `sampling`。两者都不是 0。
4. **`max_text` 必填**：宁可注册失败，也不许让岛宽跟着读数跳。
5. **单行**：label / 单位 / 读数 / detail 都禁换行（换行会撑破 44px 的行高预算）。
