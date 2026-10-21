# petcore P6：动画节拍、事件动画与 core 联网 / API（2026-10-20）

> **基线**：`feat/petcore-vpet-architecture`（P5 收口，本地未提交）
> **分支**：`feat/petcore-vpet-architecture`　**日期**：2026-10-20
> **范围**：动画播放链、行为权重、事件动画、core `net/` 与 `api/`、设置页与打包依赖
> **关联**：[`PETCORE-LOG.md`](PETCORE-LOG.md) L016–L019、[`PETCORE-SPEC.md`](PETCORE-SPEC.md) §10

## 一、核心特性

修掉「桌宠几乎一直待机」：真实角色包（shenshen，106 个 clip）上复现出
`Default/Single 95`（random 89 + events/balance 6）、`Idel/B_Loop 1（loop=True）`。
`_on_finished()` 先调用 `AnimationPlayer.advance()`，而 `B_LOOP + loop=True` 会**原样
返回同一个 idle spec**，于是待机自己续自己，掷骰链只在点击/拖拽/手动播放后才被走到。
主分支的语义是「待机播完一圈 → 掷骰」。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 待机掷骰 | IDEL 圈末直接 `_roll_next()`；60s/2x offscreen 探针得到 `idle 3 / act 3 / move 1 / turn 2` |
| 2 | 可调概率 | 设置「互动与物理 → 自主行为概率」四项百分比，默认 30/10/40/20，归一化，0 表示从不 |
| 3 | 动画间隔 | `animation_gap_seconds` 改为「间隙继续播待机、到点掷骰」，不再冻在末帧 |
| 4 | 同 clip re-arm | 重播同一可循环 clip 只 `start()`，不 `stop()`，避免 WebMClip 硬停换代 |
| 5 | 手动播放菜单 | 「播放动画」按待机/转向/移动/点击回应/随机动作/事件分组，播完回掷骰链 |
| 6 | 事件动画 | `events/<group>/` → `GraphType.EVENT` + `event_group`；`play_event()` 按名字/索引；余额 6 个不再混进随机动作 |
| 7 | core 联网 | `petcore/net/`：系统代理失败自动直连并固化、五类失败分类；架构守卫改 allowlist |
| 8 | core API | `contracts/api.py` + `petcore/api/`（规格/`api.json`/钥匙串/探测）+ 设置页「API 与账户」+ `HostPorts.api` |

**红线 / 不变量**

- `IDEL` 仍用 `B_LOOP + loop=True` 素材；`AnimationPlayer` 的 A_START→B_LOOP→C_END
  链语义不变（单测未改）。
- 菜单/设置一一对应：新增 `api_settings` 已登记 `coverage.py`。
- 网络库只出现在 `net/`、`api/`、`account/`；mod 不得 import 这三个包。
- 密钥只进系统钥匙串；`api.json` 与 `config.json` 都不含 API Key。

## 二、修改文件说明

### 实现

| 文件 | 改动意图 |
|---|---|
| `petcore/ui/pet_window.py` | 待机圈末掷骰、gap 重写（时间戳 + 待机循环）、同 clip re-arm、`play_animation` 按 Graph 映射类型、`play_event()`、权重 provider |
| `petcore/engine/behavior.py` | `DEFAULT_WEIGHTS`、`normalize_weights()`、`weights_provider`；`choose()` 改累计阈值 |
| `petcore/config.py` | `anim_weight_idle/turn/act/move` 默认值与 0–100 规范化 |
| `petcore/ui/settings/page_interaction.py` | 「自主行为概率」四个 spinbox，改动即写 config、可回滚 |
| `petcore/ui/menu_actions.py` | 「播放动画」分类（含事件组）、新增 `api_settings` 菜单项 |
| `petcore/engine/enums.py` | `GraphType.EVENT` |
| `petcore/contracts/content.py` | `AnimationSpec.event_group` |
| `petcore/content/legacy.py` | `events/` 映射与 `event_group` 解析 |
| `petcore/engine/catalog.py` | `specs_for_event/event_groups/event_names` |
| `petcore/contracts/host.py` | `play_event` 端口、`HostPorts.api` |
| `petcore/contracts/api.py` | `ApiMetadata/ApiRequest/ApiPort`（stdlib） |
| `petcore/net/http.py`、`errors.py`、`__init__.py` | 唯一网络出口：代理兜底与稳定错误分类 |
| `petcore/api/spec.py`、`store.py`、`credentials.py`、`probe.py` | 服务校验、`api.json` 原子写、钥匙串、文本探测 |
| `petcore/ui/settings/page_api.py` | 「API 与账户」设置页（服务/密钥/测试连接） |
| `petcore/ui/settings/dialog.py` | 注册第 8 页，侧边栏 7→8；保存门：页面 `confirm_save()` 返回 False 时不关闭对话框 |
| `petcore/ui/settings/coverage.py` | `api_settings → ("api", "服务与密钥")` |
| `petcore/ui/ports.py` | `CoreApiPort`、`build_ports` 注入 `api/credentials` |
| `petcore/ui/app.py` | `CoreHost` 共享 `ApiStore/KeyringCredentials`；`play_event` 适配 |
| `petcore/ui/icons.py` | 新增 `network` 图标 |
| `petcore/menu_templates/petcore-default-v1.json` | 「工具与帮助」加「API 与账户」 |
| `scripts/build_petcore.ps1` | 收集 keyring Windows 后端与 `win32ctypes` |

### 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_petcore_playback.py`（新） | 待机圈末掷骰、gap 行为、re-arm、权重、`play_event`、设置页四项 |
| `tests/test_petcore_net.py`（新） | 代理兜底/固化/复位、HTTPError 不重试、错误分类 |
| `tests/test_petcore_api.py`（新） | endpoint 校验、store 无密钥、keyring 兜底、probe 映射、设置页 smoke |
| `tests/test_petcore_behavior.py` | 权重归一化与自定义分布 |
| `tests/test_petcore_settings.py` | 8 页与搜索索引跟随 |
| `tests/test_petcore_architecture.py` | 网络 allowlist + mod 不得 import core 网络/API |

### 未改动（故意）

- `pet/` 产品代码一行未改；`AnimationPlayer.advance()` 语义保持原样（由 UI 状态机
  选择何时掷骰）。
- `events/balance` 的档位选择仍等 account/余额 mod；本批只提供 `play_event` 入口。

## 三、实现要点

- **待机节拍**：`_is_idle_dwell()` 只对「kind=idle ∧ Graph=IDEL ∧ B_LOOP ∧ loop」
  生效；否则仍走 `advance()`，保证 A_START/B_LOOP/C_END 链不被破坏。
- **gap**：动作结束记 `_gap_until = monotonic()+gap` 并立刻播待机；待机圈末若
  `_gap_active()` 就再播一圈，否则清空并掷骰。点击/拖拽/换角色取消 gap。
- **re-arm**：`_play_spec()` 在 `self._clip is clip and state.current is spec and
  kind 相同` 时只 `start()`；WebMClip 圈末已驻留，软停语义保持不变。
- **权重**：`normalize_weights()` 把负数/NaN/非数字归零，全 0 回默认；`weights_provider`
  每次掷骰读 config，设置改动下一次掷骰即生效（无信号接线）。
- **事件动画**：`events/<group>/` 只映射为 EVENT，`act()` 仍只取 DEFAULT，因此
  `random/` 与 `events/` 彻底分流；`play_event` 支持名字/目录前缀/排序索引。
- **联网**：沿用主分支 `http_util` 的口径（代理先试、传输失败改直连并固化、
  `HTTPError` 原样抛）；分类只暴露 `auth/rate_limit/network/timeout/protocol`。
- **密钥**：`ApiService` 没有 key 字段，`ApiStore` 方法签名里也没有；`KeyringCredentials`
  先写内存镜像再写钥匙串，失败降级为内存并在设置页说明；`ApiRequest` 的 key
  标 `repr=False`。

## 四、性能分析

- `BehaviorDirector.choose()`：**7.23 µs/次**（shenshen 106 clip，100k 次，
  `timeit`，Python 3.13.7 / 本机 Win11）。掷骰每 5–10s 一次，增量可忽略。
- `normalize_weights()`：**0.77 µs/次**；`_roll_next` 每次多一次该调用。
- 60s/2x 播放探针期间无异常日志、无新增线程；WebMClip 解码进程数与 P5 相同
  （每条 clip 一条，未因 re-arm 增加）。
- `api.json` 写入沿用 `mkstemp + os.replace`，只在设置页显式保存时发生；探测在
  `QThreadPool` 线程里跑，不占 GUI 线程。

## 五、实机运行记录

- 环境：Windows 11，Python 3.13.7，PySide6，`QT_QPA_PLATFORM=offscreen`。
- 真实素材（shenshen）：`Default 89 / Event 6 / Touch_Body 5 / Move 4 / Idel 1 /
  Raised_Static 1`；`event_groups() == ("balance",)`。
- 60s/2x 播放探针（`.scratch/p6_play_probe.py`）：状态切换 9 次
  `idle 3 / act 3 / move 1 / turn 2`；此前 25s 探针修复后也能从 idle 进入 move。
- 真实 Windows 钥匙串：`available=True`；`set("sk-test-123") → get 相同 →
  persisted=True → delete → get None`。
- `api.json` 探针：文件只含 `schema_version/version/services{...}`，无密钥；
  `CoreApiPort.resolve()` 拿到 9 位密钥但 `repr(ApiRequest)` 不含密钥。
- 门禁：`733 passed, 5 skipped`；`ruff check pet/ tests/ petcore/` 全绿；
  `petcore --check` 退出码 0。
- 打包：`dist/dsh-pet-core-setup.exe` 185,100,188 字节；主 exe `Subsystem=2`（windowed，
  无终端窗）；`--check` 退出码 0；冻结包 PYZ 内含 `keyring.backends.Windows`、
  `win32ctypes.pywin32.win32cred` 等 60+ 模块（`pyi-archive_viewer` 展开核对）。
- **未验证**：真实 HTTPS 端点与 `verify_ssl=False` 的自签握手；真实桌面下 gap
  手感与 ffmpeg 进程稳定性；打包版在真实 Windows 上调用钥匙串（模块已收集，未实点）。
