# petcore mod 格式

> 基线：`feat/petcore-vpet-architecture`，2026-10-20。首版实现 content 与 feature 两类包；feature 仅在内置演示与显式开关下加载。

## 1. 目录

```
mods/<id>/
  mod.json              必需
  ...                   包内资源
```

`mods/<id>/mod.json`：

```json
{
  "schema": 1,
  "id": "character.shenshen",
  "kind": "content",
  "name": "Shenshen",
  "version": "1.0.0",
  "api_version": "1",
  "core_requires": ">=0.1.0,<1.0.0",
  "author": "example",
  "character": {
    "media": "videos",
    "canvas": [640, 360],
    "feet_y": 330,
    "body_box": [212, 60, 428, 330],
    "head_box": [185, 60, 436, 195],
    "move_strides": "videos/move_strides.json",
    "text_clips": "videos/text_clips.json"
  }
}
```

feature 包额外字段：

```json
{
  "kind": "feature",
  "execution": "host-only",
  "entrypoint": "host/__init__.py:create_host",
  "capabilities": ["sound.play"],
  "requires": ["character.shenshen"]
}
```

## 2. 字段

| 字段 | 必需 | 规则 |
|---|---|---|
| `schema` | 是 | 必须为 `1` |
| `id` | 是 | `^[a-z0-9][a-z0-9._-]{0,127}$`，全局唯一 |
| `kind` | 是 | `content` 或 `feature` |
| `name` | 是 | 展示名（英文/原名） |
| `name_zh` | 否 | 中文展示名（≤128；缺失/非法回退 `name`） |
| `version` | 是 | `X.Y.Z` |
| `api_version` | 是 | 首版只接受 `"1"` |
| `core_requires` | 否 | 逗号分隔的 `>=`/`<=`/`>`/`<`/`==` 约束 |
| `author` | 否 | 文本 |
| `execution` | feature 必需 | `host-only` 或 `worker` |
| `entrypoint` | feature 必需 | 包内相对路径 `path.py:function`；也支持包入口 `host/__init__.py:create_host`（loader 以包方式加载，允许相对 import） |
| `capabilities` | 否 | 必须属于 `contracts/capabilities.py` 的清单 |
| `character` | content 可选 | 角色块，见 `PETCORE-CHARACTER-PACKS.md` |
| `sounds`/`themes`/`phrases`/`seasonal` | 否 | `{id: 相对路径}` 的内容贡献 |

未知顶层字段产生诊断但不阻断加载。

## 3. 校验

- 路径：所有声明的路径必须解析在包内；拒绝绝对路径、`..` 逃逸、解析到包外的符号链接。
- content 包不得包含可执行文件：`.py .pyc .dll .so .dylib .exe .js .bat .cmd .ps1`。
- feature 包必须提供包内入口；绝对路径与包外路径一律拒绝。
- `api_version` 大版本不匹配 → 该包停用并给出诊断，不影响其他包。
- 单个包的任何异常都转成 `ModDiagnostic`，绝不阻断 core 启动。

## 4. 发现与启停

- 扫描顺序：用户数据目录 `mods/` → 安装目录 `mods/`（仅冻结包）→ 仓库 `mods/`；按
  `(id, path)` 排序，结果确定。
- 同 id 后加载者覆盖前者，并记录冲突诊断。
- `mods-state.json` 只保存停用集合；文件缺失按“全部启用”。
- 停用不移动文件、不删数据；卸载只删除用户目录下的包目录，绝不动安装目录/仓库
  `mods/`。
- feature 包只在 `allow_feature_mods` 为真、且位于用户数据目录或安装目录 `mods/`
  时加载；安装器投放的包由同目录 `.trusted` 逐包授权。

## 5. 贡献与合并

content 贡献类型：`character`、`sound`、`theme`、`phrases`、`seasonal`。

合并规则：

- 同 id 的角色包：后加载者覆盖同一动画键，其余键保留；
- 音效/主题/台词：同 key last-wins；
- 冲突写诊断，不静默。

### 5.1 菜单贡献

feature 包通过 `Contribution(kind="menu")` 注册菜单项，`data` 支持：

```json
{"label": "打个招呼", "command": "hello", "section": "extensions", "order": 55, "icon": "chat"}
```

- 动作 id 在 Core 内统一为 `<owner>:<contribution>`，避免跨包冲突。
- 未在用户菜单布局中出现的贡献项会**自动进入「扩展」子菜单**；用户可在设置 →「菜单」里把它拖到根或其它子菜单、改名、换图标、隐藏。
- 卸载后该项从菜单消失但布局节点保留为未知；重装即可恢复，编辑器也提供清理入口。
- `command` 必须存在于该包 runtime 的 `commands` 字典；缺失时点击只记诊断，不影响菜单构建。

## 6. 安装

```
python -m petcore mods install <目录或.zip> [--force]
python -m petcore mods list
python -m petcore mods validate <路径>
python -m petcore mods enable <id>
python -m petcore mods disable <id>
python -m petcore mods remove <id>
python -m petcore mods doctor
```

`--root <数据目录>` 可以写在 `mods` 前面（`petcore --root D:/pets mods list`）或后面；
前置时 `main()` 先解析全局选项再统一下发根目录。`--portable` / `--instance` 同样可前置。

安装流程：校验 manifest → staging 目录 → 校验内容摘要 → 原子改名到 `mods/<id>`；目标已存在时拒绝，`--force` 才替换（旧目录先移入 `.trash-*`）。ZIP 安装拒绝 zip-slip。

### 6.1 授信标记 `.trusted`

功能包默认需要用户打开「允许功能扩展」（`allow_feature_mods`）。Windows 安装向导
投放的官方扩展走**逐包授权**：装到安装目录 `{app}\mods\<id>`，目录里放一个
`.trusted` 空文件即视为已授信（`petcore/mods/trust.py`），与全局开关并列；不勾选
安装就不会有目录，卸载随 `{app}` 一起删除。这类包在扩展管理里归「加装扩展」，
标「随安装包」，不能在设置里卸载。用户自己导入的包仍装到数据目录 `mods/`，同样归
「加装扩展」，可单独卸载。

### 6.2 市场安装

`petcore market install` 与设置页「插件市场」走同一套 `petcore/market/` 模块：索引
元数据、下载、SHA-256 校验、备份、原子替换与回滚。市场安装的包同样落用户数据目录
`mods/<id>`，feature 包仍受 `allow_feature_mods` 约束，不会因为来自市场就自动授信。
索引格式、来源缓存、回滚与生效语义见 [`PETCORE-MARKET.md`](PETCORE-MARKET.md)。

## 7. 能力与边界

能力是**声明 + 用户授权**，不是沙箱。首版不提供：

- 第三方代码的默认执行；
- Python 模块热卸载；
- worker 监管（协议已定义，实现留给 P1/P3）；
- 签名与沙箱；在线更新与多源下载见 [`PETCORE-MARKET.md`](PETCORE-MARKET.md)。

## 8. 内置 feature 与端口（P2）

- 内置包位于 `petcore/builtin/features/<id>/`，格式与用户 feature 包相同；由 `FeatureManager.load_builtin_features()` 扫描加载，**受信任**，不要求 `allow_feature_mods`。
- 内置包只保留与 core 交互强相关的 7 个：`fun.self-talk`、`fun.click-talk`、`tool.quick-launch`、`tool.quiet-mode`、`tool.links`、`tool.memory-trim`、`tool.network-info`。P8 起这 7 个是 **Core 内置特性**（`CORE_FEATURE_IDS`，group=`core`）：无条件加载，不参与安装/停用/卸载，设置页按 `host_page` 内嵌到 Core 页，不再出现在扩展管理导航。
- 其余 `fun.divination`、`fun.festival`、`reminder.todo`、`voice.chime`、`media.music` 是**可导入样板**，位于 `examples/petcore-mods/`；用 `petcore mods install <目录>` 安装到用户数据目录，并开启 `allow_feature_mods`。安装后由 `FeatureManager` 从用户 mods 目录加载，菜单贡献默认进入「扩展」子菜单。Windows 安装向导勾选安装时落 `{app}\mods\<id>`，归「加装扩展」。
- 设置页不再各自占侧边栏：第三方 mod 的 `settings_page` 进入「扩展管理」页内导航；Core 内置特性用 `Contribution.data["host_page"]` 声明归属（`interaction` / `menu` / `about`），由对应 Core 页内嵌，见 §9。
- `HostPorts` 新增：
  - `pets`：只读宠物句柄（body_rect / velocity / move_by / show / hide / say / play_animation / play_event）；
  - `presentation`：`say` / `show_image` / `play_animation` / `play_event` / `notify`；
  - `interaction`：`on_click`、`on_drop`、`on_tick`、`cancel_owner`；`on_drop` 回调收到的是
    **已投喂的文件路径列表**（Core 先做投喂动画与统计，再通知监听者；`file_feeding_enabled`
    关闭时不会有 drop 事件）；
  - `http`：普通取数端口（见 §11）；
  - `quiet`：进程级免打扰。
- `FeatureContext.host` 暴露宿主对象，mod 可读取共享配置；跨域仍走端口/事件，不直接 import `pet.*`。
- 每个有菜单贡献的内置 mod 必须提供 `settings_page`；`tests/test_petcore_builtin_mods.py` 守住。
- 内置包当前清单：`fun.self-talk`、`fun.click-talk`、`tool.quick-launch`、`tool.quiet-mode`、`tool.links`、`tool.memory-trim`、`tool.network-info`。
- 示例可导入包：`examples/petcore-mods/{fun.divination,fun.festival,reminder.todo,voice.chime,media.music,tool.weather,tool.file-reader}`；`examples/petcore-mods/README.md` 是安装与端口样板说明。


## 9. Core 内置特性与 `host_page`（P8）

内置包的 `settings_page` 贡献可以多写一个 `host_page` 字段，声明它的设置内容应该
内嵌到哪个 Core 设置页，而不是出现在「扩展管理」：

```json
{"kind": "settings_page", "id": "page", "data": {
  "title": "点击台词", "order": 610, "host_page": "interaction"
}}
```

| `host_page` | Core 页 | 当前使用方 |
|---|---|---|
| `interaction` | 互动与物理 | `fun.click-talk`、`fun.self-talk`、`tool.quiet-mode` |
| `menu` | 菜单 | `tool.quick-launch` |
| `about` | 关于与诊断 | `tool.links`、`tool.network-info`、`tool.memory-trim` |

规则：

1. `CORE_FEATURE_IDS`（`petcore/mods/feature.py`）里的包 group 固定为 `core`：
   无条件加载、不可停用/卸载、不进扩展导航。
2. 有 `host_page` 的 `settings_page` 由 `FeatureManager.embedded_pages(host_page)`
   返回，Core 页负责 `prepare_embedded()` 与生命周期（保存/取消/释放）。
3. 第三方 mod 不要写 `host_page`：它们仍应只出现在「扩展管理 → 加装扩展」。
4. 新增 Core 内置特性时必须同时补：`CORE_FEATURE_IDS`、`host_page`、
   `tests/test_petcore_builtin_mods.py` 的映射断言。

## 10. P3 端口：对话、截图与 AI 扩展示例

P3 新增两条 mod 可见端口，AI 执行放在 mod，传输与窗口留在 Core：

| 端口 | 能力 | 谁实现 |
|---|---|---|
| `HostPorts.chat`（`ChatPort`） | `open/append/token/done/error/close/cancel/is_open/history` + `on_submit/on_stop` | `petcore/ui/chat/controller.py` |
| `HostPorts.screen`（`ScreenPort`） | `capture(pet_slot=...) -> ScreenCapture(png, width, height, screen_name)` | `petcore/platform/screenshot.py` |
| `HostPorts.api`（扩展） | `stream_chat(service_id, messages, *, model, temperature, timeout, on_delta, cancel)` | `petcore/api/chat.py` |

约定：

1. **mod 不碰 Qt**：聊天窗口由 `ChatPort` 驱动；`token/done/error` 可以从后台线程调用，
   controller 用 Qt 信号排队到 GUI 线程。`petcore/chat/` 保持 Qt-free（架构守卫）。
2. **传输只在 core**：SSE、代理兜底、取消与错误分类都在 `petcore/api/chat.py`；
   扩展不得 import `petcore.net`/`petcore.api`（`test_mods_use_ports_not_core_transport`）。
3. **截图不落盘**：`ScreenCapture.png` 是内存字节；转 data URL 由调用方自己做
   （示例用标准库 `base64`），Core 不写临时文件、不记录正文。
4. **流式回调线程**：`on_delta` 在请求线程里执行，只做入队/信号，不能直接改控件。
5. **停止语义**：`ChatPort.on_stop` 收到停止后置位自己的 `threading.Event`，
   下一次 `stream_chat` 检查取消并返回 `cancelled=True`。

### 参考实现：`examples/petcore-mods/ai.chat`

```text
mod.json           kind=feature, execution=host-only,
                   capabilities=[network.request, screenshot.capture,
                                 speech.present, settings.read, settings.write]
host/__init__.py   create_host：只做 FeatureDefinition 组装
host/constants.py  OWNER / 历史上限 / 看看屏幕冷却
host/prompts.py    默认人格、识屏/截图话术、消息组装纯函数
host/runtime.py    三条命令 open / look_screen / screen_capture；
                   注册 chat.on_submit / on_stop / screen_ask.on_ask；
                   只经 ports.config 读配置、ports.scheduler 回 GUI 线程（无 Qt）
host/settings_page.py  设置页（受信 UI，允许 QtWidgets）
```

`runtime.py` 不得 import PySide6；设置页是唯一允许 Qt 的运行位置。

安装：`petcore mods install examples/petcore-mods/ai.chat`（或安装向导勾选，默认不勾）。
没有安装时，右键菜单与三条热键会气泡提示「AI 扩展未安装」，不会静默无响应。

## 11. P4 端口：通用取数 `HttpPort`（2026-10-22）

天气、歌词这类「普通 HTTP GET」原先没有入口：mod 只能拿 `ApiPort`（LLM 专用），
而网络库按架构守卫禁止出现在 mod 里。P4 增加 `HostPorts.http`：

| 端口 | 方法 | 说明 |
|---|---|---|
| `HttpPort` | `request(HttpRequest) -> HttpResponse` | 唯一取数入口；失败抛 `HttpError(reason)` |
| `HttpPort` | `get_json(url, *, timeout, headers, params, prefer_direct)` | 便利方法；解码失败统一 `protocol` |

`HttpRequest` 关键字段：

- `prefer_direct`：`False` 先走系统代理，`True` 先直连（国内站点口径）。
- `retry_statuses`：允许换路由的服务器明确答复，默认 `(500, 502, 504)`；404/429/503
  与带 `Retry-After` 的响应**不换路由**。
- `params`：查询串键值对，百分号编码由 Core 做（mod 不需要 `urllib.parse`）。
- `max_bytes`：响应体硬上限，默认 4 MB；超出部分截断，由调用方按协议判无效。

错误只暴露 `HttpError.reason`（`auth/rate_limit/network/timeout/protocol`）、
`status`、`retry_after`；异常链与响应体不外泄（响应体可能回显密钥）。

**硬规则**：

1. 两条路由共享同一个 `timeout` 预算，最多各试一次；显式路由请求**不改写**进程级
   「固定直连」结论（天气是国内直连、海外代理，一次失败不能污染其它域）。
2. mod 不得 import `petcore.net`/`petcore.api`/`petcore.account`；`urllib` 等网络库
   仍然只允许出现在这三个包（`tests/test_petcore_architecture.py`）。
3. 新增取数功能时先想清楚路由：国内源 `prefer_direct=True`，海外源用默认值。

### 参考实现：`examples/petcore-mods/tool.weather`

```text
mod.json               capabilities=[network.request, speech.present]
host/logic.py          城市名/地区码/两源解析/WMO 码表/失败文案（纯逻辑）
host/client.py         两源取数：CN 直连 → open-meteo 代理，6s/请求 + 15s 总预算
host/runtime.py        命令 show：后台线程 → 气泡；运行时无 Qt
host/settings_page.py  启用、城市列表、当前城市、立即查看
```

### 参考实现：`examples/petcore-mods/tool.file-reader`

```text
mod.json               capabilities=[files.read, network.request, speech.present]
host/reader.py         后缀白名单、20000 文件/2s 扫描预算、200000 字符有界读取
host/runtime.py        interaction.on_drop → 后台 stream_chat → 气泡 + ChatPort.record
host/settings_page.py  启用、进度间隔（5–120s）、是否写入聊天记录
```

`files.read` 是 P4 新增的能力声明（读取用户拖入的任意文本文件）；它同样只是声明，
不是沙箱。文件解读**只读**：不修改、不移动、不删除被拖入的文件，路径不写日志正文。
