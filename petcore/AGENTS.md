# petcore 工作约定（给 agent 与贡献者）

> 本文件只约束 `petcore/` 与 `tests/test_petcore_*.py`。仓库级规则（PR 三节证据、
> CI 成本纪律、文档登记）仍以根 [`../AGENTS.md`](../AGENTS.md) 为准。

## 1. 每次改动必须写 log

**硬要求**：任何代码、测试、文档改动完成后，必须同时做两件事：

1. 在 [`../docs/PETCORE-LOG.md`](../docs/PETCORE-LOG.md) 追加一条 `## LNNN`，写清：
   - 日期、批次/主题；
   - 改了哪些文件（`git diff --numstat` 口径）；
   - 行为变化与设计理由；
   - 验证命令与真实结果；
   - 未验证项、风险和后续动作。
2. 在 [`../docs/PETCORE-LOG-INDEX.md`](../docs/PETCORE-LOG-INDEX.md) 加一行索引：
   `LNNN / 日期 / 批次 / 一句话 / 关键词`。

读取 history 时**先读索引**，只打开命中的那一条，不要整份 log 塞进上下文。
`tests/test_petcore_docs.py` 会校验 log 与 log-index 的 `LNNN` 一一对应。

## 2. 架构红线

- `petcore/engine/` 禁 PySide6；纯逻辑只依赖标准库与同层模块。
- `petcore/contracts/` 只用标准库。
- 直接 `import pet.*` 只允许 `petcore/media/` 与 `petcore/content/legacy.py`。
- 网络库（`urllib/http/socket/requests/aiohttp/httpx`）只允许出现在 `petcore/net/`、
  `petcore/api/`、`petcore/account/`；mod（builtin 与 examples）不得 import 这三个包，
  只能拿 HostPorts。
- 密钥只进系统钥匙串：`config.json`、`api.json` 都不许出现 API Key；`ApiRequest`
  的 `repr` 不含密钥。
- `ui → engine/contracts/media/content/mods/platform` 单向；不要让 core 反向依赖具体业务域。

结构守卫：`tests/test_petcore_architecture.py`。红了不许改测试放行。

## 3. 菜单与设置

- **菜单/设置一一对应**：Core 菜单项必须在 `petcore/ui/settings/coverage.py` 有
  设置落点；新增菜单项不登记 = `tests/test_petcore_settings_coverage.py` 红。
  `modern_settings` 豁免。
- 菜单默认隐藏不等于删除：隐藏项仍要留在模板里，用户可在设置 →「菜单」重新勾选。
- **mod 设置页聚合**：所有 `settings_page` 贡献只进「扩展管理」的页内标签
  （`ui/settings/tabs.py`），不要再追加侧边栏页；P6 起侧边栏 8 页（「API 与账户」
  是 core 页，不是 mod 页）。保存/取消/释放由 `ExtensionsPage` 委托每个内嵌页。
- **设置搜索必须搜到行**：`_apply_filter` 的匹配口径含页面内所有 `QLabel` 文案，
  命中后 `reveal_text()` 切页 + 滚到该行；只按页面标题过滤不算实现。
- **页内分页不许截断**：标签条在 `QScrollArea` 里，两侧翻页箭头按溢出显隐，
  `setCurrentIndex` 必须 `_ensure_visible`。
- 设置改动必须实时反馈到桌宠；保存只负责落盘，取消/关闭恢复打开时的快照。
- 设置/关于窗口必须是非模态的，不得阻塞桌宠拖动、点击、滚轮。
- 大小范围固定 10%–300%，所有入口共用 `petcore.engine.geometry.clamp_scale()`。
- **位置钳制必须用 `body_box`**：贴边、右下角/主屏落位、位置恢复/比例、跨屏迁移
  一律走 `body_local_rect()` + `clamp_body()/clamp_body_to_screens()`；不许再用
  整窗 `content_size()` 直接贴边。`body_box` 缺失才回退整窗。`head_box` 已解析，预留给后续更精细的
  露头锚点；当前探头曝光以 `body_box` 投影宽度为准。
- **边缘探头**：贴边判定用身体框，旋转投影用帧中心；`is_transparent_at()` 必须
  与 `paintEvent` 的旋转互逆，否则点击和画面对不上。探头放宽域必须减去
  `body_local.x`。
- **快捷键/自启/多实例**：快捷键只做 Windows `RegisterHotKey`，失败必须可见；
  自启命令文本必须区分 `sys.frozen`；多实例用独立数据根与 lock，不许共享配置。
- **角色包**：`pack-character` 产物必须是标准 content mod（`character.<id>`、
  `kind=content`、`character.media`）；校验 body/head 与媒体存在；不许路径逃逸。
- **Q 弹/旋转命中**：`paintEvent` 与 `is_transparent_at()` 的逆变换顺序必须是
  「先 Q 弹逆变换、再旋转逆变换」；探头角度、黄金回旋、击飞旋转相加，不许互相覆盖。
- **多宠配置隔离**：主宠 `config.json`、子宠 `config-pet-N.json`；子宠播种不得
  复制位置/屏幕/朝向；碰撞只能通过 `PetManager` 的 tick 改位置与速度。
- **Core 内置特性**：`petcore/builtin/features/<id>/` 里的 7 个包
  （`fun.click-talk`、`fun.self-talk`、`tool.quick-launch`、`tool.quiet-mode`、
  `tool.links`、`tool.memory-trim`、`tool.network-info`）是 `CORE_FEATURE_IDS`，
  无条件加载、不可停用/卸载、不进扩展导航；其 `settings_page` 必须写 `host_page`
  内嵌到 Core 页（interaction/menu/about）。`core.feature-demo` 是接缝示例，归
  「基础扩展」。第三方 feature 仍受 `allow_feature_mods` 控制。
  `fun.divination`/`fun.festival`/`reminder.todo`/`voice.chime`/`media.music` 在
  `examples/petcore-mods/`，是可导入样板，不得再放回 builtin；Windows 安装向导会把
  它们做成可勾选项且**默认不勾选**（不勾选完全不写盘，`Flags: unchecked`），装好后带
  `.trusted` 标记，归「加装扩展」。
- **移动同步**：窗口位置只能由 `move_position_at_frame(plan, frames_elapsed)` 按
  clip 帧号与 `move_curves` 推进；移动开始必须先设置 `state.facing` 再渲染首帧。
  不许恢复固定 33ms 线性步进或只按 `state.facing` 猜方向。
- **待机节拍**：IDEL 是 `B_LOOP + loop=True`，`_on_finished` 里**不许**先走
  `player.advance()`（它会原样返回同一个 idle spec，桌宠永远待机）；圈末要么继续
  播 gap 待机、要么 `_roll_next()`。同 clip 重播只 `start()` re-arm，不 `stop()`。
- **行为权重**：`anim_weight_idle/turn/act/move` 存百分比，`normalize_weights()`
  归一化；默认 30/10/40/20，0 表示从不。`BehaviorDirector.weights_provider` 每次
  掷骰读配置，设置改完即生效。
- **探头/击飞**：`probe_active` 或 `effects.throw_egg_active` 时 `_play_spec()` 只允许
  idle/转向（主分支 `_effects_filter_switch`）；探头会话 `_pending_flip` 必须为 False。
  `motion.thrown` 期间 `_on_finished()` 只 re-arm 当前素材、不掷骰，`_on_click()` 直接
  return（主分支非 normal 不消费点击）。
- **击飞彩蛋**：探头宠物被真正撞上时，`PetManager._collide_pair()` 必须先
  `arm_throw_egg()` 再 `edge_probe.cancel("collision", restore=True)`；低速碰撞没进入
  抛掷时立刻 `end_throw_egg()`。`MotionController` 每 tick 只在彩蛋激活时更新角度，
  `stop()` 无条件回正。
- **安装器位置**：随附扩展落 `{app}\mods\<id>` + `.trusted`，`paths.install_mods_dir()`
  只在冻结包存在，loader 与 `ui/app.py` 的「用户 mod 根」都必须含它；用户导入仍落
  数据目录 `mods/`。卸载随安装目录，设置页里这类包禁用卸载。
- **安装向导目录页**：`packaging/petcore.iss` 必须 `DisableDirPage=no` 且
  `UsePreviousAppDir=yes`；每次打开向导都显示路径页，检测到同 `AppId` 已安装时
  预选上次安装目录（`InstallLocation`）。不许用 `auto` 把目录页藏掉。
- **扩展管理**：左侧竖向导航（`#extensionsNav`）顺序为「扩展管理 → 插件市场 →
  基础扩展 → 加装扩展」，两个组头可点击折叠；`tabs` 门面只为兼容旧测试/深链，不要退回横向标签。
  `基础扩展` 只放 `petcore/builtin` 接缝包；安装向导 `.trusted` 与用户导入都算
  `加装扩展`。mod 展示优先 `manifest.name_zh`；Core 内置项标「已并入 Core」且
  禁用启停/卸载。
- **插件市场**：市场是 Core 基础设施（`petcore/market/` + 设置页），不是可停用的 mod；
  索引只存元数据，artifact 走有序 URL 列表；feature 安装仍受 `allow_feature_mods`。
  契约见 `docs/PETCORE-MARKET.md`，改市场、索引格式或下载链路前必读。
- **彩蛋/音效**：`easter_egg` 菜单 → `window.show_easter_egg()`；点击音效走
  `media/click_sound.py` 的 `click_sound_pack`（默认/duck/文件/文件夹），碰撞与碰边
  复用同一入口；不许回到硬编码 `click.wav`。
- **事件动画**：`events/<group>/` 是 `GraphType.EVENT` + `event_group`，不进
  `act()` 的随机动作池；只能 `play_event(group, variant)` 显式触发。
- **API 配置/密钥**：`api.json` 只存服务规格，密钥只进 `KeyringCredentials`；
  设置页只在显式保存时落盘，keyring 不可用时退内存并在界面说明。mod 通过
  `HostPorts.api`（`ApiPort`）拿 `ApiMetadata/ApiRequest`，不许 import `petcore.api`。
- **朝向口径**：角色素材原生朝左，`facing == "right"` 才水平镜像（同主分支）。
  `PetState.facing` 默认 `left`；反了就是「位移方向和面朝向相反」。
- **碰边反馈**：抛掷/弹射按「离地→接触」的接触沿触发 `_on_motion_bounce()`，每次
  落地或撞墙都要 Q 弹 + 音效；不许用「整个会话只触发一次」的布尔闸。
- **边缘探头贴边**：`edge_side_at_rest` 的严格容差只用于判定「已经贴边」；进入探头
  用 `EDGE_ENGAGE_TOLERANCE_PX`（28px）并 `edge_snap_x` 吸附压边——落地反弹会停在
  离边十几像素处。
- **多宠碰撞**：分离结果必须走 `window._clamp_position()`（身体框钳制）；轻碰只做位置
  分离，不写速度、不取消移动计划，分离后 `shift_move_plan(dx, dy)` 让漫游继续；
  只有 `impact_speed >= HIT_FEEDBACK_MIN_SPEED` 才 `motion.set_velocity()`（切 thrown）。
  拖拽中的桌宠不参与碰撞结算（否则会把别人一路推走/顶出屏幕）。
- **碰撞几何**：`engine/collision.py` 只用内切三圆链 + 主分支分离规则
  （slop 0.5 / 60% / 1..12px / 连续 3 tick 强制分离）。不许退回整框椭圆——
  椭圆四角不判撞，看起来就是穿模。
- **气泡锚点**：`say()`/`show_image()` 用 `bubble_anchor_rect()`（`head_box` →
  `body_box` → 整窗），不许用整窗 `frameGeometry()`。桌宠 `moveEvent` 必须同帧合并后
  `bubble.reposition()`，缩放后也要重排；气泡不是一次性快照。
- **设置键位**：`SettingsDialog` 里 Enter = 保存退出，只有多行文本框放行换行。
- **命令反馈**：菜单/设置触发的命令反馈用 `say/notify(force=True)`，别被免打扰吞掉。
- **菜单勾选**：勾选项必须渲染出对勾（`menu_style.menu_stylesheet()` 注入的 check 图片），
  勾选项不要再设 icon。
- **碰撞不瞬移**：`MotionController.set_velocity()` 切 `thrown` 前必须
  `_x/_y = window.x()/y()`——内部坐标只在该方法里重锚，漏掉就是「被撞闪现到别处」。
- **探头只被真撞击打断**：`impact_speed >= HIT_FEEDBACK_MIN_SPEED` 时先
  `arm_throw_egg()` 再 `_edge_probe.cancel("collision", restore=True)` 并完整分离；
  轻碰时探头 body 按 `static=True`（无限质量）处理，只推开对方并 `abort_move_plan()`，
  不得取消探头。
- **子宠落座**：位置由 `engine.spawn.choose_spawn_position()` 决定（逐圈找空位，
  必须整只落在可用区内）；不许再写「主宠右侧 +24」这种硬编码。
- **打包工具**：PyInstaller 安装在 `.venv`；Inno Setup 便携安装在
  `tools/InnoSetup`（不入库）。默认 `--windowed`（不许出现终端窗口），
  `-Console` 只给排障用；`sys.stdout is None` 由 `cli._ensure_streams()` 兜底。
- **构建产物必须签名**：本机 Smart App Control 会拦截未签名的新构建
  （`CreateProcess` 返回 4551「An Application Control policy has blocked this file」），
  PyInstaller exe 与 Inno setup 都会被拦。用
  `scripts/make_dev_signing_cert.ps1` 建本机信任的开发证书，构建时传
  `-SignThumbprint <指纹>`；签名必须发生在 `--check` 冒烟**之前**，setup 在 ISCC
  之后签。开发证书只在本机可信，正式分发要换 CA 证书。
- **扩展授信**：安装器投放的官方 feature 包带 `.trusted` 标记（`mods/trust.py`），
  与全局 `allow_feature_mods` 并列；loader 与 `ui/app.py` 只认 `mod.enabled`，
  不许再各自复读全局开关。
- 菜单布局 schema 的子菜单最多一层；改 schema 必须写迁移与文档。
- **菜单模板打包**：`petcore/menu_templates/*.json` 必须进 PyInstaller `--add-data`；
  `load_default()` 有内置兜底常量，`--check` 输出 `menu_template=json|builtin`。
  任何情况都不许退化成只剩「设置/退出」两项。
- **菜单固定头尾**：`easter_egg` 永远是第一项；`playback_speed` 默认隐藏；尾部固定
  `modern_settings → separator → quit`。改默认模板时同步 `BUILTIN_DEFAULT_LAYOUT` 与
  `migrate_p8_menu()`，旧布局必须幂等迁移。
- **字号/图片大小**：`ui_font_size`（10–18）同时作用于设置页、右键菜单、彩蛋菜单行；
  `bubble_text_scale`（50–300）作用于气泡；`easter_egg_image_scale` 与
  `self_talk_image_scale` 只改显示上限。新增字号消费点必须读这三个键，不许另写死值。
- **自言自语配图**：`self_talk_image_chance`（0–100，默认 30）决定是否出图；空目录用
  `assets/big_blue_fat_fish`；出图失败必须回退 `say()`。点击台词固定 `force=True`。
- **弹弓右键**：右键进瞄准以及发射/取消后的 0.35s 内，`contextMenuEvent` 必须直接
  return；否则「发射玩法」会误弹菜单。
- **设置关闭语义**：标题栏 X = `_commit()` 保存并关闭；「取消」/Esc 恢复打开时快照。
  改 `closeEvent`/`accept`/`reject` 时三者的语义必须保持这个区分。
- **直播捕获兼容**：`stream_capture_mode` 开启时宠物与气泡必须是普通顶层 `Window`
  （清掉 `WS_EX_TOOLWINDOW/WS_EX_NOACTIVATE`），关闭恢复 Tool；不得因此禁用多宠。
- **动画缩略图**：分类子菜单只在 `aboutToShow` 填充；解码只能在非 GUI 线程（≤2），
  GUI 线程只转 `QPixmap`；`menu_animation_icons=False` 时不得发起解码。
- **点击/拖放监听**：`InteractionAdapter` 必须能 `attach_window()` 到新生成的子宠；
  `PetManager.spawn()/restore()` 负责调用。新增依赖点击/拖放的 feature 不许假设
  「只有启动时那只宠」。
- **隐藏态不冒泡**：`PetWindow.say()` / `show_image()` 必须先判 `isVisible()`；
  `set_visible(False)` 必须 `bubble.hide()`。第三方 feature 通过 presentation 端口
  说话时同样受这条闸门约束，不要自己直接操作气泡。
- **托盘菜单独立**：托盘右键菜单由 `CoreHost.build_tray_menu()` 构建，必须含
  「显示/隐藏桌宠」（隐藏后能只靠鼠标唤回）、设置、数据目录、重载、逐宠控制与退出；
  不要再用完整右键菜单代替托盘菜单。托盘左键也切换显示。
- **托盘 Context**：`TrayIcon._on_activated(Context)` 不得 `refresh()`/替换菜单；
  菜单动作在 `aboutToShow` 里原地重建。替换正在弹出的 context menu = 菜单空白。
- **自语出图**：`media/talk_images.pick_choice()` 是唯一抽图口径；`_speak()` 必须
  `try/finally` 保证异常后仍排下一次。图片目录无图时回退内置 `big_blue_fat_fish`；
  出图失败回退文字。点击台词与自言自语共用这套逻辑。
- **配图诊断**：`--check` 的 `self_talk_images` 字段是安装包素材/Qt 插件是否正常的
  第一证据；新增配图路径或插件时不要删它。

- **配图设置归位**：彩蛋与自言自语配图统一在「互动与物理 → 彩蛋与配图」；
  自言自语页不再重复放图片目录/大小/概率，避免两个入口互相覆盖。
- **鼠标穿透只在托盘**：右键菜单模板不含 `click_through`，旧布局由
  `migrate_p9_menu()` 幂等摘除；托盘「鼠标穿透」一次作用所有桌宠并气泡说明恢复位置。
  穿透开启后右键菜单自己点不到，托盘是唯一稳定恢复入口（同主分支）。
- **对话通道唯一**：mod 只能经 `HostPorts.chat`（`ChatPort`）驱动聊天窗口；窗口、
  Markdown、会话、取消都在 core。`token/done/error` 可能来自后台线程，controller
  必须用信号排队，不许在 worker 线程碰控件；`petcore/chat/` 保持 Qt-free。
- **对话窗是主分支移植**：`petcore/ui/chat/` 的现代双栏窗（`deepseek-sidebar` /
  `chat-main` / `chat-main-header` / `floating-composer`）是唯一实现，不许再另写
  一套极简窗口。窗口按 `(owner, pet_slot)` 隔离；`ChatPort.record()` 只写会话和
  已存在的窗口，**不得因后台结果主动唤出窗口**。
- **流式传输只在 core**：SSE/代理兜底/取消/错误分类都在 `petcore/api/chat.py`；
  扩展与 `petcore/chat/` 不得 import `petcore.net`/`petcore.api`（架构守卫）。
- **思考/联网传输只在 core**：`thinking` / `reasoning_effort` 的 payload、思维链
  `reasoning_content` 解析（只走 `on_reasoning`，不拼正文）、联网检索轮与
  `fetch_url` 都在 `petcore/api/chat.py`；搜索引擎实现只在 `petcore/net/websearch.py`。
  mod 只能传 `WebSearchOptions` 与回调；搜索 Key 只进钥匙串
  （owner `core.websearch`），`config.json`/`api.json` 不许出现。
- **截图冻结帧必须是 QImage**：`grab_screen_image()` 接收 Qt6 的 `QPixmap` 时要
  `toImage()` 并 `setDevicePixelRatio(1.0)`；覆盖层构造函数再做一次兜底。
  `QPainter.drawImage(QRect, QPixmap)` 会抛 TypeError，整层画不出来 = 全屏灰。
- **思考/检索进度只进已开窗口**：`ChatPort.reasoning()/status()` 不得创建或唤出
  对话窗；`reasoning`/`activity` 随 assistant 记录落盘并在重开会话时回显。
- **截图不落盘**：`ScreenPort.capture()` / `capture_region()` 返回内存 PNG；转 data URL
  由调用方用标准库完成，core 不写临时文件、日志不记录图片内容。
- **看看屏幕**：答复先落发起宠气泡，再 `ChatPort.record()` 静默入历史；默认不打开
  对话窗，只有 `ai_look_screen_auto_open` 为真才主动唤出。4 秒冷却与忙碌提示同主分支。
- **截图提问端口**：框选、窗口、多轮消息在 core（`ScreenAskPort`），模型调用由 mod
  在 `on_ask(question, png, history, slot)` 回调里完成；回调跑后台线程，只碰纯数据。
  截图问答标题固定 DS 鲸鱼；等待时 10% 抽鲸蛙，每次请求只抽一次，独立于菜单彩蛋。
  **历史每次采集独立**：`open()` 清空上一轮，只存内存、不落盘（图片受隐私约束，
  纯文本脱离图片没有追问语义）。
- **mod 运行时代码无 Qt**：`host/runtime.py` 这类运行时代码不得 import PySide6；
  需要回 GUI 线程一律 `ports.scheduler.call_later()`。只有设置页（`settings_page.py`
  这类受信 UI）可以用 QtWidgets。包入口用 `host/__init__.py:create_host` 时，
  loader 会按包加载并支持相对 import。
- **配置读取分两层**：运行时只经 `HostPorts.config`（只读 `ConfigPort`）；
  设置页作为 Core 托管的受信 UI，允许直接使用 `host.config`（ScopedConfig）。
  不许把 `config` 对象塞进业务运行时长期持有。
- **命令按宠派发**：`run_feature_command(..., slot=)` 对声明 `slot` 参数的扩展命令
  必须传入发起者；子宠菜单的 AI/截图不得落到主宠窗口。
- **聊天窗外观**：`chat_background` / `chat_accent` / `chat_follow_pet` /
  `chat_always_on_top` 四个键必须有设置入口；改完经
  `ChatController.apply_appearance()` 实时作用到已打开窗口。`chat_follow_pet`
  用 `PetWindow.pet_moved` + 40ms 合并定位，不许 60Hz 反复重排。
- **四条热键独立**：显示隐藏 / AI 对话 / 看看屏幕 / 截图提问各有独立 Win32 id 与
  配置键；注册失败必须气泡 + 设置行可见，扩展缺失时提示「AI 扩展未安装」。
- **气泡同层**：`always_on_top` 变化必须同步 `bubble.set_host_on_top()`，彩蛋弹窗用
  `EasterEggPopup(..., on_top=)`；气泡旗标统一由 `SpeechBubble._window_flags()` 生成，
  不许在别处直接 `setWindowFlags`（会漏掉置顶/不接受焦点）。
- **图片装载按 DPR**：彩蛋弹窗/气泡配图/菜单头像一律走
  `media/images.py` 的 `load_pixmap/scale_pixmap/logical_size`：逻辑上限 × 屏幕
  `devicePixelRatio` 解码并写回 pixmap DPR，QLabel 只设逻辑尺寸。禁止把「已缩到
  逻辑像素、DPR=1」的 pixmap 交给 QLabel（1.5 倍屏会二次放大 = 用户说的「发虚」）。


## 4. 变更纪律

- 行为修复先写会红的测试，再改产品代码；Qt 行为用真实事件循环或 `offscreen`。
- 不修改 `pet/` 产品代码来让 petcore 通过；需要适配时只改 `media/` 或
  `content/legacy.py`，并在 log 里说明。
- 不引入新依赖前先确认 `requirements.txt` / 现有 imports 是否已有；没有就说清楚。
- 不提交 git，除非用户明确要求。
- 临时脚本、截图、探针输出放 `.scratch/`，不要进版本库。

## 5. 验证命令

```bash
cd E:/Work/dsh-pet-0
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/test_petcore_*.py -q
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest \
  tests/test_petcore_*.py tests/test_architecture.py \
  tests/test_pr_report_discipline.py tests/test_ci_workflows.py -q
.venv/Scripts/ruff check pet/ tests/ petcore/
.venv/Scripts/python -m petcore --check
```

## 6. 文档地图

| 想知道什么 | 读什么 |
|---|---|
| 最终要做成什么样 | [`../docs/PETCORE-SPEC.md`](../docs/PETCORE-SPEC.md) |
| 分层、启动路径、数据目录 | [`../docs/PETCORE-ARCHITECTURE.md`](../docs/PETCORE-ARCHITECTURE.md) |
| mod 格式与加载 | [`../docs/PETCORE-MOD-FORMAT.md`](../docs/PETCORE-MOD-FORMAT.md) |
| 角色包与素材 | [`../docs/PETCORE-CHARACTER-PACKS.md`](../docs/PETCORE-CHARACTER-PACKS.md) |
| 批次与下一步 | [`../docs/PETCORE-ROADMAP.md`](../docs/PETCORE-ROADMAP.md) |
| 还差主分支什么 | [`../docs/PETCORE-MAIN-PARITY-BACKLOG.md`](../docs/PETCORE-MAIN-PARITY-BACKLOG.md) |
| 改过什么 | [`../docs/PETCORE-LOG-INDEX.md`](../docs/PETCORE-LOG-INDEX.md) |
| 上手命令与目录 | [`README.md`](README.md) |
