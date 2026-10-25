# petcore 变更日志索引

> 读取规则：**先读本表，只打开命中的 `LNNN` 条目**。完整的改动细节、验证命令与
> 遗留项在 [`PETCORE-LOG.md`](PETCORE-LOG.md)；本表只保留「一句话 + 关键词」，
> 避免把整份 log 塞进上下文。
>
> 写入规则：每次追加 log 条目时同步加一行；`tests/test_petcore_docs.py` 校验
> `LNNN` 一一对应。
>
> 编号约定：历史行里的 `P1-A…P8.4` 是旧编号，等价于
> [`PETCORE-ROADMAP.md`](PETCORE-ROADMAP.md) §0 的 `H1-A…H8.4`；
> 2026-10-22 起新计划使用 `P0–P6`，两套不要混用。

| 编号 | 日期 | 批次/主题 | 一句话 | 关键词 |
|---|---|---|---|---|
| L001 | 2026-10-20 | M0–M6 | 从 `main` 新建分支，落地可独立运行的 petcore 最小 core、mod 加载器、设置宿主与多屏几何。 | core、contracts、mod、--check、pack-legacy、多屏 |
| L002 | 2026-10-20 | P1-A | 右键/托盘菜单与设置页视觉对齐主分支，菜单改为可自定义布局。 | 菜单 QSS、图标、侧栏、MenuEditor、menu_layout |
| L003 | 2026-10-20 | P1-C | 设置/关于非模态可拖宠、大小 10–300%、设置实时预览、菜单默认隐藏大小、菜单/设置覆盖矩阵、文档体系。 | 非模态、实时预览、300%、coverage、spec/log/README/AGENTS |
| L004 | 2026-10-20 | P1-E | 贴边/落位/恢复/比例/跨屏迁移改用 `body_box` 身体框，透明画布允许出屏；记录 P1-F 边缘探头设计。 | body_box、贴边、clamp_body、body_rx、corner、edge probe |
| L005 | 2026-10-20 | P1-F | 边缘探头状态机、45° 旋转、命中反向映射、设置/菜单开关。 | edge probe、45°、PEEKING、旋转、head_box |
| L006 | 2026-10-20 | P1-B | 全局快捷键、自启 CLI、多实例、打包入口脚本、WebM→WebP 首跑供给。 | hotkey、autostart、instance、PyInstaller、provision |
| L007 | 2026-10-20 | P1-D | `pack-character` 从外部素材目录生成 content 角色包。 | character pack、pack-character、manifest、body_box |
| L008 | 2026-10-20 | P2-A | 关于并入设置、单进程多宠、Q弹/拖拽/弹弓/回旋/投喂/碰撞、菜单重排、本地 PyInstaller+Inno 构建。 | about、multi-pet、Q弹、physics、collision、PyInstaller、Inno |
| L009 | 2026-10-20 | P2-B1/B2 | 内置离线 mod 加载器与 12 个官方 mod、HostPorts 扩展、菜单/设置覆盖。 | builtin mod、ports、self-talk、quick-launch、quiet、links、memory、network、music |
| L010 | 2026-10-20 | P3 收口 | 设置页聚合到「扩展管理」页内分页；5 个 mod 移为 examples 可导入样板；快捷启动移入工具与帮助。 | settings tabs、ExtensionsPage、examples、allow_feature_mods、quick launch |
| L011 | 2026-10-20 | P3 收口 | 移动朝向按方向设置、位移按 move_curves 帧驱动，修复反向/走滑。 | facing、move_curves、move_position_at_frame、quantize_move |
| L012 | 2026-10-20 | P3 收口 | 子命令前的全局 `--root/--portable/--instance` 生效；裸 QWidget 设置页可见但标注不保存；重打包 0.1.0。 | CLI、subcommand、--root、ExtensionsPage、PyInstaller、Inno |
| L013 | 2026-10-20 | P4 收口 | 朝向口径改为主分支（right 才镜像）、回旋起表、碰边逐次反馈、探头吸附、多宠防穿模与落座、设置搜索/分页、安装器选装扩展与无终端窗口。 | facing、golden spin、bounce、edge snap、collision、spawn、search、Inno、trust |
| L014 | 2026-10-20 | P5 易用性 | 气泡贴头部锚点、台词多行大框、Enter 保存、免打扰页文案/状态、命令反馈 force、菜单对勾、碰撞改三圆链。 | bubble、anchor、QPlainTextEdit、Enter、quiet、force、checkmark、circles |
| L015 | 2026-10-20 | 碰撞修复 | `set_velocity` 重锚内部坐标（修瞬移）；被撞的探头宠物先退出探头再分离（修被撞斜）。 | teleport、set_velocity、probe、collision、tilt |
| L016 | 2026-10-20 | P5 net 测试 | 为 `petcore/net` 补 33 条传输兜底与错误分类单测；架构守卫未豁免 `net/` 的 urllib 导入仍红。 | net、urlopen、force_direct、classify、retry_after、architecture |
| L017 | 2026-10-20 | P6 动画节拍 | 待机一圈改为掷骰（修一直 idle）、gap 期间继续播待机、四项概率可调、播放动画菜单分组。 | idle、roll、weights、animation gap、re-arm、menu |
| L018 | 2026-10-20 | P6 事件动画 | `events/<group>` 独立为 GraphType.EVENT，`play_event()` 按名字/索引触发，余额动画不再混入随机动作。 | EVENT、event_group、balance、play_event、legacy |
| L019 | 2026-10-20 | P6 core 联网/API | 网络守卫改 allowlist；`petcore/net` + `petcore/api` + keyring + 设置页「API 与账户」+ `HostPorts.api`；构建脚本收集 keyring。 | net、api、keyring、ApiPort、api.json、settings、allowlist |
| L020 | 2026-10-21 | P7 探头/击飞 | 碰撞先授权击飞旋转再退出探头；飞行不掷骰/点击忽略；探头与彩蛋只播 idle/转向。 | collision_throw、throw egg、thrown、probe filter、click |
| L021 | 2026-10-21 | P7 安装/扩展管理 | setup 带鲸鱼娘图标；随附扩展改到 `{app}\mods`；扩展页改竖向导航+基础/加装分组；mod 中文名 `name_zh`。 | SetupIconFile、install_mods_dir、ExtensionsNav、name_zh、filter |
| L022 | 2026-10-21 | P7 彩蛋/音效 | 彩蛋图片弹窗与点击音效包（默认/小黄鸭/自定义）；碰撞/碰边复用音源。 | easter egg、click_sound_pack、duck、wav、QMediaPlayer |
| L023 | 2026-10-21 | P8 多宠/气泡/设置/打包 | 轻碰推动与探头优先、子宠单独退出、气泡跟随/图片、彩蛋菜单行、互动 8 分页、Core 特性归位、扩展分组折叠、安装目录页与菜单模板兜底。 | collision push、probe、quit_this、bubble follow、image、menu builder、host_page、collapsible、DisableDirPage、menu_template |
| L024 | 2026-10-21 | P8.1 字号/菜单/弹弓/直播 | 界面/气泡字号、彩蛋图片大小、自语配图概率、彩蛋置顶与菜单尾部、播放动画缩略图、弹弓右键抑制、点击监听补挂、X 保存、直播捕获兼容。 | ui_font_size、bubble_text_scale、self_talk_image_chance、migrate_p8_menu、thumbnail、slingshot、attach_window、stream_capture_mode |
| L025 | 2026-10-21 | P8.2 隐藏气泡/配图/托盘 | 隐藏态不冒泡并收起气泡；彩蛋与自语配图合并到「彩蛋与配图」；托盘菜单支持显示/隐藏、设置、逐宠控制与退出。 | hidden bubble、bubble hide、easter+self-talk images、tray menu、toggle visibility |
| L026 | 2026-10-21 | P8.3 托盘/自语出图 | 托盘菜单不再在 Context 时替换（改原地重建）；自语/点击台词共用配图选择器，失败回退文字且异常后继续排队；`--check` 增加配图目录/可读数。 | tray context menu、aboutToShow、talk_images、pick_choice、self_talk_images、readable |
| L027 | 2026-10-21 | P8.4 穿透归位/高清 | 点击穿透移出右键菜单改由托盘统一开关（p9 迁移）；彩蛋/气泡/头像按屏幕 DPR 解码，修 1.5 倍屏发虚。 | migrate_p9_menu、tray click-through、media/images、DPR、load_pixmap、logical_size |
| L028 | 2026-10-22 | P0 主分支对齐审查 | 新增主分支功能矩阵、AI 交接计划和审查报告；冻结每宠作用域、WorkerHost、迁移回滚、默认扩展和发布门。 | parity matrix、handoff、audit、scope、worker、migration、rollback |
| L029 | 2026-10-22 | P1 配置作用域/基础迁移 | 设置窗口绑定当前宠物；全局/每宠键分流；点击台词/自语按宠物运行；standalone 与 slot 基础迁移并备份。 | ScopedConfig、pet scope、settings target、legacy migration、slot、feature lifecycle |
| L030 | 2026-10-22 | P2 WorkerHost/离线接缝 | 真实子进程 WorkerHost、角色目录导入、Graph 类别映射、5 个官方 feature 默认安装。 | WorkerHost、JSONL、cancel、heartbeat、character importer、Graph、installer tasks |
| L031 | 2026-10-22 | P3 Core 账户/余额基础 | Core 账户服务、余额缓存/错误分类、钥匙串读取和 `ApiPort.fetch_balance()`。 | AccountService、BalanceResult、cache、keyring、ApiPort、DeepSeek |
| L032 | 2026-10-22 | P3 每宠会话/worker 请求接缝 | 增加按 slot/角色隔离的会话存储、消息限制和 WorkerSession.request 协议接缝。 | SessionStore、ChatSession、slot、character、request、delta、done |
| L033 | 2026-10-22 | 插件市场 v1 | 静态索引 + 多源 artifact + SHA-256 + 安装/更新/回滚 + 市场设置页 + `petcore market` CLI；npm 只留 URL 接口。 | market、index、sha256、Range、resume、backup、rollback、market-lock、page_market、allow_feature_mods |
| L034 | 2026-10-22 | 安装器口径修正 | 5 个官方扩展恢复默认不勾选（iss `Flags: unchecked` + 测试反转），文档口径同步；顺手修正 README 的安装位置。 | opt-in、unchecked、iss、installer、examples README |
| L035 | 2026-10-22 | 编号统一 | 历史批次改名 H1–H8.4，P0–P6 只表示未来交付阶段；ROADMAP §0 加换算表，SPEC/LOG-INDEX/INDEX 同步。 | numbering、H series、P0–P6、ROADMAP §0、mapping |
| L036 | 2026-10-22 | P3 流式/窗口/截图/热键 | Core 流式 SSE、ChatPort 聊天窗口、内存截图端口与四条可并存热键；菜单/设置同步。 | stream_chat、ChatPort、ChatWindow、ScreenPort、hotkeys、ai 快捷键 |
| L037 | 2026-10-22 | P3 ai.chat 扩展 | host-only AI 对话扩展（prompt/路由/截图提问/设置页）+ 安装器可选任务。 | ai.chat、host-only、prompt、vision、installer、opt-in |
| L038 | 2026-10-22 | 构建签名/打包收尾 | 本机开发证书签名 exe/setup（SAC 4551 拦截），构建脚本支持 -SignThumbprint，P3 安装包产出并验证。 | code signing、Smart App Control、4551、SignThumbprint、ISCC、setup |
| L039 | 2026-10-22 | P3 对话/识屏/截图提问 | 主分支现代双栏对话窗移植、看看屏幕气泡+静默入历史、框选截图问答窗与 10% 鲸蛙彩蛋、`ScreenAskPort`、按宠命令派发。 | ChatWindow、modern UI、record、ScreenAskPort、capture_region、jingwa、slot dispatch |
| L040 | 2026-10-22 | AI 边界收口 | `ai.chat` 拆成包入口+prompts/runtime/settings；线程安全 Scheduler、只读 ConfigPort、移除 SettingsPort；聊天窗背景/强调色/跟随/置顶设置与实时预览；截图历史明确不落盘。 | package entrypoint、SchedulerBridge、ConfigPort、runtime no Qt、apply_appearance、follow pet、trusted settings UI |
| L041 | 2026-10-22 | 截图灰屏 + 思考/联网 | 冻结帧强制 QImage/DPR=1（QPixmap 导致 drawImage 崩溃=灰屏）；thinking/reasoning_effort、思维链面板与回显；联网 planner（web_search/fetch_url）、四引擎、搜索 Key 只进钥匙串。 | grab_screen_image、QPixmap、reasoning_content、research、websearch、thinking、ChatPort.status |
| L042 | 2026-10-22 | 截图四动作 + 快速对话 | 动作条补齐提取文字/翻译/问问肥鱼/复制图像；OCR 归 `tool.ocr`（本地 rapidocr 优先、AI 兜底）；`on_action` 按 priority 回退；点桌宠气泡开快速对话并与完整窗共用会话。 | RegionPick、on_action、priority、tool.ocr、rapidocr、QuickChatPort、bubble.clicked |
| L043 | 2026-10-22 | 动作条对比度 | 显式深色按钮文字/禁用灰，修深色主题下浅条白字看不清；像素级回归 + 重建安装。 | QSS、ButtonText、对比度、screen-selection-bar |
| L044 | 2026-10-22 | AI 模块分布盘点 | core/mod 代码表、core 里没有的业务、启动/传输/窗口/OCR 实测占用与四项已知耦合；纯文档批次。 | AI 模块、core 占用、7.1MB、145MB、ChatTruncated、ARCHITECTURE 23 |
| L045 | 2026-10-22 | P4-a 取数/天气/文件解读 | 新增 `HttpPort`（按请求路由、共享 deadline、4MB 上限）与 `tool.weather`、`tool.file-reader` 两个可导入 mod；安装器两条 unchecked 任务；`files.read` 能力。 | HttpPort、fetch_url、prefer_direct、retry_statuses、tool.weather、open-meteo、tool.file-reader、on_drop、files.read |
| L046 | 2026-10-22 | P4-b 语音/音乐/循环 | Core 新增 `SpeechPort`（edge/豆包/MiMo/SAPI + 缓存/预检/重试/钥匙串）与 `play_animation(loop)`/`release_loop()`；`voice.chime`、`media.music` 重写为 1.1.0（歌词两源、SMTC、唱跳）。 | SpeechPort、edge-tts、SAPI、cache、preflight、voice.chime、media.music、lyrics、SMTC、loop、release_loop |
| L047 | 2026-10-23 | P4-b2 分组/卸载/气泡/音乐识别 | 右键「扩展」按 mod 分组、mod 设置页 H2/H3；`.trusted` 包可卸载（清单删除、保留未知文件与个人数据、草稿保护）；气泡 248→360 列宽 + 分页/页码/滚轮 + 副标题；音乐只识别已配置播放器、设置页切歌、气泡「我在唱《…》」。 | H2/H3、owner 分组、remove_at、install.json、trusted、bubble paginate、column_for_text、subtitle、music_filter、allowed_app_ids |
| L048 | 2026-10-23 | P4-b2.1 菜单/设置/气泡修正 | 扩展 hub 不再平铺 children、按 allowed 分组；`migrate_p10_menu` 把 links/快捷启动/网络/内存/免打扰搬回模板位置；expand 设置行改纵向；气泡改 `wordWrap=False` + 显式固定宽高，短句不再折行/裁切。 | extensions_hub、allowed、migrate_p10、p10、settingTextBlock、wordWrap、setFixedSize、heightForWidth、孤行 |
| L049 | 2026-10-23 | 设置窗口标题栏按钮 | `SettingsDialog` 补 `WindowMinMaxButtonsHint`，标题栏出现最小化/最大化；非模态与保存/取消语义不变。 | WindowMinMaxButtonsHint、showMinimized、showMaximized、settingsDialog |
| L050 | 2026-10-23 | P4-c1 窗口抓屏 + 主动识屏 | 前台窗口 hwnd/rect、`capture_window()`、dHash；`ai.chat` 8 s 看门狗（白名单/停留/限额/去重）、12 个 `ai_proactive_*` 全局键、菜单勾选项 + 设置分节；只冒气泡不唤窗。 | foreground_window、capture_foreground、dh_hash、image_hash、ProactiveWatcher、ProactiveLimiter、ai_proactive_*、ConfigPort.set、idle_seconds、ai.chat:proactive、GDI BitBlt、sample_foreground、SAC 4551 |

| L051 | 2026-10-23 | DPI 适配：模型图封顶/图标缩略图 | 新增 `VISION_MAX_EDGE` 与 `ScreenPort.shrink_for_vision()`（物理像素封顶 1024），AI 四处送图统一走它；菜单图标/动画缩略图按 `screen_dpr()` 物理绘制；SPEC §27 固化「逻辑 vs 物理」口径。 | DPI、devicePixelRatio、shrink_for_vision、VISION_MAX_EDGE、physical_side、availableSizes、缩略图、逻辑像素、物理像素 |
| L052 | 2026-10-23 | P4-c2 Agent 联动 | `ai.agent` 只读联动扩展：DSH 桥目录 + `agent-events/*.jsonl` + 自定义文件，六态 → 动作池/过程气泡/完成确认/音效；Core 加 `data_root()`/`visible()`/`animations()` 三条接缝与 13 个 `ai_agent_*` 键。 | ai.agent、Agent link、ByteTailer、GlobTailer、LinkEngine、六态、data_root、visible、animations、ai_agent_*、mod_agent |
| L053 | 2026-10-23 | P5-a1 灵动岛 v1 | 顶部胶囊 + CPU/内存/网络段 + 告警色 + 展开卡片 + 13 个 `island_*` 键；契约/布局零 Qt、采样 1 Hz、宽度只由模板驱动。 | 灵动岛、island、segments、layout、plan_info_row、+N chip、sysmon、netmon、island_metrics、dynamic_island、状态点 |

| L054 | 2026-10-24 | 已复现缺陷收口 | Python3.11清理、Qt菜单父子/刷新释放、非阻塞世代采样、折叠采样与Agent停止重启。 | onerror、QMenu、SamplingLoop、cancel、island、Agent |
| L055 | 2026-10-24 | 后台资源与逐域修复 | HTTP关闭、Speech线程归属、天气/文件/音乐/AI迟到结果和取消、proactive身份、MSG ABI。 | close、scheduler、generation、vision、SMTC、MSG |
| L056 | 2026-10-24 | 质量证据与阶段校正 | 五域审查、亮暗菜单回归、性能与源码实机、整仓失败归属；不宣布全绿/不进入分发。 | PR报告、性能、125%DPI、全量缺口、6签、8节日 |

| L057 | 2026-10-24 | P4-c3 A质量门禁 | 隔离环境、设置原生退出/菜单/Pillow根因修复；整仓9716passed正常退出、三遍高负载与本批实机证据；B–E尚未实施。 | Python3.11、DeferredDelete、QMenu、全量、性能、原生退出 |

| L058 | 2026-10-24 | P4-c3 B通用端口 | slot交付、DND汇总、单语音队列/实际播放完成及生命周期取消；整仓9729passed、源码Windows与高负载验证通过。 | speech、on_finished、notification、quiet、generation |

| L059 | 2026-10-24 | P4-c3 C | 待办调度、slot持久化与安全迁移，关联95passed，最终联合证据见L061 | todo、宽限、去重、迁移 |

| L060 | 2026-10-24 | P4-c3 D | 节日历法与生日调度、默认关闭和让位规则，关联126passed；联合验收见L061 | festival、生日、农历、去重 |


| L061 | 2026-10-24 | P4-c3 E | 48签/真实结束揭签/有界预热、chime让位；整仓9837passed正常退出、三遍高负载与实机/性能通过 | divination、48、on_finished、迁移、生命周期、性能 |

| L062 | 2026-10-24 | 分发详细交接与提交 | T00–T09、三worker写集与安全/验收边界；主交付 `b77d4436`，复验见交接报告 | handoff、分发、计划、多智能体、提交 |

| L063 | 2026-10-24 | 动画画质评估计划 | 同源素材/DPR/Q70证据、T00–T06串行步骤与停止门；仅文档落盘，产品未改 | 动画、DPR、Q70、小小桌宠、计划、未实施 |

| L064 | 2026-10-24 | 分发计划本机环境校正 | 路径/pwsh/venv(3.12.10)/PyInstaller/rapidocr 事实按本机重写，T00/T08 口径同步；文档批，整仓复跑 | 分发计划、环境、3.12、PyInstaller、rapidocr、全仓 |

| L065 | 2026-10-24 | P4-c3-D1/T01 契约冻结 | 预算/传输/来源三契约、fetch_artifact 签名、origin 剔除包内 .trusted；11+63 测试与 ruff 通过，解包预算待 T03 | 分发、ArchiveLimits、TransferSpec、PackageOrigin、trusted、契约 |

| L066 | 2026-10-24 | P4-c3-D1/T02+T03+T05 | 逐跳传输/解包预算/可复现构建器 三 worker 并行；46+62 测试、ruff、4 包构建与 verify 4/4；新增 allowed_hosts | 传输、Content-Range、416、预算、构建器、可复现、allowed_hosts |

| L067 | 2026-10-24 | P4-c3-D1/T04 | 市场安装接 fetch_artifact + limits、能力/api/core 四类交叉校验、锁失败回滚、回环 http 契约；1738 passed | 授权、verify_manifest、事务、回滚、allow_loopback_http |

| L068 | 2026-10-24 | P4-c3-D1/T06 | 根索引（blocked）+ file: 索引/artifact + 市场页销毁持有线程；22 passed，file: 从 42s 降到 0.67s | 根索引、file://、dispose、QThread、nofallback |

| L069 | 2026-10-24 | P4-c3-D1/T07（D1 收口） | 真实 ZIP + file: 索引的授权/安装/加载/升级/回滚/数据保真；5 passed，60 循环资源无残留 | 端到端、FeatureManager、回滚、SHA、资源循环 |

| L070 | 2026-10-24 | D2/T08 冻结包 | `-OutputRoot`/`-PythonPath` + iss 源目录覆盖（修「打旧包」）、开发证书签名、冻结包自检与四包安装；D1 验收说明 | 打包、签名、Inno、SAC、冻结包、验收说明 |

| L071 | 2026-10-24 | D2/T09 收口 | before/after 无回退、整仓 9941 passed、安装器四组合矩阵、发布手册；未发布 | 性能对照、整仓、安装器、发布准备 |
| L072 | 2026-10-25 | 市场生命周期与授权修复 | 应用级市场任务 registry、可恢复下载、feature 解包预算、file 授权、结构化回滚、candidate/published 索引状态；90 passed | QThread、resume、archive limits、file://、rollback、candidate |
| L073 | 2026-10-25 | WorkerHost 与 DPR 渲染收口 | worker 握手/心跳/取消/代次拒收，帧按屏 DPR 使用物理像素并保留镜像；5 passed | worker、generation、heartbeat、DPR、frame_pixmap |
| L074 | 2026-10-25 | 重构收尾状态与交付证据 | candidate/published 文档边界、市场/Worker/DPR 收口范围、最终门禁待补原始输出 | 交付、parity、handoff、验收边界 |

| L075 | 2026-10-25 | 运行时迁移与 Worker 收口 | 迁移状态/诊断、session/todo schema、Worker 有界退出和非法消息拒收；新增 156 行回归 | migration、schema、Worker、shutdown |
| L076 | 2026-10-25 | 角色导入与媒体生命周期 | ZIP 安全导入、点击按下/释放 token、彩蛋头像/提示、关闭音频取消 | character、ZIP、click sound、easter egg |
| L077 | 2026-10-25 | parity 设置与动画入口 | ZIP 设置入口、余额异步查询、彩蛋设置契约、GraphType 懒加载菜单 | settings、balance、GraphType、menu |
| L078 | 2026-10-25 | 重构收尾文档与 petcore-only 最终门禁 | 运行时/媒体/parity 状态、最终报告、交接断点；petcore 1479 passed，专项门禁 302 passed，Ruff 通过 | 交付、petcore-only、报告、handoff、缺口 |

| L079 | 2026-10-25 | 候选包构建交接与弱模型任务说明 | PyInstaller/Inno Setup、隔离验收、SHA 证据、停止条件与 petcore-only 门禁；不上传 Release | 候选包、安装器、交接、证据 |
| L080 | 2026-10-25 | petcore 摸头互动 | 头部命中、连续往返判定、可配置单次动画池、设置契约与回归证据；1490 passed；实现提交 `2a5f80e9` | head_pat、head_box、InteractionPage、动画池、生命周期 |
| L081 | 2026-10-25 | P5 收口 | 灵动岛、余额、菜单/设置几何、性能治理和 Core 更新服务已实现，petcore-only 门禁通过，冻结包与 GPU/FPS 实机留缺口。 | island、balance、UI、performance、update、petcore-only |

| L082 | 2026-10-25 | P5 更新取消与可选探针收尾 | 更新下载中/取消状态和 generation 拒收，GPU/FPS 可选 snapshot 接入；Ruff、聚焦 121、CPU 压力 3×121、petcore 1513 通过；实机/冻结包仍留缺口。 | update、cancel、GPU、FPS、island、petcore-only |
