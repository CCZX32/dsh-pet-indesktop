# DLC 线交接文档（给接手者与 AI 的完整工作包）

> 写作时点：2026-10-15，分支 `dlc/mod-center-port`（HEAD `8f022ff`）。
> 读者设定：**没接触过这个项目**的开发者 + 他的 AI 助手。读完这份文档 + 文内指路的两三份档案，应该能直接开工。
> 本线的**唯一真相源**是 [`docs/modding/PORT-STATUS.md`](modding/PORT-STATUS.md)（逐 phase 状态对照），本文是它的导航与操作手册；两者冲突时以 PORT-STATUS 为准。

---

## 0. 一段话讲清这条线在干嘛

这是一个 PySide6 桌面宠物应用（`dsh-pet-indesktop`，Windows/macOS/Linux 三端）。
主线（`main`）是"功能全内置"的传统形态。**DLC 线的终态目标：纯净 Core——桌宠本体只留骨架，一切功能（AI 对话、识屏、语音等）都是可按需安装/停用/卸载的"功能扩展包"**。
上游作者在另一条分支上把这套设计写了出来并部分实现；本仓库的拓扑（overlay 单合成窗多宠、固定身份槽位 0..128、进程内碰撞世界）和上游不同，**不能合并，只能逐片移植**。本线已完成内核与两个官方包的落地，剩下的是"接线"与打包投递。

**硬边界（定案，不要翻案）**：

- DLC 线的一切留在 `dlc/mod-center-port` 分支，**不进 main、不开 PR**；什么时候交叉由两位维护者说了算。
- 内置功能（`pet/chat/` 等）**一个字节都不动**——包是共存的可插拔形态，不是替换。内置聊天是现行权威，带着全部后续产品修复。
- 推分支前跑全量测试闸门（见 §2）；commit 勤推（工作盘有过掉盘前科）。

---

## 1. 环境起步

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

## 2. 架构地图（Core 现状）

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
- **没有"热插拔"**。正确措辞是「可停用 / 可卸载 / 进程级卸载」；Python 模块热卸载不承诺（论证见 `docs/plugin-roadmap/PLUGIN-DLC-OPENING-ORDER-AND-THIRD-PARTY-INTERFACES.md` §8）。文档和 UI 文案都遵守这个措辞。
- LPAC 原生探针沙箱**不移植**（已拍板）；预检探针只在拒绝方向有权威，文档不得声称隔离/验签认证。

## 3. 已完成清单（信任但要验证）

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

## 4. 剩余工作（接线清单，建议按此顺序）

每条都标了入口与验收。详情一律去 PORT-STATUS 对应格子核对（它写"未做"的别假设已做）。

### 4.1 包内 AI 聊天窗与内置 UI 对齐（需要产品决策，先问维护者）

- **现状**：`features/ai-chat/host/chat/widgets.py` 是内置聊天**较早时间点的分叉**（2219 行 vs 内置 2532 行），缺 markdown 渲染、思考链、#191 布局修复、联网检索。
- **要做**：把内置 UI 的后续修复带进包（分叉同步），或反过来让包复用内置实现——**两个方向都涉及"共存 vs 替换"的终态决策，开工前先和维护者对齐**。
- 入口：`features/ai-chat/host/chat/` vs `pet/chat/`；机器判据 `test_the_package_never_touches_the_builtin_chat_configuration` 不许破。

### 4.2 小包接线三件（同源后续片，可一起做）

- `AiRuntime.create_window` 的 `notifier` / `auth_callback`（现传 None，效果是"未配 Key 不能一键跳 API 设置页"）——上游参照：`bind_ai_window`。
- 文件解读投喂：Core 侧拖文件 → 包的 `FileInterpretController`（包侧件都在，差 Core 投喂接线）。
- MOD 中心 UI「安装官方包」按钮：当前官方包由 Core 入口 + 管理器驱动，UI 入口未做；识屏包同状态。

### 4.3 4B-5 冻结构建（打包/构建片的前半）

- host-only 包的**冻结 exe 真实构建**（`build_mod_echo` / `build_feature_probe_native` 形态）+ host-worker 真实冻结。
- 产品侧读 `<app>/features/` 旁置包根的那条链（D4 已让构建脚本能携带包根，运行期还没人读）。
- 前置认知：冻结包的子进程路由已经修过（`packaging/pet_entry*.py` 分流 `--worker`/`--feature-package-probe`，见 PORT-STATUS §八 B1）；冻结版长路径用 `pet/frozen_runtime_paths.py`（`\\?\` 扩展拼写、就地替换 sys.path）。
- 验收：真冻结产物上跑通"安装→装载→启停→卸载"，而不是只在源码解释器下绿（N6 登记的缺口）。

### 4.4 5A Setup 适配（打包/构建片的后半）

- Setup 选装器（官方 ZIP 编译期嵌入、勾选安装、首启 startup receipt）、显式便携模式。
- 注意 PORT-STATUS §七 的已拍板取舍：官方包嵌入 Setup 与便携模式**当前判定为不做**——开工前重新跟维护者确认这条是否翻案。
- 入口：`packaging/dsh-pet.iss`（本站 Inno Setup）、上游参照 `docs/plugin-phase-05-distribution/`。

### 4.5 不排期/不做（别捡起来）

- LPAC 沙箱（不移植）、3A agent-link worker（不移植，主线 agent_link 是权威）、Phase 6 社区生态（条件阶段）、Phase 7 发布门（没有可验收对象）。
- 盲审缓做项 m1/m2/m4/N4/N5/N6：理由与归属都在 PORT-STATUS §八，想动先读那里的归属片。

## 5. 工程纪律（这个仓库的机器校验会卡你）

1. **test-first**：修 bug/改行为先写会红的测试，再改产品码让它绿；聚焦族按符号 grep 选（不许手挑文件名凑数）。
2. **三份交付证据**（行为变更必须，纯文档可豁免但要写理由）：逐文件修改说明（含 `git diff --numstat`）、实测性能数字（命令+环境+样本量，形容词不算数）、实机运行记录。落 `docs/PR-REPORT-<主题>-<日期>.md` 并登记 `docs/INDEX.md`——`tests/test_pr_report_discipline.py` 机器校验四节齐全。
3. **新文档必须登记 `docs/INDEX.md`**（一条一句话+何时必读）。
4. **CI 成本纪律**：push 前本地三门——ruff、全量 pytest、涉时序测试族的高负载复跑。CI 红了先读日志再动手；同一族连红两轮就停下来隔离，别赌。
5. **flake 定性规矩**：隔离复跑能过的不算缺陷（已登记的 flake 族：workers_lifecycle 三条、island_extension_chain 一条、test_product_copy…一条）。
6. **提交**：小而频繁，commit message 用仓库既有中文 conventional 风格（看 `git log` 学）；本线只推分支，不开 PR。
7. **AGENTS.md 必读**（仓库根）：架构拓扑、槽位语义、配置纪律（`docs/SETTINGS-CHANGE-GATES.md`——动持久设置前先读）都在里面。

## 6. 已知坑（前人踩过，别重蹈）

- **Windows 访问违规组合**：`tests/test_proactive.py` + `test_proactive_worker*.py` 三文件同跑曾触发段错误（时序相关，曾自愈）。遇上先按 PORT-STATUS §八末节的登记核对，别当自己改坏的。
- **机器过载时全量套件会出现大面积子进程创建失败**（0xC0000142）：那是环境事件不是代码塌方——2026-10-15 一度误判成"153 条塌方"。判断法：失败全部落在要起子进程的族 + 退出码 3221225794。
- **D 盘工作区有掉盘前科**：重要进展即 commit+push。
- **git push 报 failed 先 `git ls-remote` 核实**：这条线多次出现"报错但实际推上去了"。
- **上游文档里的"已实现"是上游分支的进度**，不是本仓库事实；对不上号就查 PORT-STATUS。

## 7. 上手第一周的建议路径

1. 读 `AGENTS.md`（根）+ `docs/modding/README.md` + 本文档。
2. 跑全量套件一次，拿到本机基线（顺便熟悉 20–70 分钟的节奏）。
3. 读 PORT-STATUS 全文（418 行，信息密度极高，是这条线的"宪法"）。
4. 挑 4.2 里最小的一件（比如 notifier 接线）走完整流程：test-first → 聚焦族 → 三份证据 → INDEX 登记 → 推分支。
5. 拿不准的终态问题（包 UI 对齐方向、5A 翻案与否）**问维护者**，别自己拍。

---

导航：[PORT-STATUS（真相源）](modding/PORT-STATUS.md) · [MOD 文档入口](modding/README.md) ·
[移植交付证据](PR-REPORT-DLC-MOD-CENTER-2026-10-13.md) · [全文档索引](INDEX.md)
