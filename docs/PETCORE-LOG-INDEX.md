# petcore 变更日志索引

> 读取规则：**先读本表，只打开命中的 `LNNN` 条目**。完整的改动细节、验证命令与
> 遗留项在 [`PETCORE-LOG.md`](PETCORE-LOG.md)；本表只保留「一句话 + 关键词」，
> 避免把整份 log 塞进上下文。
>
> 写入规则：每次追加 log 条目时同步加一行；`tests/test_petcore_docs.py` 校验
> `LNNN` 一一对应。

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
