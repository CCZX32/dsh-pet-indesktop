# DLC 线交接文档（给接手者与 AI 的完整工作包）

> 写作时点：2026-10-15，分支 `dlc/mod-center-port`（HEAD `07ec46e`）。
> 读者设定：**没接触过这个项目**的开发者 + 他的 AI 助手。读完这份文档 + 文内指路的两三份档案，应该能直接开工。
> 本线的**唯一真相源**是 [`docs/modding/PORT-STATUS.md`](modding/PORT-STATUS.md)（逐 phase 状态对照），本文是导航、理念与操作手册；两者冲突时以 PORT-STATUS 为准。

---

## 0. 一段话讲清这条线在干嘛

这是一个 PySide6 桌面宠物应用（`dsh-pet-indesktop`，Windows/macOS/Linux 三端）。
主线（`main`）是"功能全内置"的传统形态。**DLC 线的终态目标：纯净 Core——桌宠本体只留骨架，一切功能（AI 对话、识屏、语音等）都是可按需安装/停用/卸载的"功能扩展包"**。
上游作者在另一条分支上把这套设计写了出来并部分实现；本仓库的拓扑（overlay 单合成窗多宠、固定身份槽位 0..128、进程内碰撞世界）和上游不同，**不能合并，只能逐片移植**。本线已完成内核与两个官方包的落地，剩下的是"接线"与打包投递。

---

## 1. 理念与取向（先懂为什么，再动手）

这条线的每个"奇怪规矩"背后都有原因。理解它们比记住它们重要。

### 1.1 纯净 Core 与"一切都是包"

终态形态里，Core 只包含：窗口/渲染骨架、配置与档案系统、包信任链、安装事务、宿主运行时、事件总线。**连 AI 对话这种"看起来就是本体"的功能，终态也是一个包**（`features/ai-chat/` 已经是这个形态的试点——它与内置聊天并存，自带 provider/会话/窗口，各持各的账）。
动机：功能边界清晰 → 每个包独立演进/独立出事/独立卸载；Core 小 → 启动快、崩溃面小、审查面小。用户按需安装，不为自己不用的功能付内存和启动时间。

### 1.2 共存优先，不做替换

内置功能（`pet/chat/` 等）是现行权威，带着全部后续产品修复；包是它的可插拔形态。**移植 ≠ 替换**：整包化内置功能会把产品修复分叉成两份，所以本线明确"内置一个字节不动，包开自己的窗口用自己的配置"。等包的能力与内置完全对齐、且两位维护者拍板后，才有"瘦身"（内置退役）那一步——那是后期阶段，不是现在。

### 1.3 工程诚实：fail-closed 与不夸大

- 包安全模型是"显式用户信任 + 装前子进程预检"，**不是沙箱**。探针只在拒绝方向有权威；文档/UI 文案绝不声称"验签通过=安全"或"已隔离"（这是盲审 M3 修出来的口径，有机器守卫）。
- **没有"热插拔"这个词**。Python 模块热卸载不承诺（sys.modules/Qt 对象/线程引用无法严谨回收）；正确措辞是「可停用 / 可卸载 / 进程级卸载」。写文档和代码注释都按这个口径。
- 报告里"无法验证"要写明为什么不能自动验证，不许用沉默代替结论。

### 1.4 证据驱动

每个改动交付三份证据：逐文件修改说明（含 numstat）、实测性能数字（命令+环境+样本量）、实机运行记录。"可忽略/更快/优化了"这类形容词不算分析。这条由 `tests/test_pr_report_discipline.py` 机器校验，不是倡导。

### 1.5 边界管理

DLC 线与主线不交叉（定案）；什么时候交叉由两位维护者说了算。上游设计文档里的"已实现"是**上游分支自己的进度**，不是本仓库事实——对不上号就查 PORT-STATUS，别猜。

---

## 2. 硬边界（定案，不要翻案）

- DLC 线的一切留在 `dlc/mod-center-port` 分支，**不进 main、不开 PR**。
- 内置功能一个字节不动（见 §1.2）。
- 推分支前跑全量测试闸门（见 §3）；commit 勤推（工作盘有过掉盘前科）。
- LPAC 原生探针沙箱不移植（已拍板）；3A agent-link worker 不移植（主线 `pet/agent_link.py` 是权威）；Phase 6/7 不排。

---

## 3. 环境起步

```bash
git clone https://github.com/MerZlin/dsh-pet-indesktop.git
cd dsh-pet-indesktop
git checkout dlc/mod-center-port
python -m pip install -r requirements.txt   # Python 3.13（CI 构建机是 3.11，本机开发 3.13 验证过）
```

- 跑应用（源码态）：`python -m pet`
- 测试（一律这个形态）：`QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:randomly`
  - 聚焦族：上面命令 + `tests/test_xxx.py`
  - **全量闸门**：同命令不带文件名，本机约 20–70 分钟。**改共享模型/配置/生命周期/打包后必须跑全量**；只改局部表现层可以跑聚焦+相关族，但要在交付报告里写明为什么跳过全量。
- Lint：`python -m ruff check pet tests scripts`（push 前必过）
- Windows 上 Git Bash 跑 robocopy 要 `MSYS2_ARG_CONV_EXCL="*"`，否则 `/E` 被路径转换吃掉。

## 4. 架构地图（Core 现状）

```
pet/
├── overlay_window.py / overlay_shell.py   # overlay 单合成窗拓扑（默认）。所有 sprite 在一个透明全屏窗里
├── pet_sprite.py                          # sprite 本体（拖拽物理、动画状态机）
├── pet_profiles.py                        # slot 档案（config-slot-N.json，含 slot0）；每宠键的唯一真值
├── settings_slot_config.py                # 设置页读写路由 SlotRoutedConfig（main 刚修的 #271 在这条链上）
├── workers/                               # 子进程底座：pet-worker/v1 协议 + QProcess 监督 + 启动租约
├── plugins/                               # 包信任链（package_trust.py：验签/清单/指纹/路径边界）+ 宿主骨架
├── mod_api/                               # 包宿主 API（v1）
├── feature_*.py                           # 安装事务/状态账本/版本租约/装前预检/启动契约（Phase 4B 件）
├── feature_management.py                  # LocalFeatureRuntime——本地包的管理器（第三方包已可装卸）
├── feature_host_bindings.py               # 官方包的宿主绑定（bind_screen_context / bind_ai_context）
├── feature_ports.py / api_ports.py        # 端口面（DesktopQueryPort / CredentialVaultPort / FeatureUserDataPort）
├── mod_management.py / mod_catalog.py     # 角色资源 MOD（另一条腿，早已可用）
└── mod_center_controller.py / settings_mod_domain.py  # 设置页「扩展管理」域

features/
├── screen-understanding/   # 官方识屏包（host 15 + common 4 + worker 薄入口）
└── ai-chat/                # 官方 AI 对话包（host-only，30 文件）——与内置 pet/chat/ 并存，各持各的配置与会话账
```

**关键认知**：

- 官方包（`official.*` owner）走 Core 自有装配链（`attach_official` + 官方验签策略），第三方包（未知 owner）走「显式用户信任 + 装前子进程预检」链，默认 fail-closed。
- 包的身份 ID 是规范形 `[a-z0-9][a-z0-9_.-]*`（禁末尾 `.`/`-`、禁设备名首段），官方闭集按规范形比较——别造大写 ID。
- 冻结包子进程路由已修过（`packaging/pet_entry*.py` 分流 `--worker`/`--feature-package-probe`）；冻结版长路径用 `pet/frozen_runtime_paths.py`（`\\?\` 扩展拼写、就地替换 sys.path，追加无效是实测过的）。

## 5. 已完成清单（信任但要验证）

| 片 | 内容 | 证据 |
|---|---|---|
| S1/S2/S3/S4 | MOD 中心（角色资源全链路）、workers 底座、主动识屏 worker 试点、文档与示例 | `docs/PR-REPORT-DLC-MOD-CENTER-2026-10-13.md` |
| D2/D3 | 宿主运行时（mod_api/plugins 骨架）+ 第三方功能包 ZIP/目录导入全链路（装前子进程预检） | PORT-STATUS §六 |
| D4 | 分发/打包链最小子集：`scripts/verify_feature_package.py`（发布门）、`build_mod_example.py`（作者入口）、三端构建两道门 + `<app>/features/` | PORT-STATUS §七 |
| Phase 2 内核 | CoreEventBus + Registry/Context + owner 作用域事件订阅面 | `03ad5c6`/`2cfb6a7`/`f50d80c` |
| 4A 两端口 | `pet/desktop_query.py`、`pet/credentials.py`（凭据库） | `e3295fa`/`6586cf0` |
| 识屏官方整包 | `features/screen-understanding/` + 宿主注入 + 独立视觉配置 + 识屏→聊天联动 | PORT-STATUS §二 Phase 4A 格 |
| AI 对话官方整包 | `features/ai-chat/` + `bind_ai_context` + 呈现面 `pet/ai_bindings.py` + 装卸 e2e + 退出闸门退订收口 | PORT-STATUS §九 |
| 盲审修复批 | B1/M1–M4/m3/m5/n1/n2 + N1/N2/N3（冻结入口分流、ID 规范形、两段式失败装回、重试阶梯、退出补拉等） | PORT-STATUS §八 |

当前分支状态：全量套件绿（唯一例外是 `test_workers_lifecycle.py` 三条负载 flake——基线上也红，单跑全绿，已登记 BACKLOG，别去"修"它们除非你打算把族隔离出主套件）。

## 6. 后续工作（接线清单，按建议顺序）

每条标了入口、依赖与验收。**拿不准的终态问题先问维护者，别自己拍。**

### 6.1 包内 AI 聊天窗与内置 UI 对齐（需要产品决策，先问维护者）

- **现状**：`features/ai-chat/host/chat/widgets.py` 是内置聊天**较早时间点的分叉**（2219 行 vs 内置 2532 行），缺 markdown 渲染、思考链、#191 布局修复、联网检索。
- **要做**：两个候选方向——(a) 把内置 UI 的后续修复逐片同步进包；(b) 让包复用内置实现（反过来收敛）。两者都触碰"共存 vs 替换"的终态路线（§1.2），**开工前必须和维护者对齐**。
- 入口：`features/ai-chat/host/chat/` vs `pet/chat/`。
- 验收：机器判据 `test_the_package_never_touches_the_builtin_chat_configuration` 不许破；包窗功能清单与内置对齐到逐项可核对。

### 6.2 小包接线三件（同源后续片，可一起做，建议作为上手第一批）

1. **`notifier` / `auth_callback` 接线**：`AiRuntime.create_window` 这两个参数现在传 None（效果是"未配 Key 时不能一键跳 API 设置页"）。上游参照：`bind_ai_window`。验收：包窗未配 Key 时出现跳转入口且真能跳到设置页。
2. **文件解读投喂**：Core 侧拖文件 → 包的 `FileInterpretController`（包侧件都在，差 Core 投喂接线；上游参照 `bind_ai_window` 的 `file_factory` + `install_file_interpreter`）。验收：真拖一个文件到包窗/桌面，走包的解读器出结果。
3. **MOD 中心 UI「安装官方包」按钮**：当前官方包由 Core 入口 `attach_official` + 管理器驱动，UI 入口未做；识屏包同状态。验收：设置页「扩展管理」能装官方包且状态可视。

### 6.3 4B-5 冻结构建（打包/构建片的前半）

- host-only 包的**冻结 exe 真实构建**（`build_mod_echo` / `build_feature_probe_native` 形态）+ host-worker 真实冻结。
- 产品侧读 `<app>/features/` 旁置包根的那条链（D4 已让构建脚本能携带包根，运行期还没人读）。
- 验收：真冻结产物上跑通"安装→装载→启停→卸载"，而不是只在源码解释器下绿（N6 登记的缺口）；三端构建脚本的两道门保持绿。
- 注意：Windows 安装包 GUI 实测（装/卸/升级）属于这片的人工验收部分。

### 6.4 5A Setup 适配（打包/构建片的后半）

- Setup 选装器（官方 ZIP 编译期嵌入、勾选安装、首启 startup receipt）、显式便携模式。
- 入口：`packaging/dsh-pet.iss`（本站 Inno Setup）、上游参照 `docs/plugin-phase-05-distribution/`。
- **注意**：官方包嵌入 Setup 与便携模式在 PORT-STATUS §七 的当前判定是"不做"——开工前重新跟维护者确认是否翻案。

### 6.5 不排期/不做（别捡起来）

- LPAC 沙箱（不移植）、3A agent-link worker（不移植）、Phase 6 社区生态（条件阶段）、Phase 7 发布门（没有可验收对象）。
- 盲审缓做项 m1/m2/m4/N4/N5/N6：理由与归属都在 PORT-STATUS §八，想动先读那里的归属片。

## 7. 工程纪律（这个仓库的机器校验会卡你）

1. **test-first**：修 bug/改行为先写会红的测试，再改产品码让它绿；聚焦族按符号 grep 选（不许手挑文件名凑数）。
2. **三份交付证据**（见 §1.4）。落 `docs/PR-REPORT-<主题>-<日期>.md` 并登记 `docs/INDEX.md`。
3. **新文档必须登记 `docs/INDEX.md`**（一条一句话+何时必读）。
4. **CI 成本纪律**：push 前本地三门——ruff、全量 pytest、涉时序测试族的高负载复跑。CI 红了先读日志再动手；同一族连红两轮就停下来隔离，别赌。
5. **flake 定性规矩**：隔离复跑能过的不算缺陷（已登记：workers_lifecycle 三条、island_extension_chain 一条、test_product_copy 一条）。
6. **提交**：小而频繁，commit message 用仓库既有中文 conventional 风格（看 `git log` 学）；本线只推分支，不开 PR。
7. **AGENTS.md 必读**（仓库根）：架构拓扑、槽位语义、配置纪律（`docs/SETTINGS-CHANGE-GATES.md`——动持久设置前先读）都在里面。

## 8. 已知坑（前人踩过，别重蹈）

- **Windows 访问违规组合**：`tests/test_proactive.py` + `test_proactive_worker*.py` 三文件同跑曾触发段错误（时序相关，曾自愈）。遇上先按 PORT-STATUS §八末节的登记核对，别当自己改坏的。
- **机器过载时全量套件会出现大面积子进程创建失败**（0xC0000142）：那是环境事件不是代码塌方——2026-10-15 一度误判成"153 条塌方"。判断法：失败全部落在要起子进程的族 + 退出码 3221225794。
- **D 盘工作区有掉盘前科**：重要进展即 commit+push。
- **git push 报 failed 先 `git ls-remote` 核实**：这条线多次出现"报错但实际推上去了"。
- **上游文档里的"已实现"是上游分支的进度**，不是本仓库事实；对不上号就查 PORT-STATUS。

## 9. 上手第一周的建议路径

1. 读 `AGENTS.md`（根）+ `docs/modding/README.md` + 本文档。
2. 跑全量套件一次，拿到本机基线（顺便熟悉 20–70 分钟的节奏）。
3. 读 PORT-STATUS 全文（418 行，信息密度极高，是这条线的"宪法"）。
4. 挑 6.2 里最小的一件（比如 notifier 接线）走完整流程：test-first → 聚焦族 → 三份证据 → INDEX 登记 → 推分支。
5. 拿不准的终态问题（包 UI 对齐方向、5A 翻案与否）**问维护者**，别自己拍。

---

导航：[PORT-STATUS（真相源）](modding/PORT-STATUS.md) · [MOD 文档入口](modding/README.md) ·
[移植交付证据](PR-REPORT-DLC-MOD-CENTER-2026-10-13.md) · [全文档索引](INDEX.md)
