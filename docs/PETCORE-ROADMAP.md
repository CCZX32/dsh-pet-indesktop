# petcore 路线图

> 基线：`feat/petcore-vpet-architecture`，2026-10-20。状态以实际验证为准，未跑过的项不写成通过。

## 0. 编号约定（2026-10-22 起）

两套编号不要混用：

- **P0–P6**：2026-10-22 起的**交付阶段**，只出现在 §20、`PETCORE-HANDOFF-PLAN-2026-10-22.md`
  和后续新报告里。
- **H1–H8.4**：**历史批次**（重构完成期），由旧的 `P1-A…P8.4` 改名而来，只用于回顾。
  历史文档（`PETCORE-LOG.md`、`docs/PR-REPORT-PETCORE-P1…P8…`）保留旧写法，按下表换算。

| 旧写法 | 新写法 | 主题 |
|---|---|---|
| P1-A | H1-A | UI 风格对齐 |
| P1-B / P1-C / P1-D / P1-E / P1-F | H1-B / H1-C / H1-D / H1-E / H1-F | 核心体验、窗口与设置、角色包、贴边、探头 |
| P2-A / P2-B | H2-A / H2-B | 交互/多宠/关于、内置 mod |
| P3 / P4 / P5 / P6 | H3 / H4 / H5 / H6 | 收口、安装器、易用性、动画与联网 |
| P7 | H7 | 探头/击飞与安装治理 |
| P8 / P8.1 / P8.2 / P8.3 / P8.4 | H8 / H8.1 / H8.2 / H8.3 / H8.4 | 多宠/气泡/设置、观感/菜单/弹弓、隐藏气泡与托盘、托盘与出图、穿透归位与高清 |

> `M0–M6` 是初始 core 里程碑，与上面两套都不同轴，保留原名。

## 1. 本轮（M0–M6）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 分支、venv、路径/配置/日志、contracts、`--check` 骨架 | 完成 |
| M1 | GraphCatalog、动画链、行为权重、位移/夹取、状态 | 完成（单测通过） |
| M2 | WebP 帧序列 / WebM / GIF 后端、ClipLibrary、音效原语 | 完成（单测 + 实机首帧通过） |
| M3 | mod manifest/loader/state/install/CLI、旧素材只读 provider | 完成（33 条 mod 测试通过） |
| M4 | 透明窗、逐像素穿透、多屏、会话结束、自启、气泡、菜单/托盘 | 完成（无头测试 + 实机窗口截图；真双屏未验） |
| M5 | 设置宿主与五个 Core 页面 | 完成（7 条无头测试通过） |
| M6 | 文档、PR 报告、结构守卫、实机证据 | 完成（本轮范围） |

## 2. 后续（按批次顺序）

| 批次 | 内容 |
|---|---|
| **H1-A UI 风格对齐（已完成）** | 右键/托盘菜单换成主分支同款视觉：浅/深 QSS、26px 行高、图标列、勾选/子菜单箭头、分隔符、跟随系统深浅；设置页补齐主分支视觉骨架：侧栏 34px 行高 + 3px 选中强调条 + 图标、页面标题 22px、卡片与行度量、内容宽度上限、搜索状态行；用实机截图与主分支并排对照。 |
| **H1-C 窗口与设置体验（已完成）** | 设置/关于改非模态，打开时可拖动桌宠；大小改为 10–300% 滑条 + 手输百分比；设置实时预览、保存落盘、取消回滚；大小默认移出右键菜单；菜单项→设置入口覆盖矩阵；spec/log/log-index/README/AGENTS 文档体系。 |
| **H1-B 核心体验（已完成，打包未实测）** | 全局快捷键、开机自启 CLI、多实例（每实例一只宠）、打包入口脚本、WebM→WebP 首跑供给/世代 GC 包装。 |
| **H1-D 角色资源包导入（已完成）** | `pack-character` 从 manifest+媒体目录生成 content mod（mod schema 1 + `character` 字段）；校验/复制/硬链接；安装复用 `mods install`。 |
| **H1-E 贴边按身体框（已完成）** | 位置钳制、右下角/主屏落位、位置恢复/比例/跨屏迁移改用 `body_box × scale`；透明画布允许出屏；旧配置回退旧比例。 |
| **H1-F 边缘探头（已完成）** | 45° 探头状态机、`body_box` 投影宽度、探头放宽域、设置/菜单开关、旋转渲染与命中反向映射；`head_box` 预留。 |
| H2 功能域迁包（第一批） | 无网络/无 worker：F08 台词、F10 趣味、F07 提醒、F11 快捷启动；每域一个 `mods/<id>`。 |
| H3 功能域迁包（第二批） | 平台适配：F04 账户、F05 音乐、F06 语音、F09 灵动岛；随后 worker 三域：F01 屏幕理解、F02 AI、F03 Agent。 |
| H4 取代旧壳 | 新壳功能齐备后切换发布入口，`pet/` 收敛为兼容层，最终删除。 |

## 3. H1-A：风格对齐的范围与验收

状态（2026-10-20）：已完成。默认菜单顺序、可自定义布局、编辑器、QSS/图标、设置页侧栏骨架均已落地；浅/深截图见 `.scratch/petcore-evidence/{menu,settings-menu}-*.png`。

### 3.1 右键/托盘菜单（真正的缺口）

现状：`MenuModel` 已经支持动作/勾选/子菜单/顺序/隐藏，但 `build()` 用的是 Qt 原生 `QMenu`，没有主分支的视觉。

要移植：

- QSS：`QMenu` 背景/边框/圆角、`::item` 26px 行高与内边距、`::item:selected`、`::item:disabled`、`::separator`、`::indicator`、子菜单箭头；浅/深两套 token，跟随系统。
- 图标列：把主分支 `context_menus/icons.py` 里与菜单相关的绘制逻辑**移植到 `petcore/ui/icons.py`**（不 import `pet`，保持架构守卫），给每个 Core 菜单项和 mod 菜单项配图标。
- 结构：补 `separator` 贡献类型与分组语义；角色/缩放子菜单保持现状。
- 交互：键盘上下/回车/ Esc、点击外部关闭、菜单出现在光标上方/下方时不出屏、勾选项状态实时反映配置。

验收：浅/深两套实机截图与主分支并排；菜单项高度、图标尺寸、分隔符间距逐项对照；`test_petcore_menu.py` 增加 QSS token 与分隔符/图标断言；不新增 `pet` import。

### 3.2 设置页（已对齐一部分）

现状：`petcore/ui/settings/style.py` 已经用主分支的浅/深调色板与圆角（12px 卡片、7px 输入/按钮），差在骨架细节。

要补齐：

- 侧栏：行高固定 34px、选中态 3px 左侧强调条（与强调色同源）、图标列；换主题时按记录重画图标。
- 页面：标题 22px、区块标题/说明层级、卡片内边距与行距、表单阅读宽度上限 800px、侧栏最小宽度。
- 搜索：结果为空时的状态行文案与位置。
- 视口：900×620 与 720×500 两档、100%/125%/150% DPI 下无裁切、无横向滚动。

验收：与主分支同页并排截图；`test_petcore_settings.py` 增加行高/强调条/宽度上限/空搜索断言；实机截图进 PR 报告。

### 3.3 顺序与成本

先菜单（所有 Core 命令与后续 mod 入口都吃这套样式），再设置页。两项都是视觉收口，不改数据模型与端口；预计各 1–2 天，必须先出截图再合。

## 4. Core / mod 边界

Core 只保留：生命周期、窗口与交互、动画/基础物理、通用呈现、菜单/设置宿主、配置与扩展宿主、最小 fallback。

F01–F11 一律做成 mod。跨域联动只走端口、事件与能力检查，不互相 import。

## 5. 明确延后

- 每屏多宠、跨进程碰撞 IPC、overlay 每屏 `ScreenHost`；
- 桌面通知、全局快捷键、自动光标隐藏；
- 配置多槽位、备份/迁移、Core 自更新、keyring；
- Agent 联动动画、音乐唱歌、`animation_gap`、共享解码 broker、预测预热；
- WebM→WebP 转换、世代退役与 GC；
- VPet 素材导入与 PNG 序列后端（只留接口）。

## 6. H1-C 验收（2026-10-20）

| 项 | 判定 |
|---|---|
| 设置/关于可移动桌宠 | 两个窗口均为 `NonModal`；打开时拖动/点击/滚轮桌宠仍有效。 |
| 大小 | 滑条 10–300%、数字框可直接输入、四档预设与恢复默认；`Config`/`PetState`/`PetWindow` 共用夹取。 |
| 实时预览 | 改角色/大小/置顶/穿透，桌宠立即变化；点保存才写 `config.json`；取消/关闭恢复快照。 |
| 菜单默认 | 默认布局不含「大小」；菜单编辑器可重新勾选；子菜单含「自定义大小…」。 |
| 菜单/设置一致性 | `coverage.py` 覆盖所有 Core 菜单项（`modern_settings` 豁免），测试守住。 |
| 文档 | `PETCORE-SPEC.md`、`PETCORE-LOG.md`、`PETCORE-LOG-INDEX.md`、`petcore/README.md`、`petcore/AGENTS.md` 均登记在 `docs/INDEX.md`。 |

## 7. H1-E 贴边身体框（2026-10-20 已完成）

| 项 | 判定 |
|---|---|
| 单屏贴边 | 身体框左右缘贴屏，窗口透明边可越界；`clamp_body()` 是唯一入口。 |
| 多屏 | 身体跨屏缝合法；落进屏间空洞按最近屏收口（`clamp_body_to_screens()`）。 |
| 恢复 | `body_rx/body_ry` 优先；旧 `rx/ry` 回退；选屏用身体矩形。 |
| 落位 | 右下角身体右缘留 24px、身体底贴可用区底；主屏同理。 |
| 回退 | 无 `body_box` 时整窗钳制，行为与改造前一致。 |

## 8. H1-F 边缘探头（2026-10-20 已完成）

- 配置/入口：`edge_probe_enabled`（默认关）、设置「外观与交互」复选框、右键「桌宠控制」勾选项；`coverage.py` 登记。
- 纯几何：`engine/edge.py` 的 `edge_side_at_rest()` / `rotated_bounds()` / `probe_target_x()` / `probe_body_bounds()`；探头放宽域必须减去 `body_local.x`。
- 控制器：`ui/edge_probe.py`，`QTimer(16ms)` + 可注入时钟，状态机 `OFF/ENTERING/PEEKING/STRAIGHTENING/STRAIGHTENED/RETURNING`。
- 渲染/命中：探头姿态绕帧中心旋转；`is_transparent_at()` 反向旋转后再做 alpha 判定；点击由探头消费，拖动取消探头。
- 验收：左/右缘 45° 部分出屏（body 投影约 55%）、点击拉直、5s 回探头、拖走取消、关闭开关恢复常规钳制；macOS/Linux 只做无头几何测试并如实登记。

## 9. H1-B 核心体验（2026-10-20 完成；打包未实测）

| 项 | 状态 |
|---|---|
| 全局快捷键 | 完成：`hotkey_spec` + Windows `RegisterHotKey`，设置页可改；真实按键未在本轮自动化验证。 |
| 开机自启 | 完成：源码/打包命令文本 + `petcore autostart on/off/status`。 |
| 多实例 | 完成：`--instance NAME` 独立数据根/lock；单进程多宠由 P2 补齐（slot 0 主宠 + slot 1–15）。 |
| 打包入口 | 完成：`packaging/petcore_entry.py` 与 `scripts/build_petcore.ps1`；P2 已在本项目内安装 PyInstaller/Inno 并实际构建。 |
| 首跑供给 | 完成包装：`media/provision.py` 复用 `pet.frameseq_provision`；实机把 shenshen 的 2 段转成 frameseq（其余 104 段仍 webm）。 |

## 10. H1-D 角色资源包导入（2026-10-20 完成）

- `pack-character <source> --out <dir>` 生成 `character.<id>` content mod；
- source = `manifest.json` + `videos/`（或媒体在根目录）；校验 body/head、媒体存在、id 合法；
- 复制/硬链接媒体与 `frameseq/`；安装复用 `petcore mods install`；
- 实机用合成包验证；**未做真实大素材导入**。

## 11. H2-A 交互、多宠与关于（2026-10-20 完成）

| 项 | 状态 |
|---|---|
| 关于并入设置 | 完成：删除独立窗口/菜单项；设置页含诊断、复制、项目主页。 |
| 单进程多宠 | 完成：slot 0 主宠 + slot 1–15；独立配置、恢复、收回、碰撞；`--check` 输出 active_pets。 |
| 点击 Q 弹 | 完成：220ms、底部居中、旋转/探头叠加、命中逆变换。 |
| 拖动物理/弹弓/黄金回旋/投喂/探头击飞 | 完成；默认拖动物理关，弹弓默认开。 |
| 菜单顺序 | 完成：主分支顺序 + 新架构项归位；`extensions_hub` 承接未排布 mod。 |
| 设置页 | 新增「互动与物理」「多宠」；所有 Core 菜单项有落点。 |
| 播放速率/动作等待间隔 | 完成。 |
| 本地打包 | 完成：PyInstaller 6.22.3 + Inno Setup 6.7.3；onedir 与安装包实际构建，`--check --out` 通过。 |

## 12. H2-B 内置 mod（离线域）

已落地内置 7 个：`fun.self-talk`、`fun.click-talk`、`tool.quick-launch`、`tool.quiet-mode`、`tool.links`、`tool.memory-trim`、`tool.network-info`。`fun.divination`、`fun.festival`、`reminder.todo`、`voice.chime`、`media.music` 已移到 `examples/petcore-mods/` 作为可导入样板（`petcore mods install` + `allow_feature_mods`）；安装后菜单默认进「扩展」，设置页进「扩展管理」页内标签。

下一批：P3 网络/worker 域（AI、识屏、账户、天气、Agent 联动）。**P6 修订**：账户与
API（配置/探测/凭据/额度）归 core（`petcore/net` + `petcore/api` + `petcore/account`），
AI/识屏/音乐/语音等**执行**仍走 worker 或 mod；P3 表里的「账户走 mod」不再成立。

## 13. H3 收口（2026-10-20）

| 项 | 状态 |
|---|---|
| 设置页聚合 | 完成：`SettingsTabContainer` + `ExtensionsPage`；侧边栏固定 7 页；「扩展管理」页内标签承载 ModsPage 与所有 mod 设置页。 |
| 可导入样板 | 完成：5 个 feature 包移到 `examples/petcore-mods/`；`petcore mods install` + `allow_feature_mods`；内置只留 7 个。 |
| 快捷启动位置 | 完成：`tool.quick-launch:open_menu` 移入「工具与帮助」。 |
| 移动朝向 | 完成：按移动方向设置 `state.facing`，首帧即正确镜像。 |
| 位移同步 | 完成：`move_curves` + `move_position_at_frame` 帧驱动；静态帧不位移，末拍到位。 |
| 文档/门禁 | 完成：L010–L012 已写；`591 passed, 5 skipped`；`ruff` 绿；`dist/` 已按 P3 代码重出 onedir 与 Inno 安装包。 |
| CLI 与扩展页兜底 | 完成：子命令前的 `--root/--portable/--instance` 生效；裸 `QWidget` 设置页可见并标注不参与保存。 |

## 14. H4 交互与安装器收口（2026-10-20）

| 项 | 状态 |
|---|---|
| 朝向镜像 | 完成：改用主分支口径——素材原生朝左，`facing == "right"` 才镜像；`PetState.facing` 默认 `left`。 |
| 黄金回旋接续 | 完成：`_begin_spin` 起表（此前角度冻结在 0°，点击动画结束后“没有回旋”）。 |
| 碰边反馈 | 完成：按「离地→接触」沿触发，每次落地/撞墙都 Q 弹 + 音效（此前整个抛掷只响一次）。 |
| 边缘探头 | 完成：贴边判定给 28px 余量并吸附压边，落地反弹停在边旁也能探头。 |
| 多宠穿模 | 完成：碰撞分离按身体框钳进屏幕；碰撞打断移动计划；拖拽中不与其它宠结算。 |
| 子宠落座 | 完成：`engine/spawn.py` 逐圈找空位并保证整只落在可用区内。 |
| 首次点击卡顿 | 完成：`SoundPlayer` 缓存 `QSoundEffect` 并预建；启动后预热全部点击 clip。 |
| 设置分页溢出 | 完成：标签条进横向滚动区，两侧翻页箭头，切页自动滚到可见。 |
| 设置搜索 | 完成：搜索口径包含页面内所有行文案，命中后自动切页 + 滚到该行。 |
| 黄金回旋子选项 | 完成：「点击时跳过点击动画」缩进为子项，仅在「点击触发黄金回旋」开启时显示。 |
| 安装器 | 完成：窗口化构建（无终端窗口）；5 个扩展改为安装向导可勾选，装到 `%APPDATA%\dsh-pet-core\mods\`，附 `.trusted` 授信标记。 |
| 已安装扩展展示 | 完成：「扩展管理」列表标出「随安装包」，选中显示类型/版本/位置/授权来源。 |


## 15. H5 交互易用性（2026-10-20）

| 项 | 状态 |
|---|---|
| 气泡贴合 | 完成：锚点改 `head_box`（回退 `body_box`），候选布局不压角色，gap 6px。 |
| 台词大框 | 完成：自言自语/点击台词改 `QPlainTextEdit`，一行一条，兼容旧 `a | b`。 |
| Enter 保存 | 完成：设置窗口 Enter = 保存退出，多行框内保持换行。 |
| 免打扰页 | 完成：默认档下拉 + 当前状态 + 恢复提醒 + 立即静默四档，附说明文案。 |
| 命令反馈 | 完成：`say/notify(force=True)` 绕过免打扰；网络信息/回收内存/免打扰都有气泡。 |
| 菜单对勾 | 完成：QSS 注入生成的 check 图片；勾选项不设 icon。 |
| 碰撞 | 完成：内切三圆链 + slop/60%/12px/连续 3 tick 强制分离，实际两只 shenshen 不互穿。 |

## 16. H6 动画节拍 + core 联网 / API（2026-10-20）

| 项 | 状态 |
|---|---|
| 待机掷骰 | 完成：IDEL 圈末不再 `advance()` 续播自身，改为 `_roll_next()`；`test_petcore_playback` 钉住。 |
| 动画间隔 | 完成：`animation_gap_seconds` 改成「间隙播待机、到点掷骰」，不再冻在末帧。 |
| 可调概率 | 完成：设置「互动与物理 → 自主行为概率」四项百分比，归一化后即时生效。 |
| 手动播放 | 完成：右键「播放动画」按待机/转向/移动/点击/随机/事件分组，播完回掷骰链。 |
| 事件动画 | 完成：`events/<group>/` → `GraphType.EVENT` + `event_group`；`play_event()` 按名字/索引；余额 6 个动画不再混入随机动作。 |
| core 联网 | 完成：`petcore/net/` 代理兜底 + 五类失败分类；守卫改 allowlist + mod 不得 import。 |
| core API | 完成：`contracts/api.py`、`petcore/api/`（规格/存储/钥匙串/探测）、`HostPorts.api`；设置页「API 与账户」+ 菜单入口。 |
| 账户/额度 | 未做：P8 落地（`petcore/account/`），API 已留 `balance_protocol` 与 `ApiRequest`。 |
| 打包 | 待重出：keyring 收集与 Windows 后端进构建脚本，需重建安装包实测。 |

**计划变更**：① API/账户从「mod/worker」改为 core 能力，执行仍在 worker/mod；
② keyring 从「明确不做」改为 core 凭据存储；③ 动画播放从「clip 循环」改为
「待机一圈 → 掷骰 + 可调权重」；④ `events/*` 从随机动作池独立；⑤ 侧边栏 7→8 页。

## 17. H7 探头/击飞与安装/扩展治理（2026-10-21）

| 项 | 状态 |
|---|---|
| 击飞旋转触发 | 完成：碰撞确认重叠后先 `arm_throw_egg()` 再退出探头；低速碰撞立即回正。 |
| 飞行接管态 | 完成：`motion.thrown` 不掷骰、不响应左键；落地 `stop()` 后才回行为链；进入抛掷即绑飞行/拖拽素材。 |
| 探头素材闸门 | 完成：`probe_active`/彩蛋激活时只允许 idle/转向，探头不翻朝向。 |
| 安装器图标 | 完成：`SetupIconFile=..\assets\icon.ico`、`UninstallDisplayIcon`；主 exe `--icon`。 |
| 随附扩展位置 | 完成：改到 `{app}\mods\<id>`，应用扫描安装目录；`.trusted` 仍逐包授权，随卸载删除。 |
| 扩展管理 | 完成：左侧竖向导航 + 基础/加装分组（独立滚动），ModsPage 同口径过滤；`name_zh` 中文名。 |
| 彩蛋图片 | 完成：菜单「彩蛋图片」随机弹内置鲸鱼娘图片；设置可换目录/标题/开关。 |
| 点击音效 | 完成：默认/小黄鸭/自定义文件/文件夹；duck mp3 已补 wav；碰撞/碰边复用。 |
| 打包 | 待重出：setup 图标与 `{app}\mods` 需 `-Clean -Installer` 重建验收。 |

**计划变更**：① 账户/额度从 P7 顺延到 P8；② 安装器的选装扩展从用户数据目录改到
安装目录（卸载随应用）；③ 扩展管理从横向页内标签改为竖向导航；④ 彩蛋/点击音效
回到 core（不再只是旧主分支的彩蛋入口）。

## 18. H8 多宠/气泡/设置重组与打包回归（2026-10-21）

| 项 | 状态 |
|---|---|
| 菜单模板缺失 | 完成：构建补 `--add-data petcore/menu_templates`；`load_default()` 内置兜底；`--check` 输出 `menu_template`；合并结果落盘。 |
| 多宠推动 | 完成：轻碰不取消移动计划、不切 `thrown`；计划平移继续走；拖拽仍排除。 |
| 探头优先 | 完成：轻碰时探头按无限质量；真撞击（≥300px/s）才退出并授权击飞旋转。 |
| 子宠退出 | 完成：右键「退出这只」只收回子宠。 |
| 气泡跟随/图片 | 完成：`reposition()` + `moveEvent` 跟随；`show_image()`；彩蛋默认气泡显示。 |
| 彩蛋菜单行 | 完成：头像 + 标题 + 「请点击」整行控件。 |
| 互动与物理分页 | 完成：8 个页内分页（点击/点击台词/自言自语/拖拽/碰撞/动画/彩蛋/免打扰）。 |
| 设置归位 | 完成：菜单页加快捷启动；关于页加链接/网络/回收内存；7 个内置特性并入 Core。 |
| 扩展管理 | 完成：组头可折叠；setup 5 个归「加装」；Core 特性不再出现在扩展导航。 |
| 安装向导路径 | 完成：`DisableDirPage=no` + `UsePreviousAppDir=yes` + 旧路径预选。 |
| 差距台账 | 完成：新增 [`PETCORE-MAIN-PARITY-BACKLOG.md`](PETCORE-MAIN-PARITY-BACKLOG.md)。 |
| 打包 | 待本轮重出：`-Clean -Installer` 后验证 `_internal/petcore/menu_templates/` 与 setup 目录页。 |

**计划变更**：① P8 原定“账户与额度”顺延到 P9 起点（本轮先修交互/设置/打包回归）；
② 7 个内置 feature 从“内置 mod”改为“Core 内置特性”，设置页内嵌而非扩展导航；
③ 差距不再散落在聊天里，统一维护在 parity backlog；④ 安装器新增“目录页必须显示”
硬规则，后续改 `petcore.iss` 先看 SPEC §4.27。

## 19. H8.1 观感/菜单/弹弓/直播兼容（2026-10-21）

| 项 | 状态 |
|---|---|
| 字号 | 完成：`ui_font_size`（10–18）同步设置页/菜单/彩蛋行；`bubble_text_scale`（50–300%）气泡。 |
| 彩蛋图片大小 | 完成：`easter_egg_image_scale`（50–300%）作用于弹窗与气泡内彩蛋图。 |
| 自言自语配图 | 完成：`self_talk_image_chance`（默认 30）、目录、图片大小；失败回退文字。 |
| 菜单顺序 | 完成：彩蛋第一、播放速率默认隐藏、尾部 modern_settings → separator → quit；旧布局幂等迁移。 |
| 播放动画预览 | 完成：分类子菜单懒加载 + 代表帧缩略图（2 线程、内存/磁盘缓存、可关）。 |
| 弹弓右键 | 完成：瞄准/发射后 0.35s 内不弹右键菜单。 |
| 点击台词启动生效 | 完成：监听补挂到新子宠；点击台词 `force=True`。 |
| 设置 X 保存 | 完成：X = 保存关闭；取消/Esc = 恢复快照。 |
| 直播捕获兼容 | 完成：`stream_capture_mode` 切普通顶层 Window（含气泡），多宠每窗可捕获。 |
| 打包 | 待本轮重出：`-Clean -Installer` 后验证 setup 与 `--check`。 |

## 20. P0–P6 主分支对齐计划（2026-10-22）

审查矩阵见 [`PETCORE-FUNCTION-MATRIX-2026-10-22.md`](PETCORE-FUNCTION-MATRIX-2026-10-22.md)，
可交接任务见 [`PETCORE-HANDOFF-PLAN-2026-10-22.md`](PETCORE-HANDOFF-PLAN-2026-10-22.md)。

| 阶段 | 目标 | 状态 | 用户可见效果 |
|---|---|---|---|
| P0 | 审查、矩阵、Core/mod/worker 边界与迁移契约冻结 | 已完成 | 行为不变，但每项差距都有唯一归属和验收 |
| P1 | 每宠/全局配置作用域、当前宠物上下文、v4/slot 基础迁移和回滚 | 已完成（基础） | 子宠设置不再改错主宠，旧配置和 slot 档案可安全迁移；会话/待办/API 文件留给对应业务阶段 |
| P2 | WorkerHost、完整 Graph、GUI 角色导入、5 个离线扩展可选安装 | 已完成（基础） | 待办/报时/节日/抽签/音乐需在安装向导勾选（默认不勾）；业务运行和媒体解耦仍待 P4/P5 |
| P3 | Core 账户/余额、AI 对话、识屏、截图提问、三个全局热键 | 已完成（基础） | 聊天窗口、截图提问与三条热键可用；OCR/翻译/主动识屏留给 P4 |
| P4 | Agent、TTS、音乐歌词、天气、文件识别和提醒业务域 | 计划 | 完成日常陪伴和开发工具联动能力 |
| P5 | 灵动岛、性能治理、更新、安装器 E2E 和系统生命周期 | 计划 | 更省资源，故障和升级可恢复 |
| P6 | 真双屏、混合 DPI、跨平台冒烟、发布入口切换和旧壳收敛 | 计划 | 新架构成为可回滚的正式发布入口 |

执行纪律：每阶段先写红测试，完成代码/验证/报告后更新四份必同步文档并创建一个
可运行的本地提交。播放速率 `0.5–2.0x`、VPet LPS/PNG 和首轮 16 宠上限是明确有意差异。

## 21. 插件市场 v1（2026-10-22）

静态索引 + artifact 多源 + 下载校验 + 安装/更新/回滚已落地，作为 Core 的
`petcore/market/` 与设置页「插件市场」；契约见 [`PETCORE-MARKET.md`](PETCORE-MARKET.md)。

| 项 | 状态 |
|---|---|
| 索引 | 完成：`index.json` schema 1、ETag/disk cache、官方 raw → GitHub Contents API 备用源、自定义镜像 |
| 下载 | 完成：多 URL 回退、`.part` Range 续传、size + SHA-256 |
| 安装 | 完成：staging → manifest 交叉校验 → 备份 → 原子替换 → `market-lock.json` |
| 更新/回滚 | 完成：版本比较、最近 2 份备份、回滚后反向备份 |
| UI | 完成：扩展管理左导航「插件市场」、搜索/分类/状态、离线过期提示 |
| CLI | 完成：`petcore market list/show/install/update/rollback/doctor` |
| 官方索引仓库 | 待创建：`MerZlin/dsh-pet-extensions`（本批只冻结契约与 schema） |
| 签名/CDN/npm | 明确不做：见 `PETCORE-MARKET.md` §8 与 §10 |
