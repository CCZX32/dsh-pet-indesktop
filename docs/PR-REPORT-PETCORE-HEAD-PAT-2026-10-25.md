# petcore 摸头互动报告（2026-10-25）

> **基线**：`3aab8155420947f98dac9aaef50d228ed32a45cd`（`feat/petcore-vpet-architecture`，本轮开始前工作区干净）
> **范围**：petcore 实现、设置、回归测试和阶段文档；不修改旧 `pet` 实现。
> **验证口径**：按用户要求只运行 `petcore` 测试族和必要的 petcore 工具检查，不把旧实现测试纳入验收。

## 一、核心特性

本轮增加“摸头互动”：鼠标在角色头部区域内连续往返晃动时，桌宠在可交互空闲状态播放一个合格的单次动画。默认使用当前角色的 `TOUCH_BODY + SINGLE` 动画；用户也可以按宠物 slot 选择自定义动画，或选择全部合格单次动画。隐藏、click-through、拖拽、投掷、动作接管、切换角色、关闭窗口时均不会触发或残留迟到动作。

**不变量**：不新增动画引擎、后台线程、Qt 定时器、网络请求或磁盘写入；动画仍经现有 `PetWindow._play_spec()` 链路播放，`head_box` 缺失时才回退到 `body_box`。

## 二、修改文件说明

以下增删来自本轮代码/测试/文档修改的 `git diff --numstat`；两个新文件在报告生成时仍为未跟踪文件，因此同时列出实际行数。

### 实现

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `petcore/engine/head_pat.py` | +167 / −0（新文件，未跟踪） | 提供无 Qt 的 `HeadPatTracker`、候选动画过滤、三种动画池和避免连续重复的选择器。 |
| `petcore/config.py` | +31 / −0 | 增加 `head_pat_enabled`、动画模式和名称列表默认值、归一化、数量/长度限制。 |
| `petcore/ui/pet_window.py` | +89 / −1 | 启用鼠标跟踪，使用逻辑坐标和 `head_box` 命中，接入忙碌状态/lifecycle 清理和 `head_pat` 播放入口。 |
| `petcore/ui/settings/page_interaction.py` | +202 / −0 | 在现有互动/动画设置页增加开关、模式、多选列表、全选/恢复点击/清空，并实现实时应用与取消恢复。 |
| `docs/PETCORE-SPEC.md` | +2 / −1 | 将 `head_box` 和摸头互动写入 Core 能力与交互契约。 |
| `docs/PETCORE-ROADMAP.md` | +9 / −0 | 区分已实现、petcore 自动化通过和 Windows 实机未验证。 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---:|---|
| `tests/test_petcore_head_pat.py` | +137 / −0（新文件，未跟踪） | 轨迹阈值、反向移动、离开/冷却/超时、三种动画选择、非法名称和不连续重复、配置归一化。 |
| `tests/test_petcore_interaction.py` | +71 / −1 | `head_box` 命中、鼠标跟踪、透明/忙碌/click-through 抑制和 `head_pat` 动作入口。 |
| `tests/test_petcore_settings.py` | +43 / −1 | 设置默认值、实时修改、slot 配置快照和 Cancel 恢复。 |

### 文档与证据

| 文件 | 增删 | 改动意图 |
|---|---:|---|
| `docs/PETCORE-LOG.md` | +14 / −0 | 新增 L080 变更记录。 |
| `docs/PETCORE-LOG-INDEX.md` | +1 / −0 | 登记 L080。 |
| `docs/INDEX.md` | +1 / −0 | 登记本报告。 |
| `docs/PR-REPORT-PETCORE-HEAD-PAT-2026-10-25.md` | 新文件 | 保存本轮实现、测试、性能和验证缺口。 |

**故意未改动**：旧 `pet/`、菜单覆盖表、动画播放器、角色素材格式和依赖声明。因为本功能已有 `head_box`、`GraphCatalog`、`AnimationPlayer`、`PetWindow` 链路可复用，不需要第二套实现。

## 三、实现要点

1. `HeadPatTracker.update()` 只接收 `(x, y)`、`inside_head`、注入的 `now` 和 eligibility，不读取 Qt 时钟，也不使用 `sleep`。单段有效移动至少 4 px，累计至少 14 px，且至少有一次方向点积 `<= -0.25`；轨迹超过 1.2 秒或离开头部立即清空，成功后保留当前点并进入 0.65 秒冷却。
2. 候选动画只接受 `AnimatType.SINGLE`，排除 `EVENT`、`IDEL`、`MOVE`、`RAISED_STATIC`、`RAISED_DYNAMIC`；`default_click` 选择 `TOUCH_BODY`，`custom` 过滤配置中的稳定名称，`all_single` 使用全部合格候选。多候选时不连续选择同名动画。
3. `PetWindow` 使用现有 `_unsquash_point()`、`_unrotated_point()` 和透明像素判断，避免透明画布误触发；`_head_local` 缺失时回退 `_body_local`。动作、拖拽、投掷、隐藏、关闭、切换角色和 click-through 状态均复用现有生命周期清理点。
4. 设置控件直接写入当前 slot 的运行时配置；页面快照包含三个摸头键，Cancel/Esc/关闭恢复快照，保存沿用现有配置持久化路径。没有新增菜单入口。

## 四、性能分析

**测试命令与环境**：Windows PowerShell；Python 3.11 项目虚拟环境 `.venv`；`QT_QPA_PLATFORM=offscreen`；纯逻辑基准使用 `.venv\Scripts\python.exe -`，设置循环使用同一进程的 `QApplication` 和 `SettingsDialog`。

| 指标 | 实测 | 归属 |
|---|---:|---|
| `HeadPatTracker.update()` | 100,000 次 / 0.042175 s = 2,371,061.67 events/s，0.422 µs/event | 鼠标移动热路径 |
| 设置开关/模式切换 | 30 个循环 / 0.235223 s = 7.841 ms/cycle | 设置页新增路径 |
| 新增线程 | 0 | 设计约束 |
| 新增 Qt 定时器 | 0 | 设计约束 |
| 新增网络请求 | 0 | 设计约束 |
| 新增磁盘写入 | 0（鼠标移动期间） | 设计约束 |

**结论**：摸头判断是已有 `mouseMoveEvent` 中的常量级状态更新；没有轮询线程或定时器，所以稳态资源开销不增加。设置列表只在页面刷新/角色变化时重建；30 次切换未观察到异常退出或资源错误，但本轮没有做进程级内存 profiler，因此不将其写成“无泄漏”结论。动画播放仍由既有播放器承担，摸头功能不增加解码进程或后台任务。

## 五、实机运行记录

### 已执行的本机真实命令

- `.venv\Scripts\python.exe -m petcore --check`：返回码 **0**；输出的角色探针包含 `head_box: [185, 60, 436, 195]`，`diagnostics` 为空。
- `.venv\Scripts\python.exe -m ruff check petcore tests scripts`：输出 **All checks passed!**。
- 真实 Windows Python 进程执行 100,000 次 tracker 基准和 30 次设置切换，输出见“性能分析”。

### 未执行的真实桌面行为

本机本轮没有启动真实桌面窗口进行鼠标人工操作，因此以下项目标记为**尚未验证**，不是自动化通过：头部实际视觉命中、单向移动不触发、click-through、拖拽/投掷不中断、两个 slot 的可视化隔离、退出后无迟到动画。原因是本轮验证环境仅按计划使用 offscreen Qt 和隔离的 Core 检查，未进行桌面交互探针；不能把 offscreen 事件测试冒充 Windows 实机证据。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 摸头/交互聚焦 | `.venv\Scripts\python.exe -m pytest tests/test_petcore_head_pat.py tests/test_petcore_interaction.py -q` | **24 passed / 1.10s** |
| 设置聚焦 | `.venv\Scripts\python.exe -m pytest tests/test_petcore_settings.py tests/test_petcore_settings_close.py tests/test_petcore_settings_coverage.py -q` | **34 passed / 6.37s** |
| petcore 全部测试 | PowerShell `$files = Get-ChildItem tests -Filter 'test_petcore_*.py' ...; .venv\Scripts\python.exe -m pytest $files -q` | **1490 passed / 130.18s / exit 0** |
| 静态检查 | `.venv\Scripts\python.exe -m ruff check petcore tests scripts` | **All checks passed!** |
| Core 检查 | `.venv\Scripts\python.exe -m petcore --check` | **exit 0** |

未运行旧 `pet` 实现整仓测试；这符合本轮明确的验证范围，不代表旧实现测试已验收。

## 七、已知限制与后续

- Windows 真实桌面摸头、click-through、拖拽/投掷和双 slot 交互尚未验证；建议在隔离配置目录启动源码后按本报告的边界逐项人工验证。
- 本轮没有安装 PyInstaller，也不涉及冻结包、安装器、Release 或 CDN。
- 本轮没有新增“节奏/灵敏度”设置；判定阈值固定在计划确定值，后续若要开放调节应先补配置迁移和设置契约评审。
- 角色若没有合格单次动画，摸头不触发并通过既有诊断节流记录，不伪造可播放状态。

## 八、风险与回滚

新增配置键有默认值，不提高 schema 版本；旧配置加载后自动补默认值。回滚代码后，新配置键会被旧代码忽略，原配置文件仍可保留；若需要清理，仅应在用户确认后删除对应键，不自动删除用户数据。代码回滚使用 `git revert` 或丢弃本轮未提交差异，不触碰旧 `pet`、角色素材和已有动画数据。
