# petcore 已有能力质量审查（2026-10-24）

> 本轮基线 `729441603525f652b731268dbf0f39ff59effff4`，工作分支 `feat/petcore-vpet-architecture`。
> **结论：已确认 petcore 行为缺陷已修复，选定门禁与源码单屏场景通过；整仓门禁仍未通过，质量计划尚未全部闭环。**
> 未新增功能、未启动 P4-c3、未提交/推送/发布、未覆盖已安装版本，未改真实用户配置或系统安全策略。

## 1. 审查结论与阶段状态

本轮按生命周期/数据风险优先，先红后绿，未降低 Python 最低版本、降级 Qt、引入全局 Qt 补丁或改功能默认开关。
范围为 petcore、10 个示例 mod、7 个 Core 特性及相关测试/构建入口；旧 pet 只读实际适配链与必要对照，未修改旧产品代码。
“审查未发现新的可复现阻断”不是“代码没有任何问题”，本报告也不是安全认证。

| 能力 | 已实现 | 本轮自动化 | 本轮实机 | 尚未实现/验收 |
|---|---|---|---|---|
| 核心、多宠、菜单、设置 | 是 | 选定门禁通过 | Windows 单屏源码通过 | 双屏/混合DPI、非Windows |
| 安装/更新/回滚 | 是 | Python3.11 回归通过；3.12 仅标准库冒烟 | 隔离 scratch 目录文件操作 | 安装包 E2E，非Windows只读文件语义 |
| AI/语音/音乐/天气/文件/OCR | 已有实现 | 端口/生命周期回归通过 | 不调用真实账号、声卡或远端服务 | 真实服务/播放器/TTS/OCR 引擎端到端 |
| P4-c2 Agent | **只读联动已实现** | JSONL/状态/停止重启通过 | 未连接真实 Agent 写方 | 写端安装/hooks/直读适配器等 |
| P5-a1 灵动岛 | 胶囊/指标/展开卡片已实现，默认关 | 折叠/隐藏/停用与重启通过 | 真 psutil 读数、展开/隐藏通过 | 第二阶段、混合DPI等 |
| 提醒/节日/抽签 | 清单 CRUD / 8 个公历日期查询 / 6 条每日签文 | 现有样板测试 | 未做定时提醒实机，因为尚无实现 | 到期/提前/重复调度、农历、48签 |
| 整仓质量/分发 | 未完成 | **整仓失败与原生崩溃未关闭** | 只有源码运行，不是安装包 | 不进入分发准备或新功能 |

阶段文档已校正：ROADMAP §20/§25/§27/§28，SPEC 提醒域边界，parity/animation backlog，两个 README。
设置窗口契约保持 **标题栏 X 保存；取消按钮/Esc 恢复快照**，只纠正 AGENTS 的过时表述。
两份历史报告保留原始记录，追加“选定 petcore 测试不等于仓库全量”说明。
日志见 [L054–L056 索引](PETCORE-LOG-INDEX.md)，断点见 `.scratch/petcore-quality-review/HANDOFF.md`。

### 1.1 已关闭的确认缺陷

1. `rmtree(onexc=...)` 不兼容 Python3.11：按解释器版本选择 `onerror/onexc`；只对 PermissionError 加写权限重试，重试失败保留异常；不吞失败、不毁原安装/回滚备份。已提交替换后的旧目录清理失败明确返回警告与残留路径。
2. Qt 6.11.1 子菜单 C++ 对象提前释放：统一显式 `QMenu(title,parent)` 再加入；动态动画/扩展/托盘均覆盖。托盘刷新先收集旧子菜单，clear 后定向 deleteLater，防累计子对象。
3. system/network `stop()` 等约2秒后丢失活线程：共享 stdlib `SamplingLoop`，短锁保护发布，停止不 join；旧线程仍活不替换；每代独立 Event；晚结果丢弃；恢复重置 CPU/网络基线。调用方下一 tick 重试启动，不增常驻重启线程。
4. 灵动岛折叠与采样脱节：以布局、可见性、clock、设置统一协调；展开、收起、隐藏、禁用后更新意图。保持模板宽度/默认开关/功能边界。
5. Agent 阻塞读取/停用回调：保留旧线程、独立取消、世代检查；有界 scheduler 重启检查；关闭后不再复活。
6. HTTP 正常/读失败/deadline 路径与重试 HTTPError 未确定关闭：finally close；交还调用方的原始异常所有权不改变。
7. Speech 错误/异常回调在 worker 触碰 Qt：与成功路径一样经 scheduler；scheduler 失败丢弃并停止 token，不退回 worker 执行 UI。
8. 天气/文件停用仍发布、线程列表增长：世代/启用检查、清理完成线程；文件取消请求与进度 handle；旧阻塞线程退出前拒绝新任务。
9. 音乐阻塞 SMTC 的停止/恢复及迟到歌词：保留旧 worker 引用与独立 Events；新轮由 tick 恢复；旧采样/歌词不跨代，不在 GUI fallback 阻塞读取。
10. AI 旧请求误清新请求取消句柄及迟到 token：按 cancel 对象身份在 GUI 发布；vision 请求持有取消信号，stop 取消；scheduler 失败不执行 worker UI。
11. 主动识屏旧完成/错误清除新 busy：每次请求及超时推进 generation，先判身份后清状态。
12. Windows 64位会话 MSG 读取错位：真实 `ctypes.wintypes.MSG.message` 取代固定32位数组索引；不触发真实关机/注销。
13. 整仓揭示菜单像素测试只适用于亮色：暗色探针先失败，再显式测亮/暗两主题对比度；**只修测试隔离，未改产品外观/放宽到不检查对勾**。

## 2. 逐域审查留痕

下表的“测试”均为实际执行的族或重点日志，不代表所有外部场景已验证。入口至停止/释放链已阅读；无明确收益的路径不做纯重构。

| 域/入口 | 数据流与生命周期审查 | 测试与结论 | 未覆盖 |
|---|---|---|---|
| CoreHost (`petcore/ui/app.py`) | run→配置/窗口/服务→quit/finish；Qt 归属、关闭顺序 | app/feature/scheduler/worker 系列；native-current 退出只余 MainThread | 真实注销/关机不触发 |
| 配置/多宠 (`config.py`, `ui/pet_manager.py`) | ScopedConfig 全局与单宠、snapshot/restore、临时文件替换、spawn/close/shutdown | config_scope/settings_close/multipet 系列；原生双宠比例 .85/.5 隔离 | 无真实双屏迁移 |
| 动画/位置 (`engine/*`, `media/library.py`, `ui/pet_window.py`) | 逻辑运动、body_box 钳制、动作取消、媒体库缓存释放；旧 pet 只经 media/content 适配 | animation/motion/edge/geometry/collision/media 系列 | 本轮不重编码素材；旧 v4 Pillow 分支失败另记 |
| mod (`mods/feature.py`, loader/manifest/trust, platform/worker.py) | 清单→授权→贡献→start/stop_owner；路径边界、host-only 信任；worker 终止/管道关闭 | feature/architecture/worker 系列；不新增权限 | host-only 不是恶意 Python 沙箱；未做全面安全扫描 |
| 安装/市场 (`mods/install.py`, market/install.py) | zip/目录→staging→替换/备份→失败恢复；manifest 归属与未知文件保留 | install/market_*；修 Python3.11 onerror 与清理失败报告，35 passed | 不做真实安装覆盖；压缩炸弹预算未专项评估 |
| HTTP/API/账号 (`net/http.py`, errors.py, api/chat.py, credentials.py, account/service.py) | 单 deadline/代理/重试/取消→有界读取→close；keyring/内存兜底，repr 隐藏 key | http_port/net/api/account；修响应和 HTTPError close，151 passed | 无真实密钥/余额/远端服务验证 |
| AI (`ai.chat/host/runtime.py`, proactive.py) | 请求 cancel 身份→GUI scheduler→token/final；停止与 supersede、vision、看屏超时 | ai_mod/proactive/chat/quick_chat；修旧结果串线、取消丢失、旧 busy 清除 | 网络取消合作式，不能强杀阻塞 socket；真实模型未验 |
| Agent (`ai.agent/host/runtime.py`, tailer.py) | 只读 JSONL→汇聚→GUI；停用、排队回调、100ms 有界重启检查 | agent_mod；generation/独立 Event/保留线程，79 passed | 无真实外部 Agent 写入端；不装 hooks |
| 语音 (`ui/ports.py`, speech/*, voice.chime) | 合成工作线程→scheduler→Qt 播放；token取消、异常回传 | speech/voice/scheduler；修错误路径线程归属，66 passed | 不调用真实声卡/TTS账号 |
| 音乐 (`media.music/host/runtime.py`) | SMTC/歌词工作线程→GUI；停用→旧线程退出→下一 tick 恢复 | music_mod；迟到 lyrics/SMTC 和 blocked restart，37 passed | 无真实播放器播放/歌词远端端到端 |
| 天气 (`tool.weather/host/runtime.py`) | 单 worker HTTP→GUI；stop generation；完成线程剪枝 | weather_mod；30轮线程引用有界，迟到结果丢弃 | 请求超时前可能仍占单一取消线程 |
| 文件 (`tool.file-reader/host/runtime.py`) | 只读文件→API(cancel)→GUI；进度 handle/线程列表回收 | file_reader_mod；停止取消/无迟到 chat 和气泡、30轮引用有界 | 不读用户真实文件，不改数据 |
| OCR (`tool.ocr/host/runtime.py`, engine.py) | action register(priority10)→本地识别→失败交 AI；stop unsubscribe | ocr_mod/screen 系列；无明确复现需改动 | 本机 rapidocr 不可导入；没有真实 OCR 引擎证据 |
| 提醒/节日/抽签 (`*/host/factory.py`) | todo 配置清单→非模态列表；festival8项日期查询；divination6项 daily.json | example_mods；纠正文档，不增加调度/农历/48签 | 未做文件损坏/断电专项演练；并非完整提醒能力 |
| Core7个特性 (`builtin/features/*/host/factory.py`) | click-talk 订阅撤销；self-talk 按slot handle取消；quiet deadline；links/quick-launch显式命令；network-info按需；memory-trim句柄finally关闭 | builtin_mods/feature_command_slot；未新增后台循环 | 不实际启动用户程序/浏览器/回收外部进程内存；跨平台系统调用未验 |
| 菜单/设置/气泡 (`ui/menu*`, app.py, settings/*, bubble.py) | QMenu显式父子→动作→定向销毁；托盘刷新释放旧菜单；预览快照 | menu/tray/P5/settings系列；新增GC/30轮/亮暗主题；原生保存与取消 | 非Windows/混合DPI未验；本轮无重排/重绘功能 |
| 灵动岛/平台 (`ui/island.py`, platform/*mon.py, sampling.py, session.py) | 布局折叠结果→visible/clock/settings采样意图；旧读数屏蔽/重置；MSG真实ABI | island/monitor_lifecycle/session；350项压力族三轮；MSG相关59pass1skip | 永久阻塞OS读取只能保留取消daemon直到OS返回；无强杀 |
| 构建/入口 (`__main__.py`, cli.py, scripts/build_petcore.ps1) | 源码启动与可选mods/资源收集、依赖声明；旧媒体适配无架构逆依赖 | architecture/ci_workflows/PR gates；原生源码 exit0 | .venv不存在，rapidocr缺失；未build/安装/签名，不修改系统安全策略 |

## 3. 修改文件说明

下表相对本轮 HEAD，已跟踪文件由 `git diff --numstat` 生成；新文件按实际行数计 `+N/-0`。
未删除产品文件；`.scratch/` 探针/截图/日志均为本地证据，不混入产品包。统计包含本报告本身，不包含生成缓存/测试临时目录。

| 文件 | 类型 | 增/删行 | 改动与理由 |
|---|---|---|---|
| `docs/INDEX.md` | 修改 | +3 / -1 | 登记本报告并校正示例 mod 数量，保证新文档可发现。 |
| `docs/PETCORE-ANIMATION-BACKLOG.md` | 修改 | +3 / -3 | 区分已实现 Agent/岛一期与未实现提醒/岛后续，避免待办状态误读。 |
| `docs/PETCORE-LOG-INDEX.md` | 修改 | +4 / -0 | 登记 L054–L056 三批变更和证据入口。 |
| `docs/PETCORE-LOG.md` | 修改 | +85 / -0 | 追加三批根因、文件统计、红绿证据和未闭环限制，保留历史。 |
| `docs/PETCORE-MAIN-PARITY-BACKLOG.md` | 修改 | +4 / -2 | 校正音乐/Agent实现状态，明确写端和提醒调度缺口。 |
| `docs/PETCORE-ROADMAP.md` | 修改 | +18 / -10 | 更新 P4-c2/P5-a1 与提醒域实际状态；保留 P4-c3未开始；纠正选定测试口径。 |
| `docs/PETCORE-SPEC.md` | 修改 | +9 / -1 | 明确现有提醒只是CRUD/公历查询/6签，链接本轮验证边界。 |
| `docs/PR-REPORT-PETCORE-ISLAND-2026-10-23.md` | 修改 | +8 / -0 | 仅追加历史测试范围纠正与本报告链接，不篡改原始记录。 |
| `docs/PR-REPORT-PETCORE-P4C2-2026-10-23.md` | 修改 | +8 / -0 | 仅追加历史测试范围纠正与本报告链接，不篡改原始记录。 |
| `docs/PR-REPORT-PETCORE-QUALITY-REVIEW-2026-10-24.md` | 新增 | +319 / -0 | 新增五域审查、逐文件统计、真实测试/性能/实机证据与未闭环清单。 |
| `examples/petcore-mods/README.md` | 修改 | +9 / -4 | 示例数改为10并补OCR；纠正提醒/节日/签文的能力高估。 |
| `examples/petcore-mods/ai.agent/host/runtime.py` | 修改 | +55 / -22 | 停止立即返回且保留阻塞线程；独立Event与世代过滤；有界调度重启且close后不复活。 |
| `examples/petcore-mods/ai.chat/host/proactive.py` | 修改 | +4 / -2 | 请求/超时推进世代；先验证身份再清busy，防旧回调覆盖新状态。 |
| `examples/petcore-mods/ai.chat/host/runtime.py` | 修改 | +67 / -38 | 按cancel身份发布流式回调；vision保留/传递取消信号；失败调度不回退worker UI。 |
| `examples/petcore-mods/media.music/host/runtime.py` | 修改 | +41 / -20 | SMTC停用不等待、不丢旧线程；tick安全恢复，过滤旧歌词/采样并避免GUI阻塞读取。 |
| `examples/petcore-mods/tool.file-reader/host/runtime.py` | 修改 | +36 / -7 | 请求持有取消令牌，停止取消进度/结果；剪枝完成线程，防旧读者重叠。 |
| `examples/petcore-mods/tool.weather/host/runtime.py` | 修改 | +25 / -9 | 世代与启用状态过滤迟到结果，剪枝完成线程，阻止旧任务未退时重复启动。 |
| `petcore/AGENTS.md` | 修改 | +1 / -1 | 纠正设置关闭契约：X保存，取消/Esc恢复；不改实际交互。 |
| `petcore/README.md` | 修改 | +10 / -1 | 校正工作区示例并链接质量报告，明确已实现与未验收，不以虚构venv当验证。 |
| `petcore/mods/install.py` | 修改 | +27 / -14 | 兼容3.11 onerror；只对权限失败安全重试并传播错误；残留清理失败可诊断且不回滚已提交替换。 |
| `petcore/net/errors.py` | 修改 | +19 / -12 | 重试/归一化HTTPError后确保关闭持有的响应，不改变交还调用方异常所有权。 |
| `petcore/net/http.py` | 修改 | +11 / -9 | 正常、读取异常和deadline超时均finally关闭响应，避免资源泄漏。 |
| `petcore/platform/netmon.py` | 修改 | +28 / -33 | 使用共享采样生命周期，重启重置网络差值基线，暴露非GUI有界等待。 |
| `petcore/platform/sampling.py` | 新增 | +135 / -0 | 新增stdlib单worker生命周期实现：独立取消、保留活线程、世代发布、调用方驱动安全重启。 |
| `petcore/platform/session.py` | 修改 | +6 / -3 | 按wintypes.MSG真实ABI读取message，避免64位HWND高位被误读。 |
| `petcore/platform/sysmon.py` | 修改 | +25 / -32 | 使用共享采样生命周期，重启重置CPU基线，停止不再等待阻塞OS读。 |
| `petcore/ui/app.py` | 修改 | +8 / -2 | 托盘显式父菜单并在刷新后定向释放旧子菜单，保持动作语义。 |
| `petcore/ui/island.py` | 修改 | +7 / -3 | 布局折叠/可见/clock/设置统一决定采样需求，展开/收起/隐藏及时协调。 |
| `petcore/ui/menu_actions.py` | 修改 | +3 / -3 | 动画/扩展动态子菜单复用显式父对象构造，避免GC后对象失效。 |
| `petcore/ui/menu_model.py` | 修改 | +11 / -4 | 集中add_submenu显式QMenu父子所有权，应用普通和嵌套菜单。 |
| `petcore/ui/ports.py` | 修改 | +7 / -6 | Speech错误/异常与成功一样走GUI scheduler；失败时丢弃并停止token。 |
| `tests/test_petcore_agent_mod.py` | 修改 | +101 / -0 | 补阻塞停止/快速重启/独立取消/迟到回调/close后不复活回归。 |
| `tests/test_petcore_ai_mod.py` | 修改 | +120 / -0 | 补旧完成不删新请求取消句柄、旧token丢弃及vision停止取消回归，使用真实Qt调度。 |
| `tests/test_petcore_file_reader_mod.py` | 修改 | +84 / -0 | 补停用后不发布、取消/进度回收、30轮线程列表有界回归。 |
| `tests/test_petcore_http_port.py` | 修改 | +21 / -0 | 补正常/读异常/deadline路径响应确定关闭回归。 |
| `tests/test_petcore_install.py` | 修改 | +92 / -0 | 补3.11清理、只读文件、重试传播、staging/提交后旧目录清理失败与保留安装回归。 |
| `tests/test_petcore_island_sampling.py` | 修改 | +2 / -0 | 测试结束显式等待采样退出，匹配非阻塞stop新契约，不残留测试线程。 |
| `tests/test_petcore_island_window.py` | 修改 | +49 / -4 | 补展开折叠后停网络、收起/隐藏/禁用协调真实采样器回归。 |
| `tests/test_petcore_menu.py` | 修改 | +33 / -0 | 补GC/事件循环后子菜单动作可用及父销毁释放，覆盖所有子菜单类型。 |
| `tests/test_petcore_monitor_lifecycle.py` | 新增 | +261 / -0 | 新增18项系统/网络阻塞读、非阻塞stop、快速重启、独立取消/迟到结果/基线回归。 |
| `tests/test_petcore_music_mod.py` | 修改 | +62 / -0 | 补阻塞SMTC停用不等待且不重叠，以及旧歌词跨代丢弃回归。 |
| `tests/test_petcore_net.py` | 修改 | +11 / -0 | 补HTTP重试和归一化错误关闭回归。 |
| `tests/test_petcore_p5.py` | 修改 | +9 / -5 | 菜单对勾像素测试显式参数化亮/暗主题，按对比色判定，不改变产品QSS。 |
| `tests/test_petcore_proactive.py` | 修改 | +23 / -0 | 补旧完成/错误不清除新请求busy的世代回归。 |
| `tests/test_petcore_session.py` | 新增 | +37 / -0 | 新增真实MSG ABI及64位HWND高位反例，防假注销与漏报。 |
| `tests/test_petcore_speech.py` | 修改 | +70 / -0 | 补合成错误/异常经GUI scheduler、调度失败不触UI的真实线程回归。 |
| `tests/test_petcore_tray.py` | 修改 | +26 / -0 | 补父菜单释放与30次刷新后子菜单数量稳定回归。 |
| `tests/test_petcore_weather_mod.py` | 修改 | +42 / -0 | 补停用迟到结果/快速恢复及30轮线程引用有界回归。 |

合计 **48 个文件（4 新增，0 删除），+2039/-251 行**。

## 4. 测试与验证

### 4.1 环境和可复制命令

Windows `10.0.26100`，Python **3.11.1**（`E:\Program Files (x86)\Dev-Cpp\python.exe`），
PySide6 **6.11.1**、pytest **8.3.4**、psutil **6.1.0**、Ruff **0.16.6**、Pillow **11.2.1**；20逻辑CPU。
测试 Qt 使用 offscreen；实机探针单独设置 windows。终端默认 cp1252，显式 UTF-8 的复验和未设置时的失败分别保留。

```powershell
$env:PYTHONUTF8='1'
$env:QT_QPA_PLATFORM='offscreen'
python -m ruff check .
$files=@(Get-ChildItem tests/test_petcore_*.py | ForEach-Object {$_.FullName})
python -m pytest -q @files tests/test_architecture.py tests/test_pr_report_discipline.py tests/test_ci_workflows.py
python -m pytest -q
# 诊断完整 nodeid；原始两次 verbose 运行未设置 PYTHONUTF8
python -m pytest -vv --tb=short --junitxml=.scratch/petcore-quality-review/full-final-v2.xml
python .scratch/petcore-quality-review/stress-delivery/runner.py
```

**最终选定门禁**：**1603 passed, 1 skipped in 86.65s**（`selected-delivery.txt/xml`；唯一skip为`rapidocr not installed`，不冒充真实OCR验证）。这不是仓库全量。`ruff-final.txt` 为 `All checks passed!`。
`git diff --check` 无空白错误（Git 另提示3个测试文件将按既有配置转换 CRLF，不是失败）。
报告成稿后三个公共门禁复验：`338 passed in 3.20s`（`docs-final-gates.txt`）。
Windows MSG 关联：`59 passed, 1 skipped in 1.56s`；该组合包含平台条件跳过，不能当作所有平台执行通过。

### 4.2 先红后绿的行为证据

所有相对证据路径均在 `.scratch/petcore-quality-review/`。

| 修复族 | 修改前失败 | 修改后输出（非互斥，不能相加当全量） | 文件 |
|---|---|---|---|
| 菜单 | 11 failed,21 passed | 32 passed；托盘追加后33 passed | menu-red/green、tray-refresh-red/green.txt |
| 安装/清理 | 7 failed,19 passed | 35 passed,9.09s | install-red/green.txt |
| 系统/网络 | 12 failed,2 passed | 60 passed；关联140 passed,25.62s | monitor/red、green-expanded、related-final.txt |
| 岛折叠 | 2 failed | 88 passed,3.82s | island-red、ui-green.txt |
| Agent | 两轮5/2项失败 | 79 passed,1.20s | agent-red、agent-lifecycle-red、agent-green.txt |
| HTTP资源 | 4 failed | 151 passed,14.46s | http-red/green.txt |
| Speech线程 | 3 failed | 66 passed,2.48s | speech-red/green.txt |
| 天气/文件 | 5 failed | 38 passed；扩展相关176 passed,3.07s | mod-lifecycle-red/green、background-green.txt |
| 音乐 | 2 failed | 37 passed | music-red/green.txt |
| AI/vision/proactive | 2+2+1 failed | 98 passed,3.37s | ai-request-red、ai-vision-red、proactive-red、ai-request-green.txt |
| Windows MSG | 3 failed | 3 passed,0.81s；关联59/1skip | session-red/green/related.txt |
| 亮暗主题测试隔离 | 1 failed（806 > 840 断言不成立） | 63 passed,6.20s（含相关菜单/托盘） | menu-dark-red/green.txt |

时序用 Event/Condition 与宽超时，真实 Qt scheduler/event loop；不新增 sleep 猜时序。
最后一轮压力包含350项（采样/岛/菜单/托盘/Agent/Speech/天气/文件/音乐/AI/proactive/对勾）：
**350 passed ×3**，32.93s / 32.87s / 33.90s；20个负载进程，开跑前系统CPU99.7% /100% /99.9%。
每次 runner finally 停止/回收其自建负载进程，未终止用户进程。证据 `stress-delivery/stress-summary.json`。
早期51/283/348项压力记录保留，但不代替这一轮。

### 4.3 仓库全量：失败、崩溃和归属（未通过）

执行过 `python -m pytest -q`（`full-pytest.txt`），及两轮 verbose（`full-final.txt`、`full-final-v2.txt`）。
均在旧 `tests/test_settings_stale_form_exit.py::_exit_host` / `app.processEvents()` 组合运行中出现
**Windows access violation，退出 -1073741819**。没有正常汇总/JUnit；不得编造整仓总通过数。
v2 收集9725项，崩溃前逐行记录 **7902 PASSED、30 FAILED、24 SKIPPED**，这是截断日志计数，不是完整结算。
随后新增MSG回归、报告门禁与亮暗参数化，最终收集数量另见 coverage-audit.json（避免跨快照混加）。

| 失败类 | 定位/复验 | 归属与处理 |
|---|---|---|
| Pillow接口20项 | 8项旧 alpha/provision/unblend 测试 +12项v4；本机 Image 没有 `get_flattened_data()`；requirements 允许该 Pillow | 对应旧源码/测试未改，基线兼容缺口；没有升级依赖/改变已暂停v4或当前素材 grade 绕过 |
| 历史文档词汇1项 | `test_product_copy_has_no_external_brand_reference` 命中未改 `PR-REPORT-PETCORE-P4B2-2026-10-23.md` | 基线文档门禁；用户要求历史保留，不静默改原文或删门禁 |
| 旧菜单2项 | `test_overlay_tray_routing...exit_this...` QAction 已删除；补测 `test_sprite_menu...scale...` QMenu 已删除 | 旧产品/测试未改；不把 petcore 菜单修复扩大到旧产品全UI重构 |
| 默认编码3项 | 两个 module_level_validation + overlay_instance_gate；cp1252 写中文失败/转义 | 同三项默认编码3failed、PYTHONUTF8=1下3passed；环境条件，不声称原命令全绿 |
| petcore 对勾1项 | 暗色 palette 下重现，亮色限定断言方向错误 | 本轮已修测试，显式双主题63passed并入最终门禁/压力 |
| 其余依赖/OCR及设置顺序项 | 见下方补充与 legacy-extra-families.txt | 仍须按具体证据处理，不归入已通过 |
| 旧设置原生崩溃 | 同测试单独1passed；整仓两轮及旧族组合重现崩溃 | 顺序/对象释放关联尚未根因关闭，不足以证明所有Qt退出场景安全 |

上述 Pillow/文档/旧菜单等路径对 HEAD `git diff --quiet` 返回0（`legacy-head-comparison.txt`）。
这是“本轮未改且可独立复现”的归属证据，不是“整仓崩溃已证明与所有修改无关”。
失败诊断：`legacy-frame-failures.txt`=9failed/231passed；`full-failure-families.txt`=13failed/84passed。
报告成稿后词汇门禁复验仍仅命中上述历史文件（`legacy-copy-final.txt`：1 failed,1.36s），没有新增命中文档。
补充复验 `legacy-extra-families.txt`：**2 failed、63 passed、5 skipped，20.47s**。
- `test_pet_third_party_imports_are_declared`：旧 `pet/screen_capture/ocr_worker.py` 导入 `cv2`，requirements 没有对应显式声明。
- `test_self_built_sessions_are_injected_into_the_engine_cfg`：缺少 `omegaconf`，`ModuleNotFoundError`。本轮未擅自升级/安装依赖遮蔽该环境缺口。
- 整仓中的两个旧设置对话框断言失败（真实按钮discard、unverified提示）在这次相关组合及逐例隔离均通过；只能定位为顺序相关，不能宣称已修复。

最终 collection **9731项、480个文件**；用v2逐节点日志、隔离补测JUnit和最终选定门禁JUnit做集合审计：
当前9731个nodeid均有一次执行记录，未执行集合为空；旧未参数化的对勾用例由亮/暗两项替代。
证据 `collection-delivery.txt` / `coverage-audit.json`。**这是跨快照、跨进程的覆盖并集，不是单进程9731项通过。**

为避免81%左右崩溃后漏测，按崩溃后 collect 序列生成134个隔离任务：崩溃文件每条用例独立进程，
随后每个测试文件完整运行（3个本地测试进程并行，不是智能体）。`run_tail.py`、`tail-targets.json`、
`tail-isolated/summary.json` 与每任务JUnit记录 **1804 passed、1 failed、2 skipped**；该失败为上述旧 sprite 菜单。
这是**显式的补充覆盖**，没有改 pytest 配置、忽略列表或门禁；不能与截断数字简单相加，也不能叫“整仓全绿”。

## 5. 性能分析

### 5.1 同环境修改前后，预热15秒、采集60秒、重复3次

命令：`python .scratch/petcore-quality-review/perf_sampling.py --baseline` / 不加 `--baseline`。
基线从本轮 HEAD 提取 sysmon/netmon，只在探针进程加载，不回写工作区产品文件。
每版活跃/隐藏各3轮，真实 Windows psutil；CPU为进程时间/墙钟的**单核百分比**。
此探针不是全桌宠内存；同时运行的 pytest/压力测试造成环境噪声，不能把细小CPU差异归因为修复。

| 状态/版本 | CPU三次 % | 中位数 % | 每60秒 CPU/mem/net读取 | 线程min–max（每轮） | 采集期磁盘读/写字节 |
|---|---|---|---|---|---|
| 活跃前 | 1.4378 /2.0275 /1.4884 | 1.4884 | 60/60/60，每轮一致 | 5–8 /4–5 /5–5 | 0/0，每轮 |
| 活跃后 | 1.7216 /1.5414 /1.3871 | 1.5414 | 60/60/60，每轮一致 | 5–8 /4–5 /5–5 | 0/0，每轮 |
| 隐藏前 | .4107 /.4110 /.4878 | .4110 | 0/0/0，每轮一致 | 2–3 /3–3 /1–3 | 0/0，每轮 |
| 隐藏后 | .5648 /.7191 /.4110 | .5648 | 0/0/0，每轮一致 | 2–3 /3–3 /1–3 | 0/0，每轮 |

RSS（每轮 起点→终点，括号为峰值；字节，原始数据便于复算）：

| 状态 | 第1轮 | 第2轮 | 第3轮 |
|---|---|---|---|
| 活跃前 | 23605248→23228416(23879680) | 23822336→23441408(23879680) | 23498752→23085056(23515136) |
| 活跃后 | 22921216→23011328(23605248) | 23035904→23711744(23711744) | 23162880→23941120(23941120) |
| 隐藏前 | 22904832→22970368(23486464) | 22970368→22913024(22970368) | 22974464→23539712(23539712) |
| 隐藏后 | 23900160→22896640(23900160) | 22908928→22908928(22908928) | 22908928→22867968(22908928) |

没有证据声称“CPU更低”或“完全无内存增长”；关键改进是停用响应、零隐藏读取、无重叠worker。
采样线程本体仍最多 system/network 各1条；表中线程含 Python/psutil/测量环境的系统线程。

### 5.2 启停与阻塞读取

`start_stop_probe.py [--baseline]`：每监控预热5次、测30次，start/stop后在非GUI显式join旧线程。
数字为**函数返回耗时**，不是首个有效样本耗时。前后探针Python线程均1→1。

| 路径 | start中位数前→后 ms | stop中位数前→后 ms |
|---|---|---|
| system | .130850→.142750 | .028050→.003300 |
| network | .081550→.089150 | .020500→.001900 |

真实60秒活跃测试中的双监控stop总耗时：前 .5670/.7147/.4198ms；后 .0578/.0494/.0662ms。
另以Event卡住读取，5次测量（`monitor/latency.json`）：system stop中位 **2006.1424→.0153ms**，
network **2005.3323→.0183ms**。旧版返回后worker仍活但running为false；新版running真实反映活线程，
不再用“丢引用”伪装停止。取消不强杀OS调用，释放Event后再等待退出，回归验证不启动重叠线程。
初版启停探针误取旧字段而漏join；已保留 `initial-start-stop-*`、修正 `_sampling._thread` 后重测，表中仅用修正结果。

### 5.3 资源循环与新增成本

Windows原生源码探针5轮预热+30轮测量，两个独立运行均保留（不能只挑较好一次）：

| 操作 | native-final | 最后 native-current |
|---|---|---|
| 托盘30刷新 | 子QMenu2→2；系统线程24→24；RSS+28672B | 子QMenu2→2；线程22→24；RSS+1015808B |
| 菜单创建/销毁+采样开关30轮 | QMenu0→0；线程22→22；RSS不变 | QMenu0→0；线程22→22；RSS+16384B |
| 退出 | Python线程仅MainThread，exit0 | Python线程仅MainThread，exit0 |

菜单残留没有逐轮增长；后一次托盘阶段存在约0.97MiB RSS和2条系统线程上升，随后开关阶段22条，
不能从30次有限样本认定所有Qt缓存无增长；长时老化仍为缺口。基线菜单在此Qt环境提前失效，
未捏造其30轮可操作性能，也未完成整应用15/60×3的前后对照，采样实测不能代表全应用性能。

- 稳态增加短锁/世代比较，无新增轮询频率；每采样周期 system CPU+mem、network 计数读取各一次。
- 开启/恢复仅重置基线，清空快照；取消后至旧OS调用返回保留1条旧daemon，无新增替代worker。
- QMenu刷新增加按旧子菜单数的 deleteLater（定向对象，不全局flush）；触发频率仅菜单刷新。
- HTTP增加已有响应/异常流的 close，不新增网络请求；磁盘清理只在安装事务错误/替换路径重试或保留残留。
- AI每个流式片段增加/明确scheduler发布与身份检查；没有新增常驻线程，但真实模型流的CPU/吞吐未测。
- 天气/文件完成线程剪枝、取消及进度handle回收；音乐/Agent沿用既有tick，Agent只在等待旧线程退出时100ms重试。
- 没有新增依赖、遥测、后台网络、磁盘扫描服务；本轮新增的是生命周期协调与回归测试。

## 6. 实机运行记录

命令：`python .scratch/petcore-quality-review/native_probe_current.py`；入口实际调用 `petcore.ui.app.run`，
`QT_QPA_PLATFORM=windows`，配置仅 `.scratch/petcore-quality-review/native-current/native-data`。
关闭 frameseq 首跑供给、外部mods/账号、快捷键与自启，保留真实 Qt窗口/托盘/psutil/媒体后端；不是 offscreen 或 mock UI。
只有1块 `\\.\DISPLAY1`，DPR **1.25**，逻辑1536×864；不能沿用历史150%/多屏证据。

| 场景 | 实际结果 |
|---|---|
| 源码启动/托盘 | tray_available=true、tray_visible=true，13个子菜单GC后有效；动作与父销毁验证通过 |
| 设置取消/保存 | 预览后取消还原scale .72；保存 .85 且隔离磁盘配置一致；非模态窗口可见 |
| 多宠 | slots[0,1]，主 .85/子 .5，各自配置隔离，关闭子宠后退出正常 |
| 灵动岛 | 真实system CPU36.9%、mem78.7%；展开folded=[network]且network_running=false；收起恢复；隐藏/禁用停止 |
| 30轮资源 | 见§5.3；定向菜单销毁，采样开关后无遗留QMenu |
| 退出 | exitcode0，13.2362642s总流程；结束Python线程仅MainThread |

`native-current-output.txt` / `native-current/native-result.json` 保存原始记录。
截图仅对本应用widget.grab，未截全桌面/真实账号、未上传外部服务；已查看最终菜单/展开岛图，原始设置等图保留。
截图在 `native-current/` 的 native-menu/settings/tray-menu/pet/island/island-expanded.png。
早期探针错误设 frameseq=only，启动过工作区素材供给；初始脚本/输出保留，改off后复验，git未出现素材改动，
未据此声称安装或素材重建验收。实机为自动化驱动+截图核看，不冒充人工鼠标逐项体验。

### 6.1 其他环境探针和缺口

- Python3.12.13 可执行存在，但 pytest/PySide6/psutil/Ruff 均不可导入。用 stdlib实际完成 install→只读旧文件覆盖→remove→只读rmtree；`python312-smoke.txt` 全True。**不是3.12完整GUI/测试验证**，未安装依赖。
- Windows `wintypes.MSG` 在真实解释器内构造并调用filter，3个回归通过；没有发系统关机/注销消息。
- 构建探针 PyInstaller/psutil/winrt/keyring 可导入，rapidocr不可导入，`.venv`不存在；脚本要求该环境。未build/安装，不通过修改安全策略/证书或覆盖现安装获得结果。
- 仅单屏：不能验证跨屏、混合DPI；无macOS/Linux执行环境。外部API/余额/钥匙串持久化/实际TTS声卡/SMTC播放器和OCR引擎没有本轮端到端结果。
- UI阶段没有真实网络或敏感配置；媒体既有适配链不等于所有旧pet测试在此依赖组合下可运行。

## 7. 限制、剩余事项与下一阶段建议

**当前阻断：整仓正常退出和全绿未达成；性能覆盖限采样与短循环、外部/多平台/安装器证据不全。**
不能因选定门禁全绿就提交“无问题/全部完成”结论。

1. 下一轮优先单独修整仓基线：Pillow声明范围与实际API、缺失依赖/OCR适配测试、旧菜单所有权、历史文档词汇门禁；保留素材grade与用户数据边界。
2. 对旧设置退出原生崩溃建立最小顺序复现/进程边界，修生命周期后重跑真正的 `python -m pytest -q`；不靠全局Qt补丁/跳过用例宣称成功。
3. 固定验证环境编码与依赖；完成无并行干扰的整应用性能/长时资源测试，再补有条件的真实外部服务、双屏、其他Python与安装器验收。
4. 质量门禁闭环后再提出功能优先级：提醒调度/农历/签文、Agent写端、岛二阶段均应单独确认需求与隐私边界。**本轮不自动进入任何这些阶段，也不启动P4-c3分发。**

证据留存与准确断点：`.scratch/petcore-quality-review/HANDOFF.md`、`review.md`、`coverage-audit.json`。
