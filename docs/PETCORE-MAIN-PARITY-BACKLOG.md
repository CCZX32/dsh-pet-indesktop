# 主分支 ↔ petcore 功能差距台账

> **基线**：`feat/petcore-vpet-architecture`（petcore v0.1.0，P8 收口）
> **对照对象**：主分支旧架构 `pet/`（v4.3.4 系列）
> **用途**：这是“还差什么”的唯一清单。每轮收口时更新状态；新发现但本轮不做的
> 缺口先记在这里，再决定进哪个批次。改代码前先查本表，避免把“示例 mod”当成
> “已对齐”。
>
> 状态口径：
> - **已对齐**：用户可见行为与主分支等价，且有测试或实机证据。
> - **部分**：有入口/降级实现，但形态或能力弱于主分支。
> - **未做**：petcore 完全没有对应能力。
>
> 关联文档：[`PETCORE-SPEC.md`](PETCORE-SPEC.md)（最终形态）、
> [`PETCORE-ROADMAP.md`](PETCORE-ROADMAP.md)（批次）、
> [`PETCORE-LOG-INDEX.md`](PETCORE-LOG-INDEX.md)（改动史）。

## 1. 已对齐 / 比主分支更强

| 功能域 | 行为 | 证据 |
|---|---|---|
| 窗口与输入 | 透明置顶工具窗、逐像素命中、点击穿透（开关只在托盘菜单 + 设置页）、窗口置顶、锁定位置、Shift 拖拽 | `tests/test_petcore_geometry.py`、`test_petcore_interaction.py` |
| 拖拽物理 | 弹簧跟随、松手按轨迹甩出、静止放手下落、甩出力度四档 | `engine/physics.py`、`test_petcore_interaction.py` |
| Q 弹 / 回旋 / 弹弓 / 投掷 | Q 弹、黄金回旋（含“跳过点击动画”子项）、弹弓瞄准发射、飞行弹跳逐次反馈 | `ui/effects.py`、`ui/motion.py`、`ui/slingshot.py` |
| 边缘探头 | 贴边 45° 探头、点击拉直、5 秒回探头、探头期只播 idle/转向、拖出甩飞授权击飞旋转 | `ui/edge_probe.py`、`tests/test_petcore_edge_probe.py` |
| 多宠 | 单进程多宠（最多 16）、独立配置 `config-pet-N.json`、落座避让、碰撞冲量、轻碰推动、探头宠不可被轻碰推走 | `ui/pet_manager.py`、`tests/test_petcore_pet_push.py` |
| 动画节拍 | 待机一圈掷骰、四项行为权重可调、动作间隔、播放速率、手动播放入口、事件动画 `play_event()` | `engine/behavior.py`、`tests/test_petcore_animation.py` |
| 气泡 | 头部锚点、跟随桌宠移动、文本/图片两种内容、彩蛋图片可进气泡；气泡与彩蛋窗跟随宿主置顶（同图层） | `ui/bubble.py`、`tests/test_petcore_bubble.py` |
| 大小 | 10%–300%、滑条 + 手输 + 四档预设；右键默认隐藏大小 | `engine/geometry.py`、设置「外观与交互」 |
| 设置 | 8 个侧边栏页、页内分页、搜索到行、实时预览、Enter 保存、非模态 | `ui/settings/`、`test_petcore_settings.py` |
| 菜单 | 默认顺序对齐主分支、菜单编排器、可隐藏/排序/别名/图标、勾选项对勾；彩蛋固定第一项、播放速率默认隐藏 | `menu_templates/petcore-default-v1.json`、`test_petcore_menu_layout.py` |
| 动画菜单预览 | 分类子菜单懒加载 + 代表帧缩略图（内存/磁盘缓存、2 线程、可关） | `media/thumbnails.py`、`test_petcore_thumbnails.py` |
| 直播捕获 | `stream_capture_mode` 切普通顶层 Window（含气泡），OBS/直播姬可枚举 | `platform/win.py`、`test_petcore_stream_mode.py` |
| 字号与气泡缩放 | 界面字号 10–18、气泡字号 50–300%、自语配图概率/大小可调 | `config.py`、`bubble.py`、`test_petcore_self_talk.py` |
| 彩蛋 | 菜单首行头像 + 标题 + 「请点击」、气泡内显示图片、独立窗口模式、目录/标题/开关可配 | `ui/easter_egg_entry.py`、`test_petcore_easter_egg.py` |
| 音效 | 点击音效包（默认/小黄鸭/自定义文件/文件夹），碰撞/碰边复用 | `media/click_sound.py` |
| 扩展体系 | mod manifest/授信 `.trusted`/安装卸载/CLI、设置页聚合、加载诊断 | `mods/`、`test_petcore_loader.py` |
| 安装与自启 | 单实例锁、开机自启、托盘、多实例数据根、安装向导选装扩展 | `platform/`、`packaging/petcore.iss` |
| 角色资源 | WebM/GIF/帧序列、`body_box`/`head_box`、`move_strides`/`move_curves`、`pack-character` CLI | `content/`、`tests/test_petcore_character_pack.py` |
| 联网底座 | 代理失败自动直连、五类失败分类、allowlist 架构守卫、keyring 密钥 | `petcore/net/`、`petcore/api/`、`test_petcore_net.py` |

## 2. 部分对齐（有入口但弱于主分支）

| 功能域 | 主分支 | petcore 现状 | 计划 | 验收 |
|---|---|---|---|---|
| 多屏 | overlay 覆盖虚拟桌面、逐屏世界、混合 DPI | 每宠一窗 + `multi_screen` 钳制；混合 DPI/跨屏连续性未实机 | P9 | 双屏不同缩放下拖拽/投掷/探头 |
| 角色导入 | 设置内 GUI 导入、预览、切换 | 只有 `petcore pack-character` CLI 与放置目录扫描 | P9 | 设置内导入 zip/目录并预览 |
| 动画目录 | 13 类 GraphType 全映射（Touch_Head/Say/Sleep/StartUP/Work/Raised_Dynamic…） | 只映射 idle/turn/move/click/drag/random/events；其余无播放入口 | P12 | 每类至少一个入口 + 播放测试 |
| 彩蛋 | 头像/提示行/标题/目录均可配 | 菜单行头像取目录首图（不可单独配）、提示固定「请点击」；图片大小/字号已可调 | P9 | 设置可配 avatar/hint |
| 点击音效 | duck 按压/释放配对音 | 单次随机音 | P9 | 按下/松开配对 |
| 音乐 | SMTC/播放器识别、歌词、唱跳动画、播放器启动 | `media.music` 示例只有系统媒体键 | P10 | 歌词同步 + 唱歌动画 |
| 语音 | TTS provider、自言自语语音、口型、语音报时 | `voice.chime` 示例用 `QTextToSpeech` 朗读时间 | P10 | provider 抽象 + 口型 |
| 设置域 | 桌宠/互动/菜单/语音/文件识别/AI/自动化/关于 | 8 页；缺 AI/自动化/语音/文件/更新/桌面组件/天气 | P9–P11 | 每域有页与搜索 |
| 右键菜单 | AI 对话/看屏幕/截图提问/音乐控制/天气/余额/Agent/主动识屏/待办/报时/抽签/节日/检查更新 | AI 三项已加（P3）；其余仍缺 | P4 | 菜单项 + 设置落点 + coverage |
| 诊断/性能 | FPS/GPU/网络监控、卡顿采样 | 关于页诊断文本 + 日志 | P12 | 实时指标页 |
| 平台 | Windows/macOS 实机 | 仅 Windows 实机；macOS/Linux 未验证 | P12 | 两平台冒烟 |

## 3. 未做（主分支有、petcore 完全没有）

### 3.1 账户 / AI / 识屏 / Agent

| 功能 | 说明 | 计划 |
|---|---|---|
| DeepSeek 账户与余额 | 登录态、token、余额查询、余额档位动画 | P8 后续（`petcore/account/`） |
| AI 对话 | chat/persona/快捷对话/模型路由/聊天记录 | 部分（P7 收口）：Core 已移植主分支现代双栏对话窗（侧栏会话、Markdown 气泡、附件、置顶）、流式/停止/会话落盘；外观四项（背景/强调色/跟随/置顶）有设置入口并实时预览；**深度思考**（`thinking` + `reasoning_effort`、思维链折叠面板、按会话回显）与**联网搜索**（规划轮 + `web_search`/`fetch_url` 工具、资料注入、状态行、博查/Tavily/百度/DDG 四引擎、搜索 Key 只进钥匙串）已接。`ai.chat` 仍负责 prompt/路由，运行时代码无 Qt。快捷对话、历史会话批量管理未做 | P7 / P4 |
| 看看屏幕 | 整屏识屏、气泡答复、同步进聊天记录 | 已对齐（P3 收口）：气泡答复 + `ChatPort.record()` 静默入历史；默认不主动唤出窗口（`ai_look_screen_auto_open` 开关）；4 秒冷却与忙碌提示同主分支 | 保持 |
| 截图提问 / 主动识屏 | 框选、截图问答浮窗、视觉模型、独立彩蛋 | 部分：Core 框选覆盖层 + 截图问答浮窗（多轮、图片只读内存、DS 鲸鱼标题、10% 鲸蛙加载彩蛋）；覆盖层冻结帧已强制为 QImage/DPR=1（此前 QPixmap 会让整层画不出来，表现为全屏灰色）；OCR/翻译/复制动作条、主动识屏与每日预算未做；HDR 屏仍未移植主分支 DXGI FP16 抓屏（颜色可能发灰） | P4 |
| Agent 联动 | DSH/Claude/Cursor 等事件、本轮消费、Agent 六态动画 | P10 |
| Worker 运行时 | `contracts/worker.py` 已有协议，执行层未实现 | P9 |

### 3.2 内容与提醒

| 功能 | 说明 | 计划 |
|---|---|---|
| 天气 / 城市 | 天气查询、菜单、气泡/灵动岛展示 | P11 |
| 灵动岛 | 刘海/顶部胶囊、分段、聊天入口、与桌宠碰撞 | P11 |
| 文件识别 | 拖文件解读、菜单入口、设置页 | P11 |
| 检查更新 / 在线更新 | 版本检查、下载、替换、回滚 | P11（需确认 Core 自更新是否仍是非目标） |
| 待办/节日/报时/抽签官方化 | 目前是 `examples/petcore-mods/` 可导入样板，不是默认功能 | P11 |
| 歌词 / Now Playing / 唱歌 | 播放器识别、歌词对齐、唱跳动画 | P10 |
| TTS provider / 自语语音 / 口型 | 多后端、音色语速、口型同步 | P10 |

### 3.3 交互与系统

| 功能 | 说明 | 计划 |
|---|---|---|
| 三个全局热键 | `open_chat`/`look_screen`/`screen_capture` | 已对齐（P3）：四条热键并存、失败可见 | 保持 |
| 预测预热 / 共享解码 / FPS 治理 | 性能层仍在 backlog | P12 |
| VPet PNG 后端 | 直接读 VPet 角色包 | P12 |
| macOS / Linux | 打包、输入、窗口行为 | P12 |

## 4. 默认安装口径差异（容易误判为“已对齐”）

以下 5 个扩展在 `examples/petcore-mods/`，安装向导勾选才会装到
`{app}\mods\<id>`；不勾选时菜单/设置里完全没有：

`fun.divination`、`fun.festival`、`reminder.todo`、`voice.chime`、`media.music`。

因此**不能**把“示例 mod 存在”当成“默认功能已交付”。要宣称对齐，必须在
安装向导勾选后跑一遍真实安装验收。

## 5. 本轮（P8）已修

| 问题 | 处理 |
|---|---|
| 打包漏 `menu_templates/` 导致右键缺「播放动画/彩蛋图片」 | 构建补 `--add-data`；`load_default()` 内置兜底常量；`--check` 报告 `menu_template`；合并结果落盘 |
| 子宠右键退出把主宠一起退掉 | `PetWindow.quit_from_menu()`：子宠只 `close_slot` |
| 走路宠物推不动别人 / 反向卡死 | 轻碰不再切 `thrown`、不再取消移动计划，改为平移计划继续走 |
| 走路宠物把探头宠物挤下边缘 | 轻碰时探头视为无限质量，只推开走路宠物 |
| 气泡不跟随桌宠 | `moveEvent` 合并后 `bubble.reposition()`；缩放后重排 |
| 气泡不显示彩蛋图片 | `SpeechBubble.show_image()`；彩蛋默认气泡显示，可切独立窗口 |
| 扩展管理分组错误 / 不能折叠 | 可折叠组头；setup 5 个归「加装」；7 个 Core 特性并入 Core 设置页 |
| 「互动与物理」太长 | 8 个页内分页 |
| setup 不显示安装路径 | `DisableDirPage=no` + `UsePreviousAppDir=yes` + 旧路径预选 |

## 5.1 P8.1 已修

| 问题 | 处理 |
|---|---|
| 字号/图片大小不可调 | `ui_font_size`（设置/菜单/彩蛋行）、`bubble_text_scale`（气泡）、`easter_egg_image_scale`、`self_talk_image_scale` |
| 自言自语从不出图 | `self_talk_image_chance`（默认 30）+ 图片目录；失败回退文字 |
| 右键菜单「播放速率」占位 | 默认隐藏（菜单编辑器仍可打开） |
| 弹弓发射后松右键弹菜单 | 瞄准/发射后 0.35s 内抑制 `contextMenuEvent` |
| 点击台词要开一次设置才生效 | 监听补挂到新子宠 + 点击台词 `force=True` |
| 设置 X 关闭不保存 | X = 保存关闭；取消/Esc 仍恢复快照 |
| 彩蛋按钮位置不显眼 | 固定菜单第一项；设置项在分界线之上，分界线下方只有退出 |
| 直播软件抓不到桌宠 | `stream_capture_mode` 切普通顶层 Window（含气泡） |
| 播放动画没有预览 | 分类子菜单懒加载 + 代表帧缩略图（2 线程、可关） |

## 6. 维护规则

1. 发现新差距先加一行，再决定批次；不要在 roadmap 里另起一份清单。
2. 完成一项时把状态改为「已对齐」，补测试名或实机记录，并写进
   `PETCORE-LOG.md`（编号只看 `PETCORE-LOG-INDEX.md`）。
3. 「示例 mod」和「默认功能」必须分开写；默认安装口径见第 4 节。
4. 验收方式必须是可复现的命令或明确的实机步骤，不写“应该没问题”。

## 7. 2026-10-22 审查冻结补充

主分支完整功能矩阵见 [`PETCORE-FUNCTION-MATRIX-2026-10-22.md`](PETCORE-FUNCTION-MATRIX-2026-10-22.md)。
本轮新增的 P0 缺口：

- **每宠配置作用域**：设置窗口和内置 feature 仍读取 `host.config`，必须绑定当前宠物；
  `PetManager.SHARED_KEYS` 不能继续同步角色、缩放、播放速率、台词和音效等每宠键。
- **迁移与回滚**：v4 全局配置、slot 配置、会话、待办、API 规格和凭据引用尚无迁移协议。
- **WorkerHost**：只有协议和端口，没有真实子进程宿主、心跳、取消、超时、重启和代次拒收。
- **账户**：API 设置已存在，`petcore/account/`、余额缓存和额度服务未实现。
- **默认安装**：5 个 example mod 仍不能按“示例存在”计为默认功能；安装向导里它们是可选安装，默认不勾选。

有意差异：播放速率维持 `0.5–2.0x`；不支持 VPet LPS/PNG；首轮最多 16 只桌宠。

## 8. P1 基础作用域收口（2026-10-22）

| 项 | 状态 | 证据 |
|---|---|---|
| 设置窗口绑定当前宠物 | 已对齐 | `test_settings_dialog_binds_to_the_clicked_child_pet` |
| 每宠/全局配置读写分流 | 已对齐 | `tests/test_petcore_config_scope.py` |
| 点击台词/自语按宠物分流 | 已对齐 | `test_petcore_click_listeners.py`、`test_petcore_self_talk.py` |
| 旧 standalone 与 slot 基础迁移 | 已对齐 | `test_legacy_config_and_slot_profiles_migrate_with_backup` |
| 会话/待办/API 文件迁移 | 未做 | 等待对应业务消费者阶段 |

## 9. P2 Worker/离线接缝（2026-10-22）

| 项 | 状态 | 证据 |
|---|---|---|
| 统一 WorkerHost | 已对齐（基础） | `tests/test_petcore_worker.py` 真实子进程测试 |
| 角色目录 GUI 导入 | 已对齐（基础） | `tests/test_petcore_character_pack.py` |
| VPet Graph 类别寻址 | 已对齐（映射） | `build_animations()` 文件夹映射测试 |
| 5 个官方 feature 可选安装（默认不勾） | 已对齐（安装任务） | `test_official_feature_tasks_are_opt_in` |
| 旧 `pet` 媒体后端解耦 | 未做 | `petcore/media/backends.py` 仍为适配层 |
| AI/识屏/Agent worker 业务 | 对话与截图提问已接（P3）；Agent/OCR/翻译未做 | P4 |

## 10. P3 Core 账户基础（2026-10-22）

| 项 | 状态 | 证据 |
|---|---|---|
| Core 余额服务/缓存/错误分类 | 已对齐（基础） | `tests/test_petcore_account.py` |
| `HostPorts.api.fetch_balance()` | 已对齐（协议） | `tests/test_petcore_api.py`、account tests |
| 余额菜单、自动刷新、档位动画 | 未做 | 等异步 UI/worker 阶段 |
| AI/识屏/Agent 业务 | 对话与截图提问已接（P3）；其余未做 | P4 后续 |

| 每宠聊天会话存储 | 已对齐（基础） | `tests/test_petcore_sessions.py`；尚未接入聊天 UI |
