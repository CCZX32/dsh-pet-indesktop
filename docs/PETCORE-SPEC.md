# petcore 最终形态规格（SPEC）

> 基线：`feat/petcore-vpet-architecture`，2026-10-20。
> 本文回答「这个项目最终要做成什么样」。实现进度、批次与未验证项见
> [`PETCORE-ROADMAP.md`](PETCORE-ROADMAP.md)；每次改动的记录见
> [`PETCORE-LOG.md`](PETCORE-LOG.md) 与 [`PETCORE-LOG-INDEX.md`](PETCORE-LOG-INDEX.md)。

## 1. 一句话目标

把 dsh-pet 从单体的 `pet/` 包重构成 **一个可独立运行的 core + 一组可插拔 mod**：
core 负责生命周期、窗口、动画、菜单/设置宿主与扩展运行时；角色素材、功能域、
平台能力都以内容包或 mod 的形式接入。最终发布入口切换到 petcore，`pet/` 收敛为
兼容层并删除。

## 2. 最终用户看到什么

一个桌宠应用，至少具备：

- **桌宠本体**：透明无边框窗口、逐像素点击、拖拽、滚轮缩放、右键菜单、托盘、
  气泡、多屏归属与热插拔恢复；贴边按角色身体框，不按动画画布。
- **边缘探头**（P1-F）：贴到屏幕左右缘后自动 45° 部分出屏（默认约 55% 投影
  宽度，实机为头/上半身）；点击拉直，5 秒后回到探头姿态；拖拽/关闭开关立即取消。
- **角色与素材**：内置角色；用户可导入角色资源包（`pack-character` 生成 content
  mod）；WebP 帧序列 / WebM / GIF 三条素材路线都能被 core 消费；后续可增加 PNG
  序列等后端。
- **设置**：非模态设置窗口；核心设置实时反馈到桌宠；保存落盘、取消回滚；
  支持搜索；菜单编排、扩展管理、诊断与关于。
- **扩展**：内置 demo + 用户 mods 目录；内容包（角色/音效/台词/主题）与功能包
  （菜单动作、设置页、行为）分离；无热卸载、无沙箱的诚实边界。
- **功能域**：F01 屏幕理解、F02 AI、F03 Agent、F04 账户、F05 音乐、F06 语音、
  F07 提醒、F08 台词、F09 灵动岛、F10 趣味、F11 快捷启动——**执行**以 mod/worker
  形式接入；F02 AI 与 F04 账户所需的 API 配置、探测、凭据与额度由 core 提供。
- **API 与账户**：设置页「API 与账户」维护服务（Base URL/模型/超时/余额协议）
  与密钥（只进系统钥匙串）；服务规格落 `api.json`，密钥永不写盘；mod 通过
  `ApiPort` 拿不可变快照，不接触存储实现。
- **快捷键/自启**：可配置的「显示/隐藏桌宠」全局快捷键；Windows 开机自启开关与
  `petcore autostart status`。
- **多宠/多实例**：多实例（`--instance NAME`）各自独立数据根与 lock；单进程多宠由
  `PetManager` 提供 slot 0 主宠 + slot 1–15 子宠，每宠独立配置与碰撞。

## 3. 架构目标

```text
petcore/
  engine/      纯逻辑：枚举、几何、动画链、行为、位移、状态（禁 Qt）
  contracts/   端口与数据契约（只用标准库）
  net/         唯一联网出口：代理兜底、失败分类（标准库）
  api/         API 服务规格、探测、凭据端口实现（密钥只进钥匙串）
  account/     账户与额度（H7 落地，网络同样只经 net/）
  media/       Clip 后端、库、fallback、音效（唯一允许适配 pet.* 媒体实现的层）
  content/     旧素材只读适配、mod 内容、收集、打包（legacy.py 允许 import pet.*）
  mods/        manifest、发现、启停、安装、feature 宿主、CLI
  platform/    Windows 输入、屏幕几何、会话、开机自启
  ui/          窗口、渲染、气泡、托盘、菜单模型/布局/编辑器、设置
  cli.py       启动、--check、mods/pack 子命令
```

依赖方向是单向的：`ui → engine/contracts/media/content/mods/platform`；
`engine` 与 `contracts` 不知道 Qt，也不知道 `pet`。跨域联动只走端口、事件与
能力检查。

### 3.1 Core 必须保留的能力

- 应用生命周期、单实例锁、日志、配置读写与迁移、数据目录。
- 桌宠窗口：透明、置顶、点击穿透、拖拽、逐像素命中、缩放、显示器归属。
- 动画：GraphType/AnimatType 寻址、播放链、行为权重、位移与夹取、fallback。
- 动画节拍：待机一圈结束才掷骰；四项权重（待机/转向/随机动作/漫游）归一化，
  设置页可调。
- 语义事件动画：`events/<group>/` 与随机动作池分离，由 `play_event()` 显式触发。
- 呈现：气泡、托盘、右键菜单、菜单布局解析与编辑、设置宿主。
- 扩展宿主：manifest 校验、发现/启停、feature 端口、内容包收集、诊断。
- **统一联网**：`net/` 是唯一 HTTP 实现（系统代理不通自动直连）；`api/` 提供
  API 服务规格、探测、凭据端口与 `ApiPort`；`account/` 提供账户与额度。
- 最小可用角色与素材 fallback，保证「没有 mod 也能跑」。

### 3.2 不允许放进 Core 的东西

- 具体业务域的执行（AI 对话、识屏、音乐播放、语音合成、提醒、台词库等）——
  仍走 worker 或 mod；core 只提供它们需要的网络/API/账户能力。
- 支付、更新器；任何对 `pet.*` 的反向依赖（`media/` 与 `content/legacy.py` 是
  唯一例外）。
- 键盘/网络库绕开 `net/`：mod 不得 import `petcore.net`、`petcore.api`、
  `petcore.account`，只能拿端口。

## 4. 菜单与设置契约（硬规则）

1. **菜单/设置一一对应**：右键菜单里能看见、能调整的每个 Core 动作，必须在
   设置里有一个可到达的入口。映射表在 `petcore/ui/settings/coverage.py`，
   `tests/test_petcore_settings_coverage.py` 机器校验；`modern_settings` 豁免。
2. **菜单是视图，不是唯一入口**：动作可以在菜单里隐藏，但设置入口必须常驻。
   当前默认菜单隐藏「大小」，设置 →「外观与交互」→「大小」常驻。
3. **设置实时反馈**：影响桌宠外观/交互的设置，改控件即生效；保存只负责落盘，
   取消/关闭恢复打开时的快照。外部副作用（安装 mod、写开机自启）仍按显式保存
   或即时确认执行，并在界面上说明。
4. **非模态**：设置窗口（含「关于与诊断」页）不得阻塞桌宠的拖动、点击与滚轮。
5. **大小范围**：10%–300%，滑条 + 手输百分比 + 四档预设；core 内所有缩放入口
   共用 `clamp_scale()`。
6. **贴边按身体框**：位置钳制、右下角/主屏落位、位置恢复与跨屏迁移一律以角色
   `body_box × scale` 为锚点，窗口透明边允许越界；`body_box` 缺失才回退整窗。
   `head_box` 预留给后续更精细的露头锚点；当前边缘探头以 `body_box` 的旋转投影宽度为准。
7. **搜索是真的搜索**：搜索框的匹配口径包含每个设置行的标题与说明，命中后自动
   切到该页并滚到那一行；只按页面标题匹配不算实现。
8. **页内分页不截断**：标签条放进横向滚动区并带翻页箭头；窗口缩到最小宽度时
   右侧分页必须仍然可达。
9. **子选项跟随父开关**：从属设置（如「点击时跳过点击动画」之于「点击触发黄金
   回旋」）缩进显示，父项关闭时隐藏。
10. **朝向口径**：角色素材原生朝左；`facing == "right"` 才水平镜像（与主分支一致）。
11. **碰边反馈逐次生效**：抛掷/弹射过程中每次「离地→接触」边界都要 Q 弹 + 音效，
    不允许整个会话只触发一次。
12. **气泡贴着角色**：锚点用 `head_box`（回退 `body_box`/整窗），气泡不压住角色、
    不越出可用区；不许再用整窗 `frameGeometry()` 当锚点。
13. **Enter = 保存并退出**：设置窗口里 `Return/Enter` 直接保存关闭，只有多行文本框
    （候选台词等）允许换行。
14. **命令反馈不受免打扰抑制**：`say/notify` 的 `force=True` 只给「用户主动点的命令」；
    自动冒泡（自言自语、提醒）仍受免打扰限制。
15. **菜单勾选必须可见**：勾选项渲染出对勾（QSS 用生成的 check 图片）；勾选项不再
    同时设 icon。
16. **碰撞不能瞬移**：`MotionController.set_velocity()` 切到抛掷前必须把内部坐标重锚到
    窗口当前位置；碰撞位移一律经过身体框钳制。
17. **探头只被真撞击打断**：只有相对接近速度 ≥ `HIT_FEEDBACK_MIN_SPEED`（300px/s）
    才算“真正撞上”：先 `arm_throw_egg()` 再 `cancel("collision", restore=True)`，
    然后完整分离。轻碰或走路宠物蹭上时，探头宠物按无限质量处理，只推开对方，
    不得取消探头、不得把旋转姿态推走。
18. **待机一圈才掷骰**：IDEL 是 `B_LOOP + loop=True`，`_on_finished` 不得用
    `player.advance()` 续播自身；必须在圈末掷骰。四项权重按比例归一化，
    `config.json` 的 `anim_weight_idle/turn/act/move` 可调，0 表示从不。
19. **事件动画独立**：`events/<group>/` 载入为 `GraphType.EVENT` + `event_group`，
    不进随机动作池；余额等事件只能经 `play_event(group, variant)` 触发。
20. **联网只有三个出口**：只有 `petcore/net/`、`petcore/api/`、`petcore/account/`
    可以 import `urllib/http/socket/requests/aiohttp/httpx`；mod 只能拿 HostPorts，
    不得 import 这三个包（`tests/test_petcore_architecture.py` 机器校验）。
21. **密钥不落盘**：API Key 只进系统钥匙串（`KeyringCredentials`），`config.json`
    与 `api.json` 都不含密钥；`ApiRequest.__repr__` 不显示密钥；钥匙串不可用时
    退回进程内存并在界面如实说明。
22. **探头/击飞只播 idle 与转向**：`probe_active` 或击飞彩蛋激活时，所有非
    `IDEL` / `MOVE(in_place)` 的素材一律降级待机；探头会话不翻朝向。
23. **飞行是接管态**：`motion.thrown` 期间不掷骰、不响应左键点击；落地 `stop()`
    后才由 `_on_motion_stopped()` 接回行为链。
24. **探头击飞才授权旋转**：碰撞确认重叠后先 `arm_throw_egg()` 再
    `edge_probe.cancel("collision")`；从探头姿态拖出去甩飞同样授权；低速碰撞没进入
    抛掷时立刻回正。
25. **安装器的扩展装进安装目录**：随附扩展落 `{app}\mods\<id>` 并带 `.trusted`，
    卸载随 `{app}`；用户导入仍落数据目录 `mods/`，可在设置里卸载。
26. **扩展管理用竖向导航与可折叠分组**：`扩展管理` 独立在最上；`基础扩展` 只放
    随程序内置的接缝包；`加装扩展` 放安装向导勾选投放的 `.trusted` 包与用户导入的
    包。组头可折叠，左侧列表独立滚动；mod 优先显示 `name_zh`。
27. **安装向导每次都显示目录页**：`DisableDirPage=no`、`UsePreviousAppDir=yes`；
    检测到同 `AppId` 已安装时预选上次安装路径。不得使用 `DisableDirPage=auto`
    把目录页藏掉，也不得把选装扩展装到用户数据目录。规则出处：
    `packaging/petcore.iss` 顶部注释 + 本条。
28. **Core 内置特性不是可选扩展**：`fun.click-talk`、`fun.self-talk`、
    `tool.quick-launch`、`tool.quiet-mode`、`tool.links`、`tool.memory-trim`、
    `tool.network-info` 由 Core 无条件加载，不参与安装/停用/卸载；它们的
    `settings_page` 通过 `host_page` 内嵌到对应 Core 设置页，不再出现在扩展管理导航。
29. **Core 内置特性设置页归位**：互动与物理（点击台词/自言自语/免打扰）、
    菜单（快捷启动）、关于与诊断（链接与项目/网络信息/回收内存）。新增这类特性
    必须在贡献里写 `host_page`，并由 `tests/test_petcore_builtin_mods.py` 守住。
30. **气泡跟随**：`say()`/`show_image()` 定位后，桌宠每次移动（漫游/拖拽/抛掷/探头）
    都要重排气泡；缩放后重新排。气泡不是一次性快照。
31. **轻碰不改变行为态**：碰撞分离只有在 `impact_speed >= HIT_FEEDBACK_MIN_SPEED`
    时才写速度/切 `thrown`；轻碰只平移位置，并把双方移动计划整体平移继续走。
    拖拽中的桌宠不参与碰撞结算。
32. **菜单模板不能因打包丢失**：`petcore/menu_templates/` 必须随 `--add-data` 打包；
    `load_default()` 有内置兜底常量，`--check` 报告 `menu_template=json|builtin`。
    任何情况下缺模板都不得退化成只剩「设置/退出」两项。

33. **字号与图片大小是全局可调参数**：`ui_font_size`（10–18）作用于设置页、右键菜单
    与彩蛋菜单行；`bubble_text_scale`（50–300%）作用于气泡文字与内边距；
    `easter_egg_image_scale` / `self_talk_image_scale` 只改显示上限，不改源图。
34. **自言自语配图**：`self_talk_image_chance` 0–100（默认 30）决定是否出图；目录空时
    用内置 `assets/big_blue_fat_fish`；出图失败必须回退文字气泡。点击台词属用户主动
    命令，固定 `force=True`。
35. **弹弓期间禁止右键菜单**：右键进瞄准、发射/取消后 0.35s 内，
    `contextMenuEvent` 不得构建菜单；普通右键不受影响。
36. **设置 X = 保存**：标题栏关闭保存并落盘；「取消」/Esc 恢复打开时快照。
    内嵌页也必须走同一套 `_commit()`。
37. **菜单固定头尾**：`easter_egg` 永远是第一项；`playback_speed` 默认隐藏；
    尾部固定 `modern_settings → separator → quit`。旧布局由 `migrate_p8_menu()`
    幂等迁移，用户仍可在菜单编辑器里调整其他项。
38. **直播捕获兼容**：`stream_capture_mode` 开启时宠物窗口与气泡必须是普通顶层
    `Window`（非 Tool），并清掉 Win32 `WS_EX_TOOLWINDOW/WS_EX_NOACTIVATE`；
    关闭恢复 Tool。不得因此禁用多宠（每只窗口都可单独捕获）。
39. **播放动画预览**：分类子菜单只在 `aboutToShow` 填充；缩略图解码必须在
    非 GUI 线程（最多 2 线程），GUI 线程只转 `QPixmap`；`menu_animation_icons`
    关闭时不得发起解码。
40. **点击/拖放监听覆盖未来宠物**：`InteractionAdapter` 必须保存回调并能
    `attach_window()` 到新生成的子宠；`PetManager.spawn()/restore()` 负责调用，
    否则点击台词/投喂类功能在子宠上永远不触发。
41. **气泡与彩蛋窗必须与桌宠同层**：`always_on_top` 是宿主口径，气泡
    （`SpeechBubble.set_host_on_top`）与彩蛋弹窗（`EasterEggPopup(on_top=)`）都要跟随；
    桌宠置顶时气泡也置顶，否则图片气泡会被桌宠盖住（文字气泡贴头顶，看不出差别）。
42. **鼠标穿透只在托盘菜单**：右键菜单模板不包含 `click_through`（旧布局由
    `migrate_p9_menu()` 幂等摘除）；托盘菜单的「鼠标穿透」一次作用到所有桌宠并
    用气泡说明恢复位置。设置页「外观与交互 → 点击穿透」保留为第二个入口。
    理由：穿透开启后右键菜单本身点不到，托盘是唯一稳定的恢复入口（与主分支一致）。
43. **对话只有一条通道**：mod 只能通过 `HostPorts.chat`（`ChatPort`）驱动聊天窗口；
    窗口、Markdown 渲染、会话落盘与取消都在 core。流式 HTTP/SSE 只能出现在
    `petcore/api/`，`petcore/chat/` 保持 Qt-free 且零网络依赖。
44. **截图只走内存**：截屏由 core 的 `ScreenPort` 提供，PNG 直接内联进请求，
    **不写磁盘、不写日志正文**；未声明 `screenshot.capture` 的扩展拿不到端口。
45. **热键失败必须可见**：四条全局热键（显示隐藏 / AI 对话 / 看看屏幕 / 截图提问）
    各自独立注册；注册失败要落到气泡与设置行，不许静默。
46. **图片按设备像素比装载**：彩蛋弹窗、气泡配图、菜单头像一律走
    `petcore/media/images.py`（`load_pixmap/scale_pixmap/logical_size/screen_dpr`）：
    逻辑尺寸上限 × 屏幕 `devicePixelRatio` = 物理解码尺寸，pixmap 写回 DPR，
    QLabel 只设逻辑尺寸。禁止「先缩到逻辑像素再交给 QLabel」——1.5 倍缩放的
    屏幕上会被二次放大，这就是「彩蛋图发虚」的根因。

## 5. 资源与扩展供应链

### 5.1 素材路线

| 路线 | 现状 | 目标 |
|---|---|---|
| WebP 帧序列 | core 直接消费 | 默认路线；首跑供给、世代退役与 GC 由 core/worker 负责 |
| WebM | 通过 `pet.webm_clip` 只读适配 | 过渡期保留；可转帧序列后退役 |
| GIF | 通过 `pet.library.GifClip` 只读适配 | 过渡期保留 |
| 角色资源包 | 规划中（P1-D） | 统一 manifest v2、导入/校验/预览 CLI、冲突策略 |
| VPet 素材 | 只留 `Clip` 后端接口 | 不承诺兼容 LPS；需要时写独立后端 |

### 5.2 角色包

- 一个角色包 = 目录 + manifest：角色 id、显示名、动画文件/帧序列、`body_box`/
  `head_box`、`move_strides`、预览图、授权与来源字段。
- 包可以被复制到 `mods/<id>/` 或打包成 content mod；同 id 冲突策略为
  「拒绝覆盖内置、用户包之间按显式安装覆盖」。
- 转换（WebM/GIF/PNG → 帧序列）在 worker 中执行，core 只消费结果；转换失败要
  有诊断，不得静默回退到错误素材。
- 详见 [`PETCORE-CHARACTER-PACKS.md`](PETCORE-CHARACTER-PACKS.md)。

### 5.3 mod

- `mod.json` 声明 id、kind、版本、入口、能力、依赖与贡献；内容包与功能包同一套
  发现/启停/安装流程。
- feature 只能在 `--allow-feature-mods`、或带安装器授信标记 `.trusted` 的用户
  mods 目录下加载；默认只加载内置 demo。没有热卸载与沙箱，文档必须如实说明。
- Windows 安装向导把 5 个官方示例扩展做成可勾选项：不勾选就不写盘；勾选时装到
  安装目录 `{app}\mods\<id>` 并带 `.trusted`。卸载随 `{app}` 一起删除。
- 贡献类型：菜单动作、设置页、角色/音效/台词/主题内容、事件订阅；跨域不互相
  import。
- 详见 [`PETCORE-MOD-FORMAT.md`](PETCORE-MOD-FORMAT.md)。

## 6. 交付门

一个批次算完成，必须同时满足：

1. 结构守卫绿：`petcore/engine/` 禁 Qt、`contracts/` 只用标准库、`pet.*`
   只在允许的两个文件中出现、网络库只出现在 `net/`/`api/`/`account/`、mod 不
   import 这三个包。
2. 测试绿：`tests/test_petcore_*.py` + `tests/test_architecture.py` +
   `tests/test_pr_report_discipline.py` + `tests/test_ci_workflows.py`。
3. ruff 绿：`ruff check pet/ tests/ petcore/`。
4. 实机证据：真实启动、用户可见行为、截图/命令输出；不能自动验证的项要写清
   「为什么不能」与探针结果。
5. 性能证据：受影响路径的实测数字（命令、环境、样本量），不用形容词代替。
6. 文档：PR 报告三段证据 + `docs/INDEX.md` 登记 + `PETCORE-LOG.md` 追加条目 +
   `PETCORE-LOG-INDEX.md` 建索引。

## 7. 非目标（当前阶段明确不做）

- 热卸载、mod 沙箱、签名/权限隔离。
- 跨进程碰撞 IPC、每屏多宠、overlay 的 `ScreenHost` 全套。
- Core 自更新、支付、云同步。
- 兼容 VPet 的 LPS 素材格式。
- 在没有实测的情况下承诺 macOS/Linux 的窗口层级与输入行为。

## 8. 退出旧架构的判定

只有同时满足以下条件，才把发布入口从 `pet/` 切到 `petcore`：

- P2 第一批功能域（F07/F08/F10/F11）在 petcore 下可用且有验收；
- 设置/菜单/多屏/托盘/气泡达到主分支用户可见行为；
- 角色包导入与首跑素材供给可用；
- 打包产物在 Windows 实机跑通，macOS/Linux 至少有无头/构建验证；
- 旧 `pet/` 只作为兼容层被调用，不再承载新功能。

之后 `pet/` 只修兼容性缺陷，最终删除。

## 9. P2 已落地（2026-10-20）

- **关于**：独立 `AboutDialog` 与右键 `about` 已删除；版本、数据目录、日志、诊断快照、复制诊断、项目主页全部在设置「关于与诊断」。
- **单进程多宠**：`PetManager` 管理 slot 0 主宠与 slot 1–15 子宠；每宠独立 `config-pet-N.json`；生成/收回/重启恢复；宠物间椭圆近似碰撞与 Q 弹；设置页「多宠」。
- **交互 Core**：点击 Q 弹（220ms，旋转/探头叠加、命中逆变换）、拖动物理（弹簧/抛掷/碰边）、弹弓、黄金回旋、探头击飞旋转、拖文件投喂、碰撞；菜单「播放动画」「播放速率」「拖动物理」「不自动移动」「黄金回旋」「生小肥鱼」「退出子肥鱼」。
- **内置 mod**：`fun.self-talk`、`fun.click-talk`、`tool.quick-launch`、`tool.quiet-mode`、`tool.links`、`tool.memory-trim`、`tool.network-info`；受信任内置包随 core 加载，第三方 feature 仍需 `allow_feature_mods`。`fun.divination`、`fun.festival`、`reminder.todo`、`voice.chime`、`media.music` 是 `examples/petcore-mods/` 的可导入样板，不再内置。
- **设置聚合**：所有 mod `settings_page` 进入「扩展管理」页内标签（`SettingsTabContainer`）；P6 起侧边栏 8 页（新增「API 与账户」）。
- **移动同步**：朝向由移动方向决定；窗口位置由 clip 帧号 + `move_curves` 推进，静态帧不位移，末拍精确到位。

- **打包**：PyInstaller 6.22.3 装入 `.venv`；Inno Setup 6.7.3 便携安装到 `tools/InnoSetup`；`scripts/build_petcore.ps1 -Clean -Installer` 实际产出 onedir 与安装包，`--check --out` 取证。
- **动画**：`animation_gap_seconds`、`playback_speed` 生效；Q 弹/回旋/击飞/投喂/碰撞属于本轮交互动画。
- 后续：P3 网络/worker 域（F01/F02/F03/F04/F05/F06/F07/F09），P4 动画与性能 backlog（共享解码、预测预热、WebM 全量、VPet PNG、Agent 联动动画、音乐唱歌、动态岛、head_box 精细探头）。见 [`PETCORE-ANIMATION-BACKLOG.md`](PETCORE-ANIMATION-BACKLOG.md)。


> 本章及以下 P6/P7/P8.x 已按 ROADMAP §0 的编号约定改称 H6…H8.4（历史批次）；
> 当前交付阶段用 P0–P6，见 §15 与 ROADMAP §20。

## 10. H6 已落地（2026-10-20）

- **动画节拍**：待机一圈结束即掷骰（此前 IDEL 的 `B_LOOP + loop=True` 被 `advance()`
  原样续播，桌宠永远停在待机）；`animation_gap_seconds` 改为「间隙继续播待机、到点掷骰」；
  同一 clip 重播只 re-arm 不硬停。
- **可调概率**：设置 →「互动与物理」→「自主行为概率」四个百分比；默认 30/10/40/20，
  按比例归一化，0 表示从不；改完下一次掷骰即生效。
- **事件动画**：`events/<group>/` 载入为 `GraphType.EVENT` + `event_group`；余额 6 个
  动画不再混进随机动作池，由 `play_event()` 按名字/索引触发。
- **手动播放**：右键「播放动画」按待机/转向/移动/点击回应/随机动作/事件分组，
  叶子点一次播一次，播完回掷骰链。
- **core 联网**：`petcore/net/`（代理失败自动直连 + 五类失败分类）与
  `tests/test_petcore_net.py`；架构守卫改为 allowlist（`net/`、`api/`、`account/`），
  并新增「mod 不得 import 这三个包」。
- **core API**：`contracts/api.py`（`ApiMetadata/ApiRequest/ApiPort`）、`petcore/api/`
  （规格校验、`api.json` 原子写、keyring 凭据、文本探测）；设置页「API 与账户」；
  菜单「工具与帮助 → API 与账户」；`HostPorts.api` 与 `CoreApiPort`。
- **账户**：H8 落地（H7 只做交互/安装/扩展管理/彩蛋与音效；`account/` 仍留占位）。

## 11. H7 已落地（2026-10-21）

- **探头/击飞**：碰撞确认重叠后先授权 `arm_throw_egg()` 再退出探头；飞行/彩蛋期间
  只允许 idle/转向；`motion.thrown` 不掷骰、左键点击返回；低速碰撞立即回正。
- **安装器**：`SetupIconFile`/`UninstallDisplayIcon` 用鲸鱼娘 `assets/icon.ico`；
  5 个随附扩展改到 `{app}\mods\<id>`（`.trusted`），应用同时扫描安装目录；
  `--icon` 让主 exe 也带图标。
- **扩展管理**：左侧竖向滚动导航（基础扩展/加装扩展），ModsPage 加同口径过滤；
  `mod.json` 新增 `name_zh`，13 个内置/示例包已补中文名。
- **彩蛋与音效**：菜单「工具与帮助 → 彩蛋图片」随机弹 `assets/big_blue_fat_fish`
  的图片（可配置目录/标题）；点击音效包支持默认/小黄鸭/自定义文件/文件夹，
  碰撞与碰边复用同一音源。

## 12. H8 已落地（2026-10-21）

- **多宠推动**：轻碰分离不再取消移动计划、不再切 `thrown`；被推开的宠把漫游计划
  整体平移继续走。探头宠物在轻碰时按无限质量处理，只推开对方；真撞击（≥300px/s）
  才退出探头并授权击飞旋转。
- **子宠退出**：右键「退出这只」只关闭当前子宠并写回 `active_pets`；主宠仍保持运行。
- **气泡**：跟随桌宠移动与缩放；支持图片内容（彩蛋默认进气泡），可切独立窗口。
- **彩蛋菜单行**：头像 + 标题 + 「请点击」的整行控件，点击在菜单关闭后打开。
- **设置 IA**：「互动与物理」拆成 8 个页内分页；「菜单」拆菜单编排/快捷启动；
  「关于与诊断」拆版本诊断/链接/网络/回收内存。
- **Core 内置特性**：7 个原内置 feature 并入 Core，设置页按 `host_page` 内嵌；
  扩展管理只保留「扩展管理 + 基础扩展 + 加装扩展」，组头可折叠。
- **安装向导**：目录页每次显示，已装过时预选上次安装路径。
- **打包回归**：`menu_templates` 进入 PyInstaller 数据；`load_default()` 内置兜底；
  `--check` 输出 `menu_template`，杜绝右键菜单缺项。
- **差距台账**：新增 [`PETCORE-MAIN-PARITY-BACKLOG.md`](PETCORE-MAIN-PARITY-BACKLOG.md)，
  后续 P9–P12 的待办以该表为准。

## 13. H8.1 已落地（2026-10-21）

- **字号与图片大小**：`ui_font_size`（10–18）同步设置页、右键菜单与彩蛋菜单行；
  `bubble_text_scale`（50–300%）控制气泡文字/内边距；`easter_egg_image_scale`
  控制彩蛋图上限；`self_talk_image_scale` 控制自语配图上限。
- **自言自语出图**：`self_talk_image_chance`（0–100%，默认 30）命中时从
  `self_talk_image_dir`（空 = 内置 `assets/big_blue_fat_fish`）随机取图，作为气泡
  配图显示；0% = 只说话。点击台词是用户主动命令，`say(force=True)` 不受免打扰抑制。
- **菜单顺序**：`easter_egg` 固定为第一项；`playback_speed` 默认隐藏；
  尾部固定为 `… → modern_settings → separator → quit`（分界线下方只有退出）。
  `migrate_p8_menu()` 对旧布局幂等迁移。
- **动画预览**：播放动画分类子菜单改为 `aboutToShow` 懒加载；动作带代表帧缩略图
  （`media/thumbnails.py`，内存 LRU 128 + 磁盘缓存，2 线程）；随机动作按名称前缀
  分组；`menu_animation_icons` 可关。
- **弹弓右键**：右键进入瞄准后，发射/取消后的 0.35s 内以及瞄准期间
  `contextMenuEvent` 一律不再弹菜单。
- **点击监听**：`InteractionAdapter.attach_window()` 给新生成的子宠补挂 click/drop
  监听；点击台词从启动第一只宠起就生效。
- **设置关闭**：标题栏 X = 保存并关闭；「取消」/Esc 仍恢复打开时快照。
- **直播捕获兼容**：`stream_capture_mode` 让桌宠与气泡从 Tool 窗口切到普通顶层
  `Window`，OBS/直播姬可枚举；捕获方式需选 Windows 10 1903+（BitBlt 黑屏）。
- **隐藏态**：`say()` / `show_image()` 在桌宠不可见时直接返回；`set_visible(False)`
  同时收起气泡。任何 feature 都不能绕过这个闸门。
- **设置合并**：彩蛋与自言自语配图合并到「互动与物理 → 彩蛋与配图」一页；
  自言自语页只保留节奏与候选台词。
- **托盘菜单**：独立于右键菜单（显示/隐藏桌宠、桌宠设置、数据目录、重载扩展、
  逐宠显示/隐藏/回右下角/退出这只、退出）；托盘左键也能切换显示。

## 14. H8.4 已落地（2026-10-21）

- **鼠标穿透归位托盘**：右键菜单不再有「点击穿透」（`migrate_p9_menu()` 幂等摘除
  旧布局里的该项）；托盘菜单新增可勾选「鼠标穿透」，一次作用到所有桌宠，开启时
  气泡提示「可从托盘菜单关闭」。设置页「外观与交互 → 点击穿透」保留。
- **气泡同层**：气泡与彩蛋弹窗跟随桌宠 `always_on_top`（同主分支
  `speech_bubble.set_host_on_top`），修「图片气泡掉到桌宠下面」。
- **图片高清**：新增 `petcore/media/images.py`，彩蛋弹窗、气泡配图、菜单头像统一按
  「逻辑上限 × 设备像素比」解码并写回 DPR；1.5 倍缩放的屏幕上不再被 QLabel 二次
  放大。实测弹窗渲染锐度（梯度能量）10.99 → 16.37（+49%）。

## 15. 2026-10-22 审查冻结的迁移契约

- **每宠作用域**：当前宠物上下文负责角色、缩放、动画、物理、音效、台词、位置与会话；
  全局上下文负责菜单、托盘、网络/API、更新、共享解码、默认扩展与进程级资源。
  设置窗口和 feature port 必须绑定打开它的宠物，不能默认读取主宠配置。
- **Worker**：业务 worker 只能通过 `contracts/worker.py` 的 JSONL 协议和 `HostPorts.worker`
  接入。Core 必须统一提供启动、握手、心跳、取消、超时、崩溃重启、代次拒收和退出收口。
- **迁移**：发布入口切换前必须迁移 v4 全局配置、slot 配置、会话、待办、API 规格和凭据引用；
  原文件先备份，迁移失败不得覆盖原数据，并提供可读诊断与回滚。
- **Core/mod**：API 服务规格、钥匙串、账户、额度和统一网络出口属于 Core；AI、识屏、Agent、
  音乐、语音、天气、文件识别和提醒执行属于 mod/worker。
- **有意差异**：播放速率保持 `0.5–2.0x`；本轮不支持 VPet LPS/PNG；首轮 petcore 保持最多
  16 只桌宠。差距和阶段归属见 [`PETCORE-FUNCTION-MATRIX-2026-10-22.md`](PETCORE-FUNCTION-MATRIX-2026-10-22.md)。
- **发布门**：只有 P0–P6 阶段完成、配置迁移可回滚、默认扩展安装可验收、Windows 冻结包
  通过功能矩阵且旧 `pet/` 不再承载新功能后，才切换 `python -m petcore` 为正式入口。

## 16. P1 已落地的配置作用域基础（2026-10-22）

- `ScopedConfig` 让设置页和 Core feature 区分全局键与当前宠物键。
- 设置对话框按打开它的窗口绑定 slot；实时预览和保存都针对该宠物。
- `PetManager` 只同步全局键；新子宠从主宠播种每宠配置，恢复/生成/收回会通知 feature 生命周期。
- 旧 standalone 配置与 slot 档案会在目标不存在时迁移，旧源只读，新目录保存 `migration-backup/`。
  会话、待办和 API 文件迁移等待对应消费者阶段。

## 17. P2 已落地的 WorkerHost 与离线接缝（2026-10-22）

- `petcore/platform/worker.py` 提供统一 `WorkerHost/WorkerSession`：真实子进程、JSONL 握手、
  配置推送、取消、错误、退出回收、owner 替换和可选心跳超时。
- CoreHost 持有单一 WorkerHost；退出流程会先收口 worker。业务 worker 仍需在 P3/P4 由 mod 接入。
- 设置常规页可从角色目录构建并安装 content mod；旧素材目录补齐 VPet Graph 类别的寻址映射。
- 安装器的 5 个官方离线 feature 默认不勾选，勾选才写盘；它们继续保持 feature mod 边界。

## 18. P3 账户基础（2026-10-22）

- `petcore/account/AccountService` 属于 Core，通过 `ApiStore`、`KeyringCredentials` 和统一
  `net` 出口提供余额查询、30 秒内存缓存、多币种选择和稳定错误分类。
- `HostPorts.api.fetch_balance()` 是 mod 的唯一余额入口；请求响应体和密钥不得进入日志。
- 余额菜单、自动刷新、档位动画和灵动岛展示要等异步 UI/worker 阶段接入，不能把同步服务
  直接放进 Qt 菜单回调。
- `petcore/chat/SessionStore` 按 slot 和角色目录隔离会话，限制消息数量并原子写入；它不保存
  API Key、服务凭据或 worker 状态。



## 16. P3 落地（2026-10-22）

- **流式对话**：`petcore/api/chat.py` 提供 `stream_chat()`（SSE / 一次性 JSON 回退、
  取消、超时、代理兜底、稳定错误分类）；`ApiPort.stream_chat()` 是 mod 唯一入口。
- **聊天宿主**：`ChatPort` + `petcore/ui/chat/`（主分支同款双栏对话窗、Markdown
  气泡、流式合帧、停止/新建会话、附件、按 `(owner, slot)` 隔离）；会话复用
  `petcore/chat/session_store.py`。跨线程只走信号，worker 线程不碰 Qt。
- **截图提问**：`ScreenPort.capture_region()` 负责框选（Core 覆盖层），
  `ScreenAskPort` 负责提问窗口；两者都只处理内存 PNG。整屏 `ScreenPort.capture()`
  仍用于「看看屏幕」，实测 1920×1200@1.5 抓屏 204.7ms、PNG 367KB。
- **热键**：`hotkey_toggle_pet` / `hotkey_open_chat` / `hotkey_look_screen` /
  `hotkey_screen_capture`，四条各自独立的 Win32 id；失败在设置页与气泡可见。
- **AI 扩展**：`examples/petcore-mods/ai.chat` 是参考实现（host-only）：prompt/人格/
  路由在 mod，传输/窗口/密钥在 core；安装向导提供可勾选项（默认不勾）。无扩展时
  菜单/热键会明确提示「AI 扩展未安装」。
- **打包签名**：构建脚本支持 `-SignThumbprint`（开发证书见
  `scripts/make_dev_signing_cert.ps1`）；exe 在 `--check` 前签名，setup 在 ISCC 后签名。
  未签名产物会被本机 Smart App Control 拦下（4551），这不是代码问题。
- **未做**：OCR、翻译、框选、主动识屏、Agent、TTS（P4）。

## 19. 对话 / 识屏 / 截图提问的最终边界（2026-10-22）

这一节冻结「效果对齐主分支，但执行仍归 mod」的边界，后续不要再把窗口或传输重写一遍。

- **对话窗口是 Core**：`petcore/ui/chat/` 直接移植主分支的现代双栏对话窗（侧栏会话、
  标题栏、Markdown 气泡、附件、浮动输入框、置顶/最小化/关闭）。mod 只能经
  `HostPorts.chat` 提交、流式回传、停止；不得自建聊天窗口或直接操作气泡。
- **运行时代码无 Qt**：`ai.chat` 的 `host/runtime.py` 不 import PySide6，需要回
  GUI 线程一律经 `HostPorts.scheduler.call_later()`；只有 Core 托管的设置页
  （`host/settings_page.py`）可以用 QtWidgets。
- **配置读取分两层**：运行时只经 `HostPorts.config`（只读 `ConfigPort`）读配置；
  设置页作为受信 UI，允许直接使用 Core 给的 `ScopedConfig`。不再保留未实现的
  `SettingsPort` 假契约。
- **主对话与截图提问是两个窗口**：主对话用 `ChatPort`，截图提问用
  `ScreenAskPort`；两者都按 `(owner, pet_slot)` 隔离，互不串流。
- **对话窗外观**：`chat_background`（默认白/内置主题/本地图片）、`chat_accent`、
  `chat_follow_pet`、`chat_always_on_top` 均有设置入口；改动经
  `ChatController.apply_appearance()` 实时作用到已打开的窗口。跟随使用
  `PetWindow.pet_moved` + 40ms 合并定位，优先右侧、放不下切左侧、最后钳在可用区。
- **看看屏幕**：Core 只提供整屏 `ScreenCapture`（含前台应用描述）；mod 负责
  prompt 与请求。答复必须先落到发起宠的气泡，再通过 `ChatPort.record()` **静默**
  写入该宠的会话记录；不得主动唤出对话窗口，除非 `ai_look_screen_auto_open=true`。
- **截图提问**：框选覆盖层、图片预览、多轮消息、加载态与 10% 鲸蛙加载彩蛋都在
  Core；mod 只通过 `ScreenAskPort.on_ask(question, png, history, slot) -> str`
  同步返回整段答复（Core 在后台线程调用它）。图片只在内存中流转，不落盘、不进日志。
  多轮历史**每次采集独立**：`open()` 清空上一轮，只存内存；不写磁盘（图片不能落盘，
  纯文本脱离当次图片没有追问语义）。
- **彩蛋口径**：截图提问窗口标题栏固定 DS 鲸鱼；等待答复时按
  `random.random() < 0.1` 抽一次鲸蛙，整次请求保持不轮播。这个彩蛋独立于桌宠菜单的
  「鲸鱼娘彩蛋」，不复用后者的图片目录/概率配置。
- **失败可见**：没有 API 服务、缺少扩展、视觉开关关闭、框选取消分别给出不同反馈；
  取消框选是静默返回，不算错误。

## 20. P7 深度思考与联网搜索（2026-10-22）

这一节冻结「思考/联网仍属 Core 传输能力、业务编排在 mod」的边界。

- **思考参数在 Core**：`petcore/api/chat.py::build_payload()` 负责
  `thinking={"type": enabled|disabled}` 与 `reasoning_effort`；`auto` 模式不发送
  任何思考字段（严格校验的服务会 400），显式开/关才下发。`stream_chat()` 把
  `reasoning_content` / `reasoning` 通过 `on_reasoning` 单独回调，**不拼进正文**；
  只出思维链且 `finish_reason == "length"` 时抛 `ChatTruncated`，提示调大输出上限。
- **联网检索在 Core**：`petcore/net/websearch.py` 是唯一搜索引擎实现
  （百度/DuckDuckGo 免 Key，博查/Tavily 需 Key；免 Key 两个互为兜底，遇人机验证
  如实报错、不绕过）。`stream_chat(web_search=)` 先跑独立一轮非思考 planner
  （`web_search` / `fetch_url` 工具，≤3 轮 × ≤4 次），把资料按主分支口径注入
  system，再走正式流式回答；任何检索失败只降级成状态行，不阻断回答。
- **搜索 Key 只进钥匙串**：owner `core.websearch`、key 为引擎 id；
  `ApiPort.set_web_search_key()` / `web_search_key_status()` 是唯一读写入口，
  `config.json` 与 `api.json` 都不出现 Key。
- **思考/联网是全局设置**：`ai_thinking`（auto/enabled/disabled）、
  `ai_reasoning_effort`（low/high/max）、`ai_web_search`、`ai_web_engine`
  （baidu/duckduckgo/bocha/tavily）、`ai_web_results`（1–10）、`ai_web_fetch`；
  设置入口在「扩展管理 → 加装扩展 → AI 对话」。与现有 `ai_model` / `ai_temperature`
  一致，不按 API 服务分别保存（主分支是 per-provider，这是已知差异）。
- **面板在 Core 窗口**：`ChatPort.reasoning()/status()` → `ChatController` 排队信号 →
  `ChatWindow.append_reasoning()/add_activity()` → `MessageBubble` 的折叠面板；
  窗口没开就丢弃，绝不主动唤窗。`reasoning`/`activity` 随 assistant 记录落盘，
  重新打开会话时回显（旧会话没有字段照常加载）。
- **截图冻结帧契约**：`grab_screen_image()` 必须返回 `QImage` 且
  `devicePixelRatio == 1.0`（裸设备像素）。Qt6 的 `QScreen.grabWindow` 返回
  `QPixmap`，直接交给 `QPainter.drawImage` 会抛 TypeError，覆盖层整层画不出来
  （用户看到的是一整屏灰色）；裁切/编码仍能工作，所以「框出来的图正常」。

## 21. P8 截图动作条与快速对话（2026-10-22）

- **动作条四个动作**：提取文字 / 翻译 / 问问肥鱼 / 复制图像。core 只提供覆盖层、
  按钮可点性、结果窗与剪贴板；`copy` 在 core 完成（PNG 在内存里写系统剪贴板），
  其余动作交给扩展。
- **动作调度**：`ScreenAskPort.on_action(owner, callback, priority=, actions=)` 是
  处理者注册表；core 按 priority 从小到大调用，回调返回空串或抛异常就换下一个。
  这就是「本地 OCR 优先、AI 兜底」的机制，core 里没有任何引擎判断或提示词。
- **本地 OCR 是扩展**：`examples/petcore-mods/tool.ocr`（加装扩展，安装任务
  `mod_ocr` 默认不勾）用 rapidocr + `resources/rapidocr_models`（经
  `ResourcesPort.bundle_path` 取路径），显式自建 onnxruntime session，不下载模型。
  失败返回空串，由 `ai.chat` 的视觉模型兜底；引擎异常不弹给用户。
- **翻译**：`ai.chat` 注册 `translate`；有本地 OCR 原文时走纯文本翻译，没有时把
  图交给视觉模型；目标语言自动判定（中日韩占多→英文，否则中文）。
- **快速对话**：点桌宠气泡 → `SpeechBubble.clicked` → `CoreHost.open_quick_chat`
  → `QuickChatPort`；紧凑气泡（标题/状态/Markdown 输出/输入/去聊天窗）在 core，
  流式回答在 `ai.chat`。与完整聊天窗共用同一会话，提交前落 user、完成后落
  assistant，`去聊天窗` 看到同一段对话。
- **依赖现实**：冻结包无法让 mod 自己安装 Python 包，`rapidocr` / `onnxruntime` /
  `cv2` 随 exe 打包；没有安装 `tool.ocr` 时这些代码不会被调用，动作条按能力置灰。

## 22. AI 对话模块的最终分布（2026-10-22）

- **core 只背通用能力**：`contracts/*` 的端口、`api/chat.py` 的流式/搜索传输、
  `net/websearch.py` 的搜索引擎、`chat/session_store.py` 的会话、`ui/chat/` 的
  双栏窗与快速气泡、`ui/screen/` 的截图动作条与结果窗、`ui/ports.py` 的端口装配。
- **业务全在 mod**：`ai.chat` 负责人格/提示词/消息组装/翻译/快速对话编排；
  `tool.ocr` 负责本地 OCR 引擎与模型。core 不 import 它们。
- **允许的耦合**：`ai_*`/`chat_*` 设置键在 core 配置白名单里（作用域与类型校验）；
  `ChatTruncated` 是 core 里唯一残留的用户向文案。
- **启动成本**（实测）：对话窗包导入约 7.1 MB / 63.5 ms；传输层首次对话才加载
  （6.4 MB / 77.9 ms）；OCR 引擎首次识别 +145 MB 常驻。
- 详细代码表、占用与结论见
  [`PETCORE-ARCHITECTURE.md` §23](PETCORE-ARCHITECTURE.md#23-ai-对话模块分布与-core-占用2026-10-22)。
