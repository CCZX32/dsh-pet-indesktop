# PR 报告：外观页内分页、点击查看余额与峰谷提示（2026-10-26）

> 关联日志：`docs/PETCORE-LOG.md` L098。关联提交：`37d40e22`。

## 0 结论先行

三件事一起做，因为它们都落在设置与余额这一条链上：

1. 「外观与交互」页内容已经长到四屏，按主分支的设置页内分页切成
   **大小与外观 / 灵动岛 / 文字与快捷键 / 屏幕与位置** 四块；
2. 「点击查看余额」从「API 与账户」搬到「互动与物理 → 点击与音效 → 余额提示」，
   与主分支同页（`pet/settings_interaction.py` 的「点击反馈」分组），API 页留说明行；
3. 主分支的 **DeepSeek 峰谷提示**（高峰红 `#e5484d` / 空闲绿 `#30a46c`）作为余额气泡
   副标题接回来，文案与颜色开关都可在同一张卡里设置。

## 1 修改文件说明

| 文件 | 改了什么 | 为什么 | 行数 |
|---|---|---|---|
| `petcore/account/pricing.py`（新增） | 零 Qt 纯函数：`pricing_tier`（北京时间、周末/节假日空闲、工作日 09–12/14–18 高峰）、`next_pricing_switch`（40 天逐边界扫描）、`format_switch_time`（今天/明天/ISO 周措辞）、`resolve_tier_labels`（默认/梁文峰梁文谷/自定义）、`format_hint` / `format_hint_html`、`subtitle_for(config)`；常量 `TIER_PEAK_COLOR` / `TIER_IDLE_COLOR` | 主分支口径逐字移植；节假日由调用方注入（core 不反向依赖 `fun.festival`） | +227 |
| `petcore/config.py` | 新增 4 个**全局**键：`balance_tier_labels_mode`(default)、`balance_tier_label_peak`("")、`balance_tier_label_idle`("")、`balance_tier_color_enabled`(True)；`BALANCE_TIER_MODES` / `BALANCE_TIER_LABEL_MAX=12` + 归一化 | 峰谷是服务商计价事实，进程级；自定义文本 12 字上限防撑爆气泡 | +26 |
| `petcore/ui/app.py` | `_on_balance_result` 成功时带副标题；`_notify(slot, message, *, subtitle="")` 透传 `say(..., subtitle=)`，老签名降级；新增 `_balance_subtitle(window)` | 余额气泡要显示「当前高峰 · 下一空闲 12:00」 | +24/−4 |
| `petcore/ui/settings/page_interaction.py` | `_CHECK_KEYS` 加 `click_show_balance` / `balance_tier_color_enabled`；「点击与音效」分页新增「余额提示」卡（点击查看余额、峰谷提示颜色、峰谷文案、两条自定义文本，custom 才显示）；`_snapshot/_current/discard_changes/keywords` 同步 | 设置里必须能见到右键菜单能调的一切 | +109 |
| `petcore/ui/settings/pages_core.py` | `AppearancePage` 用 `ExitStack` 包出四个 `tab()`；新增 `contextlib.ExitStack` import | 不缩进 200 行控件代码的前提下切页 | +13 |
| `petcore/ui/settings/page_api.py` | 删掉重复的 `click_balance_check`，改成一行说明（指向新落点） | 两处控件写同一个键会互相覆盖 | +2/−9 |
| `petcore/ui/settings/coverage.py` | `show_balance` 落点 `("api", 点击显示余额)` → `("interaction", 点击查看余额)` | 覆盖表要指向真实入口 | +1/−1 |
| `tests/test_petcore_pricing.py`（新增） | 13 例：边界、周末、节假日注入、坏 lookups 降级、naive/aware 时间、下一档位、三种措辞、标签模式、HTML 转义、颜色开关、副标题 | 判定是纯函数，必须钉死 | +145 |
| `tests/test_petcore_balance_subtitle.py`（新增） | 5 例：默认带颜色、关颜色去标签、梁文峰模式、`_notify` 透传副标题、老签名仍出气泡 | 从配置到气泡的那一跳 | +93 |
| `tests/test_petcore_settings.py` | 新增外观页分页键/标签、搜索切分页、余额行在互动页、取消回滚余额开关 | 行为变化要可核对 | +114/−6 |

产品行为变化：外观页从平铺变四页；「点击显示余额」开关位置变动（键与语义不变）；
余额气泡多一行峰谷副标题（默认开启颜色，可用设置关掉）。

## 2 性能分析

- `pricing_tier` 是 O(1) 的星期/小时比较；`next_pricing_switch` 最坏扫 41×4=164 个候选
  时刻（微秒级），且只在余额返回时调用一次，不进心跳。
- 固定 +08:00 时区（中国 1991 年后无夏令时）省掉 `tzdata` 依赖，冻结包里少一类资源。
- 副标题是纯文本/HTML 字符串，气泡已有 `subtitle_label` 通道，无新增控件、无新增绘制路径。
- 设置页分页只影响构造期（`QStackedWidget` 多一页），搜索索引仍按 `page_search_texts`
  全量扫描，跨分页命中由 `reveal_text` 自动切页。

## 3 实机运行记录

- `pytest -q tests/test_petcore_pricing.py tests/test_petcore_balance_subtitle.py
  tests/test_petcore_balance.py tests/test_petcore_click_balance.py
  tests/test_petcore_settings.py tests/test_petcore_settings_coverage.py` → **全绿**
  （pricing 13 + subtitle 5 + 既有 balance/click/settings/coverage 用例）。
- 覆盖表测试 `test_coverage_rows_are_reachable_by_search` 通过：`点击查看余额` 能在
  互动页搜索文案里命中，说明新落点真的可达。
- 搜索跳转用例：搜「不透明度」→ `appearance.tab_container.currentKey() == "island"`。
- 取消语义：勾选后立即写配置（实时生效），点「取消」回滚到打开时的快照
  （`config.restore(snapshot)` + `discard_changes`）。
- 真实余额请求需要 API Key，本轮未做联网验收；峰谷判定用固定时间戳覆盖了
  09:00/12:00/14:00/18:00 四个边界与周末/节假日分支。
